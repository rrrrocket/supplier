import json
import re
from datetime import datetime
from pathlib import Path

import pdfplumber


PDF = Path("零售商  郡士价目表240801 .pdf")
OUT = Path("tmp/pdfs/gunze_parsed.json")


def clean(v):
    return " ".join((v or "").replace("\u3000", " ").split())


def date_value(s):
    s = clean(s)
    for fmt in ("%y.%m.%d", "%y.%m"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def expand_codes(raw):
    """Expand alpha+number lists/ranges, preserving series wildcards separately."""
    text = clean(raw).replace("，", ",").replace("、", ",").replace("／", "/")
    if not text:
        return [], "blank"
    # Product series and N/H are descriptions, not safely enumerable codes.
    if re.match(r"^N\s*,\s*H", text):
        return [], "wildcard"
    if not re.search(r"\d", text):
        return [], "wildcard"
    token_re = re.compile(r"(?P<prefix>[A-Za-z]+)?(?P<start>\d+)(?:\s*-\s*(?P<eprefix>[A-Za-z]+)?(?P<end>\d+))?")
    matches = list(token_re.finditer(text))
    if not matches:
        return [], "unparsed"
    result = []
    last_prefix = None
    for m in matches:
        prefix = m.group("prefix") or last_prefix
        if not prefix:
            continue
        last_prefix = prefix
        start_s = m.group("start")
        start = int(start_s)
        end_s = m.group("end")
        end_prefix = m.group("eprefix") or prefix
        if end_s is None:
            nums = [start]
        else:
            end = int(end_s)
            # Short right-hand ranges such as GX112-13 mean GX112..GX113.
            if len(end_s) < len(start_s):
                scale = 10 ** len(end_s)
                end = (start // scale) * scale + end
                if end < start:
                    end += scale
            nums = range(start, end + 1)
        width = len(start_s)
        for n in nums:
            # Preserve zero padding from the source start token.
            result.append(f"{prefix}{n:0{width}d}")
        last_prefix = end_prefix
    return list(dict.fromkeys(result)), "expanded"


def parse():
    rows = []
    with pdfplumber.open(PDF) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            table = page.extract_tables()[0]
            data_rows = table[3:]
            previous = None
            for row_no, row in enumerate(data_rows, 4):
                cells = [clean(x) for x in row]
                if len(cells) < 8:
                    continue
                date, category, code, pack, carton, jpy, wholesale, retail = cells[:8]
                # The HUG 24.08.01 continuation row carries the prior code/category.
                if not code and (wholesale or retail or jpy) and previous:
                    category = previous["category"]
                    code = previous["code_raw"]
                if not code or not (wholesale or retail or jpy):
                    continue
                previous = {"category": category, "code_raw": code}
                codes, parse_kind = expand_codes(code)
                changed = bool(re.search(r"更\s*改\s*价", category))
                # The PDF sometimes inserts spaces between the three Chinese characters.
                base_category = re.sub(r"更\s*改\s*价", "", category).strip()
                # Known discontinued items visible in the right-side annotations.
                status = "INACTIVE" if set(codes) & {"CS511", "CS513", "B504", "B505", "B506"} else "ACTIVE"
                try:
                    wholesale_num = float(wholesale.replace(",", ""))
                except ValueError:
                    wholesale_num = None
                row_obj = {
                    "page": page_no,
                    "source_row": row_no,
                    "date": date_value(date),
                    "category": base_category,
                    "category_raw": category,
                    "code_raw": code,
                    "codes": codes,
                    "parse_kind": parse_kind,
                    "changed": changed,
                    "jpy_raw": jpy,
                    "wholesale": wholesale_num,
                    "retail": retail,
                    "pack": pack,
                    "carton": carton,
                    "status": status,
                }
                rows.append(row_obj)

    candidates = {}
    for row in rows:
        for code in row["codes"]:
            candidates.setdefault(code, []).append(row)
    selected = []
    conflicts = []
    for sku, options in sorted(candidates.items()):
        def rank(r):
            specificity = 3 if re.fullmatch(r"[A-Za-z]+\d+", r["code_raw"].strip()) else 2
            return (r["date"] or "0000-00-00", int(r["changed"]), specificity, r["page"], r["source_row"])
        ordered = sorted(options, key=rank, reverse=True)
        winner = ordered[0]
        distinct = {(x["wholesale"], x["retail"], x["jpy_raw"]) for x in options}
        if len(distinct) > 1:
            conflicts.append({"sku": sku, "options": options, "winner": winner})
        selected.append({
            "product_name": winner["category"],
            "brand": "郡士",
            "category": winner["category"].split()[0] if winner["category"] else "郡士产品",
            "supplier_sku": sku,
            "model": sku,
            "price": winner["wholesale"],
            "currency": "CNY",
            "moq": int(re.search(r"\d+", winner["pack"]).group()) if re.search(r"\d+", winner["pack"]) else 1,
            "status": winner["status"],
            "effective_date": winner["date"] or "",
            "source_page": winner["page"],
            "source_row": winner["source_row"],
            "source_code_raw": winner["code_raw"],
            "is_changed_price": "是" if winner["changed"] else "否",
            "jpy_price_raw": winner["jpy_raw"],
            "retail_guide_price": winner["retail"],
            "parse_rule": winner["parse_kind"],
            "review_reason": "同 SKU 存在历史价格，已按规则选最新有效记录" if len(options) > 1 else "",
        })
    wildcard_rows = [r for r in rows if r["parse_kind"] == "wildcard"]
    review_rows = []
    for r in wildcard_rows:
        review_rows.append({
            "source_page": r["page"], "source_row": r["source_row"],
            "category_raw": r["category_raw"], "source_code_raw": r["code_raw"],
            "effective_date": r["date"] or "", "wholesale": r["wholesale"],
            "retail": r["retail"], "jpy_price_raw": r["jpy_raw"],
            "reason": "系列/排除规则，需与 ERP 产品主数据匹配后才能展开",
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"selected": selected, "review": review_rows, "conflicts": len(conflicts)}, ensure_ascii=False, indent=2))
    print(json.dumps({"selected": len(selected), "review": len(review_rows), "conflicts": len(conflicts)}))


if __name__ == "__main__":
    parse()

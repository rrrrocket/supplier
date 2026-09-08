from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.api.deps import DbSession, SupplierUser
from app.models.entities import (
    ImportJob,
    ImportStatus,
    InventorySnapshot,
    OfferStatus,
    Product,
    ProductStatus,
    SupplierOffer,
)
from app.services.events import record_event
from app.services.catalog import ensure_supplier_sku, resolve_brand
from app.services.import_mapping import (
    FIELD_DEFINITIONS,
    MAX_IMPORT_ROWS,
    SheetImportConfig,
    infer_defaults,
    infer_mapping,
    inspect_excel_workbook,
    mapping_view,
    normalize_rows,
    parse_excel_sheets,
    parse_table,
)


router = APIRouter(prefix="/imports", tags=["数据导入"])
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_IMPORT_FORM_PART_SIZE = 8 * 1024 * 1024
MAX_FINAL_IMPORT_REQUEST_SIZE = 20 * 1024 * 1024
IMPORT_REQUEST_SIZE_ERROR = "导入请求不能超过 20MB"
UPLOAD_READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class SubmittedRow:
    values: dict[str, str]
    source_sheet: str | None
    source_row: int
    included: bool


def _to_int(value: str, default: int, field_name: str) -> int:
    if not value:
        return default
    match = re.search(r"[-+]?\d+(?:\.\d+)?", value.replace(",", ""))
    if not match:
        raise ValueError(f"{field_name}必须是整数")
    try:
        result = int(float(match.group()))
    except ValueError as exc:
        raise ValueError(f"{field_name}必须是整数") from exc
    if result < 0:
        raise ValueError(f"{field_name}不能小于0")
    return result


def _to_decimal(value: str) -> Decimal:
    cleaned = re.sub(r"[^0-9.\-]", "", value.replace(",", ""))
    try:
        result = Decimal(cleaned)
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError("价格格式不正确") from exc
    if result <= 0:
        raise ValueError("价格必须大于0")
    return result


def _normalize_fulfillment(value: str) -> str:
    normalized = value.strip().upper()
    labels = {
        "采购": "PURCHASE",
        "自营采购": "PURCHASE",
        "一件代发": "DROPSHIP",
        "代发": "DROPSHIP",
        "寄售": "CONSIGNMENT",
        "联营": "JOINT_OPERATION",
        "联营代运营": "JOINT_OPERATION",
    }
    return labels.get(value.strip(), normalized or "PURCHASE")


def _normalize_status(value: str) -> str:
    normalized = value.strip().upper()
    labels = {
        "有效": "ACTIVE",
        "在售": "ACTIVE",
        "启用": "ACTIVE",
        "草稿": "DRAFT",
        "停售": "PAUSED",
        "暂停": "PAUSED",
        "过期": "EXPIRED",
    }
    return labels.get(value.strip(), normalized or OfferStatus.ACTIVE.value)


def _validate_row(row: dict[str, str]) -> list[str]:
    errors = []
    required = {
        "product_name": "商品名称不能为空",
        "category": "类目不能为空",
        "supplier_sku": "供应商SKU不能为空",
        "price": "价格不能为空",
    }
    for field, message in required.items():
        if not row.get(field):
            errors.append(message)
    if row.get("price"):
        try:
            _to_decimal(row["price"])
        except ValueError as exc:
            errors.append(str(exc))
    for field, default, label in (
        ("moq", 1, "起订量"),
        ("stock_qty", 0, "库存"),
        ("lead_time_days", 3, "交期"),
    ):
        try:
            _to_int(row.get(field, ""), default, label)
        except ValueError as exc:
            errors.append(str(exc))
    return errors


def _job_view(job: ImportJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "file_name": job.file_name,
        "import_type": job.import_type,
        "status": job.status,
        "total_rows": job.total_rows,
        "success_rows": job.success_rows,
        "error_rows": job.error_rows,
        "errors": job.errors,
        "created_at": job.created_at,
    }


async def _read_upload(
    file: UploadFile,
    *,
    excel_only: bool = False,
) -> tuple[str, bytes]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="请选择表格文件")
    extension = file.filename.lower().rsplit(".", 1)[-1]
    if excel_only and extension not in {"xlsx", "xls"}:
        raise HTTPException(
            status_code=400,
            detail="工作簿扫描仅支持 XLSX 和 XLS 格式",
        )
    if extension not in {"csv", "tsv", "txt", "xlsx", "xls", "pdf"}:
        raise HTTPException(status_code=400, detail="支持 CSV、XLSX、XLS 和 PDF 格式")
    raw = bytearray()
    while True:
        remaining_with_guard = MAX_FILE_SIZE - len(raw) + 1
        chunk = await file.read(min(UPLOAD_READ_CHUNK_SIZE, remaining_with_guard))
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_FILE_SIZE:
            raise HTTPException(status_code=413, detail="文件不能超过 10MB")
    return file.filename, bytes(raw)


def _import_form_text(
    form,
    field_name: str,
    *,
    max_length: int | None = None,
) -> str:
    value = form.get(field_name, "")
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field_name}格式不正确")
    if max_length is not None and len(value) > max_length:
        raise HTTPException(status_code=400, detail=f"{field_name}内容过长")
    return value


async def _read_final_import_form(
    request: Request,
) -> tuple[str, bytes, str, str, str, str, str]:
    async def bounded_stream():
        total_bytes = 0
        async for chunk in request.stream():
            total_bytes += len(chunk)
            if total_bytes > MAX_FINAL_IMPORT_REQUEST_SIZE:
                raise MultiPartException(IMPORT_REQUEST_SIZE_ERROR)
            yield chunk

    parser = MultiPartParser(
        request.headers,
        bounded_stream(),
        max_files=1,
        max_fields=5,
        max_part_size=MAX_IMPORT_FORM_PART_SIZE,
    )
    try:
        form = await parser.parse()
    except MultiPartException as exc:
        status_code = 413 if exc.message == IMPORT_REQUEST_SIZE_ERROR else 400
        raise HTTPException(status_code=status_code, detail=exc.message) from exc

    try:
        upload = form.get("file")
        if not isinstance(upload, StarletteUploadFile):
            raise HTTPException(status_code=400, detail="请选择表格文件")
        filename, raw = await _read_upload(upload)
        return (
            filename,
            raw,
            _import_form_text(form, "description", max_length=2_000),
            _import_form_text(form, "mapping_json"),
            _import_form_text(form, "defaults_json"),
            _import_form_text(form, "rows_json"),
            _import_form_text(form, "sheet_configs_json"),
        )
    finally:
        await form.close()


def _json_object(value: str, field_name: str) -> dict[str, str]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name}格式不正确") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail=f"{field_name}必须是对象")
    return {str(key): str(item) for key, item in data.items() if item is not None}


def _effective_mapping(
    headers: list[str],
    description: str,
    mapping_json: str,
) -> dict[str, str]:
    mapping = infer_mapping(headers, description)
    overrides = _json_object(mapping_json, "字段映射")
    for field, source in overrides.items():
        if field not in FIELD_DEFINITIONS:
            continue
        if source and source not in headers:
            raise HTTPException(status_code=400, detail=f"字段映射引用了不存在的列：{source}")
        if source:
            mapping[field] = source
        else:
            mapping.pop(field, None)
    return mapping


def _effective_defaults(description: str, defaults_json: str) -> dict[str, str]:
    defaults = infer_defaults(description)
    defaults.update(_json_object(defaults_json, "默认值"))
    return defaults


def _sheet_configs(value: str) -> list[SheetImportConfig]:
    try:
        data = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="工作表配置格式不正确") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="工作表配置必须是数组")
    if not data:
        raise HTTPException(status_code=400, detail="请至少选择一个工作表")

    configs: list[SheetImportConfig] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=400,
                detail=f"工作表配置第 {index} 项格式不正确",
            )
        sheet_name = item.get("sheet_name")
        header_row = item.get("header_row")
        mapping = item.get("mapping", {})
        defaults = item.get("defaults", {})
        if not isinstance(sheet_name, str) or not sheet_name:
            raise HTTPException(
                status_code=400,
                detail=f"工作表配置第 {index} 项缺少工作表名称",
            )
        if (
            not isinstance(header_row, int)
            or isinstance(header_row, bool)
            or header_row < 1
        ):
            raise HTTPException(
                status_code=400,
                detail=f"工作表 {sheet_name} 的表头行必须是正整数",
            )
        if not isinstance(mapping, dict) or not all(
            isinstance(key, str) and isinstance(source, str)
            for key, source in mapping.items()
        ):
            raise HTTPException(
                status_code=400,
                detail=f"工作表 {sheet_name} 的字段映射必须是对象",
            )
        if not isinstance(defaults, dict) or not all(
            isinstance(key, str) and isinstance(default, str)
            for key, default in defaults.items()
        ):
            raise HTTPException(
                status_code=400,
                detail=f"工作表 {sheet_name} 的默认值必须是对象",
            )
        configs.append(
            SheetImportConfig(
                sheet_name=sheet_name,
                header_row=header_row,
                mapping=mapping,
                defaults=defaults,
            )
        )
    return configs


def _duplicate_skus(rows: list[dict[str, str]]) -> set[str]:
    counts: dict[str, int] = {}
    for row in rows:
        supplier_sku = row.get("supplier_sku", "").strip()
        if supplier_sku:
            counts[supplier_sku] = counts.get(supplier_sku, 0) + 1
    return {supplier_sku for supplier_sku, count in counts.items() if count > 1}


def _submitted_rows(
    rows_json: str,
    *,
    allowed_source_sheets: set[str] | None = None,
    require_sheet_configs: bool = False,
) -> list[SubmittedRow] | None:
    if not rows_json:
        return None
    try:
        data = json.loads(rows_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="目标列表格式不正确") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="目标列表必须是数组")
    if not data:
        raise HTTPException(status_code=400, detail="目标列表至少保留一行")

    rows: list[SubmittedRow] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=400,
                detail=f"目标列表第 {index} 行格式不正确",
            )

        nested = "values" in item
        if nested and require_sheet_configs:
            raise HTTPException(
                status_code=400,
                detail="Excel 多工作表导入缺少工作表配置",
            )
        source_sheet = item.get("source_sheet")
        if source_sheet is not None and not isinstance(source_sheet, str):
            raise HTTPException(
                status_code=400,
                detail=f"目标列表第 {index} 行来源工作表格式不正确",
            )
        source_row = item.get("source_row", index)
        if (
            not isinstance(source_row, int)
            or isinstance(source_row, bool)
            or source_row < 1
        ):
            raise HTTPException(
                status_code=400,
                detail=f"目标列表第 {index} 行来源行号格式不正确",
            )
        included = item.get("included", True)
        if not isinstance(included, bool):
            raise HTTPException(
                status_code=400,
                detail=f"目标列表第 {index} 行是否导入格式不正确",
            )
        raw_values = item.get("values", item)
        if not isinstance(raw_values, dict):
            raise HTTPException(
                status_code=400,
                detail=f"目标列表第 {index} 行字段值格式不正确",
            )
        if not included:
            continue
        if (
            nested
            and allowed_source_sheets is not None
            and source_sheet not in allowed_source_sheets
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"目标列表第 {index} 行来源工作表未被选择："
                    f"{source_sheet or '空'}"
                ),
            )
        rows.append(
            SubmittedRow(
                values={
                    field: str(raw_values.get(field, "") or "").strip()
                    for field in FIELD_DEFINITIONS
                },
                source_sheet=source_sheet or None,
                source_row=source_row,
                included=included,
            )
        )
    if not rows:
        raise HTTPException(status_code=400, detail="目标列表至少保留一行")
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(status_code=400, detail=f"单次最多导入 {MAX_IMPORT_ROWS} 行")

    duplicate_skus = sorted(_duplicate_skus([row.values for row in rows]))
    if duplicate_skus:
        raise HTTPException(
            status_code=400,
            detail=f"供应商 SKU 在本次导入中重复：{'、'.join(duplicate_skus)}",
        )
    return rows


@router.get("")
def list_imports(db: DbSession, user: SupplierUser) -> list[dict[str, Any]]:
    jobs = db.scalars(
        select(ImportJob)
        .where(ImportJob.organization_id == user.organization_id)
        .order_by(ImportJob.created_at.desc())
        .limit(30)
    ).all()
    return [_job_view(job) for job in jobs]


@router.post("/product-offers/workbook/inspect")
async def inspect_product_offer_workbook(
    user: SupplierUser,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    del user
    filename, raw = await _read_upload(file, excel_only=True)
    try:
        inspection = inspect_excel_workbook(raw, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return asdict(inspection)


@router.post("/product-offers/preview")
async def preview_product_offers(
    user: SupplierUser,
    file: UploadFile = File(...),
    description: str = Form(default="", max_length=2000),
    mapping_json: str = Form(default=""),
    defaults_json: str = Form(default=""),
    sheet_configs_json: str = Form(default=""),
) -> dict[str, Any]:
    del user
    filename, raw = await _read_upload(file)
    if sheet_configs_json:
        configs = _sheet_configs(sheet_configs_json)
        try:
            sourced_rows = parse_excel_sheets(raw, filename, configs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        duplicate_skus = _duplicate_skus([row.values for row in sourced_rows])
        preview_rows = []
        valid_rows = 0
        for sourced in sourced_rows:
            errors = _validate_row(sourced.values)
            if not errors:
                valid_rows += 1
            supplier_sku = sourced.values.get("supplier_sku", "").strip()
            preview_rows.append(
                {
                    "row": sourced.source_row,
                    "source_sheet": sourced.source_sheet,
                    "source_row": sourced.source_row,
                    "included": True,
                    "conflict_group": (
                        supplier_sku if supplier_sku in duplicate_skus else None
                    ),
                    "values": sourced.values,
                    "errors": errors,
                }
            )

        invalid_rows = len(sourced_rows) - valid_rows
        warnings = []
        if invalid_rows:
            warnings.append(f"检测到 {invalid_rows} 行数据需要修正")
        if duplicate_skus:
            warnings.append(f"检测到 {len(duplicate_skus)} 组重复供应商 SKU")
        return {
            "file_name": filename,
            "sheet_name": None,
            "header_row": None,
            "total_rows": len(sourced_rows),
            "valid_rows": valid_rows,
            "invalid_rows": invalid_rows,
            "headers": [],
            "mapping": [],
            "defaults": {},
            "preview_rows": preview_rows,
            "warnings": warnings,
            "conflict_count": len(duplicate_skus),
            "can_import": not duplicate_skus,
        }

    try:
        table = parse_table(raw, filename, description)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    mapping = _effective_mapping(table.headers, description, mapping_json)
    defaults = _effective_defaults(description, defaults_json)
    rows = normalize_rows(table, mapping, defaults)
    preview_rows = []
    valid_rows = 0
    for offset, row in enumerate(rows, start=1):
        errors = _validate_row(row)
        if not errors:
            valid_rows += 1
        preview_rows.append(
            {
                "row": table.header_row + offset,
                "values": row,
                "errors": errors,
            }
        )

    missing_fields = [
        definition["label"]
        for field, definition in FIELD_DEFINITIONS.items()
        if definition["required"] and not mapping.get(field) and not defaults.get(field)
    ]
    warnings = []
    if missing_fields:
        warnings.append(f"仍需指定：{'、'.join(missing_fields)}")
    invalid_rows = len(rows) - valid_rows
    if invalid_rows:
        warnings.append(f"检测到 {invalid_rows} 行数据需要修正")

    return {
        "file_name": filename,
        "sheet_name": table.sheet_name,
        "header_row": table.header_row,
        "total_rows": len(rows),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
        "headers": table.headers,
        "mapping": mapping_view(mapping, table.headers),
        "defaults": defaults,
        "preview_rows": preview_rows,
        "warnings": warnings,
    }


@router.post("/product-offers", status_code=status.HTTP_201_CREATED)
async def import_product_offers(
    request: Request,
    db: DbSession,
    user: SupplierUser,
) -> dict[str, Any]:
    (
        filename,
        raw,
        description,
        mapping_json,
        defaults_json,
        rows_json,
        sheet_configs_json,
    ) = await _read_final_import_form(request)
    job = ImportJob(
        organization_id=user.organization_id,
        file_name=filename,
        import_type="SMART_PRODUCT_OFFER",
        status=ImportStatus.PROCESSING.value,
    )
    db.add(job)
    db.flush()

    try:
        extension = filename.lower().rsplit(".", 1)[-1]
        allowed_source_sheets: set[str] | None = None
        if sheet_configs_json:
            configs = _sheet_configs(sheet_configs_json)
            if extension not in {"xlsx", "xls"}:
                raise HTTPException(
                    status_code=400,
                    detail="工作表配置仅支持 XLSX 和 XLS 格式",
                )
            parse_excel_sheets(raw, filename, configs)
            allowed_source_sheets = {config.sheet_name for config in configs}
        rows = _submitted_rows(
            rows_json,
            allowed_source_sheets=allowed_source_sheets,
            require_sheet_configs=(
                extension in {"xlsx", "xls"} and not sheet_configs_json
            ),
        )
        if rows is None:
            table = parse_table(raw, filename, description)
            mapping = _effective_mapping(table.headers, description, mapping_json)
            defaults = _effective_defaults(description, defaults_json)
            rows = [
                SubmittedRow(
                    values=row,
                    source_sheet=table.sheet_name,
                    source_row=table.header_row + offset,
                    included=True,
                )
                for offset, row in enumerate(
                    normalize_rows(table, mapping, defaults),
                    start=1,
                )
            ]
        else:
            mapping = {}
    except (ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        job.status = ImportStatus.FAILED.value
        job.errors = [{"row": 0, "message": message}]
        job.error_rows = 1
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=message) from exc

    errors: list[dict[str, Any]] = []
    success = 0
    for submitted in rows:
        row = submitted.values
        row_transaction = db.begin_nested()
        try:
            row_errors = _validate_row(row)
            if row_errors:
                raise ValueError("；".join(row_errors))

            price = _to_decimal(row["price"])
            moq = max(1, _to_int(row["moq"], 1, "起订量"))
            stock_qty = _to_int(row["stock_qty"], 0, "库存")
            lead_time_days = _to_int(row["lead_time_days"], 3, "交期")
            brand = resolve_brand(db, row["brand"])
            model = row["model"] or None
            product = db.scalar(
                select(Product).where(
                    Product.created_by_organization_id == user.organization_id,
                    Product.name == row["product_name"],
                    Product.brand_id == brand.id,
                    Product.model == model,
                )
            )
            if product is None:
                product = Product(
                    created_by_organization_id=user.organization_id,
                    name=row["product_name"],
                    brand_id=brand.id,
                    brand=brand.name,
                    model=model,
                    category=row["category"],
                    status=ProductStatus.ACTIVE.value,
                )
                db.add(product)
                db.flush()

            supplier_sku = ensure_supplier_sku(
                db,
                supplier_id=user.organization_id,
                brand_id=brand.id,
                product_id=product.id,
                variant_id=None,
                supplier_sku_code=row["supplier_sku"],
            )
            offer = db.scalar(
                select(SupplierOffer).where(
                    SupplierOffer.supplier_sku_id == supplier_sku.id,
                )
            )
            if offer is None:
                offer = SupplierOffer(
                    organization_id=user.organization_id,
                    product_id=product.id,
                    supplier_sku_id=supplier_sku.id,
                    supplier_sku=supplier_sku.supplier_sku_code,
                    price=price,
                    currency=(row["currency"] or "CNY").upper(),
                    moq=moq,
                    stock_qty=stock_qty,
                    lead_time_days=lead_time_days,
                    fulfillment_mode=_normalize_fulfillment(row["fulfillment_mode"]),
                    status=_normalize_status(row["status"]),
                )
                db.add(offer)
                db.flush()
            else:
                offer.product_id = product.id
                offer.price = price
                offer.currency = (row["currency"] or "CNY").upper()
                offer.moq = moq
                offer.stock_qty = stock_qty
                offer.lead_time_days = lead_time_days
                offer.fulfillment_mode = _normalize_fulfillment(row["fulfillment_mode"])
                offer.status = _normalize_status(row["status"])

            db.add(
                InventorySnapshot(
                    offer_id=offer.id,
                    quantity=stock_qty,
                    source="SMART_TABLE_IMPORT",
                )
            )
            row_transaction.commit()
            success += 1
        except ValueError as exc:
            row_transaction.rollback()
            errors.append(
                {
                    "sheet": submitted.source_sheet,
                    "row": submitted.source_row,
                    "message": str(exc),
                }
            )

    job.total_rows = len(rows)
    job.success_rows = success
    job.error_rows = len(errors)
    job.errors = errors[:100]
    if success and errors:
        job.status = ImportStatus.PARTIAL.value
    elif success:
        job.status = ImportStatus.COMPLETED.value
    else:
        job.status = ImportStatus.FAILED.value

    record_event(
        db,
        event_type="PRODUCT_OFFERS_IMPORTED",
        entity_type="ImportJob",
        entity_id=job.id,
        organization_id=user.organization_id,
        actor_type="USER",
        actor_id=user.id,
        payload={
            "file_name": job.file_name,
            "import_mode": "SMART_TABLE_MAPPING",
            "total_rows": job.total_rows,
            "success_rows": job.success_rows,
            "error_rows": job.error_rows,
            "mapping": mapping,
        },
    )
    db.commit()
    db.refresh(job)
    return _job_view(job)

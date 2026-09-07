# Excel 多工作表导入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让供应商扫描 Excel 工作簿、选择一个或多个 Sheet、分别配置字段映射，并在解决跨 Sheet 重复 SKU 后统一导入。

**Architecture:** 后端把 Excel 读取拆成工作簿扫描和按配置解析两层，列字母作为稳定字段标识；API 保留现有单表入口，同时增加扫描接口和多 Sheet 配置。前端保存完整预览状态，每页渲染 50 行，并在提交前和服务端分别校验重复 SKU。

**Tech Stack:** Python 3.13、FastAPI、openpyxl、xlrd、PostgreSQL 16（端口 `6432`）、原生 JavaScript、Node.js test runner

**Spec:** `docs/designs/2026-09-08-multi-sheet-excel-import-design.md`

## Global Constraints

- `.xlsx` 和 `.xls` 支持选择一个或多个 Sheet；CSV、TSV、TXT、PDF 保持单数据源流程。
- 每个 Sheet 独立保存表头行、字段映射和默认值。
- 列映射使用 Excel 列字母；空表头显示为 `C列（无表头）`。
- 腾讯文档空 Fill 兼容只在内存中进行，不修改、不保存原始文件。
- 本次提交中的重复供应商 SKU 必须人工解决；数据库中已有相同 SKU 继续 Upsert。
- 所有 Sheet 合计最多 10,000 行；前端每页只渲染 50 行。
- PostgreSQL 仍是唯一数据库，内部端口仍为 `6432`。
- 不读取、输出或提交 `.env`；不提交 `Trumpeter.xlsx`。

## 文件职责

- `app/services/import_mapping.py`：打开兼容后的工作簿、扫描 Sheet、生成列描述、按 Sheet 配置解析原始行。
- `app/api/routes/imports.py`：解析表单 JSON、暴露扫描/预览/导入接口、校验来源和重复 SKU。
- `app/web/assets/import-workbook.js`：无 DOM 的多 Sheet 选择、分页、编辑和冲突计算，供页面与 Node 测试共用。
- `app/web/assets/app.js`：工作簿扫描、Sheet 配置卡、合并预览和最终提交的 DOM 编排。
- `app/web/pages/app.html`、`app/web/assets/styles.css`：多 Sheet 配置及分页界面。
- `tests/test_import_mapping.py`：解析器和异常 XLSX 回归测试。
- `tests/test_api.py`：扫描、独立映射、冲突及导入 API 测试。
- `tests/test_import_workbook.js`：前端纯状态逻辑测试。

---

### Task 1: 工作簿扫描与腾讯文档兼容

**Files:**
- Create: `tests/test_import_mapping.py`
- Modify: `app/services/import_mapping.py`

**Interfaces:**
- Produces: `inspect_excel_workbook(raw: bytes, filename: str) -> WorkbookInspection`
- Produces: `parse_excel_sheets(raw: bytes, filename: str, configs: list[SheetImportConfig]) -> list[SourcedRow]`
- Produces: dataclasses `WorkbookColumn`, `WorkbookSheet`, `WorkbookInspection`, `SheetImportConfig`, `SourcedRow`
- Preserves: `parse_table`, `infer_mapping`, `infer_defaults`, `normalize_rows` for the legacy single-source flow

- [ ] **Step 1: Add a malformed-style workbook fixture and failing scan test**

Create a test helper that builds a workbook with two sheets, makes `Sheet1` active, and injects an empty Fill without writing a fixture to the repository:

```python
def workbook_bytes_with_empty_fill() -> bytes:
    workbook = Workbook()
    sheet1 = workbook.active
    sheet1.title = "Sheet1"
    sheet1.append([None, None, None, None, None, None, None, None, None, None,
                   None, None, None, None, None, None, None, "成本"])
    sheet1.append([None, None, "001", None, "商品一", None, None, None, None,
                   None, None, None, None, "TRU", "1:35", "模型", None, 70])
    sheet2 = workbook.create_sheet("Sheet2")
    sheet2.append(["名称", "编号", "销售价"])
    sheet2.append(["参考商品", "REF-1", 100])
    source = BytesIO()
    workbook.save(source)

    incoming = ZipFile(BytesIO(source.getvalue()))
    output = BytesIO()
    outgoing = ZipFile(output, "w")
    for info in incoming.infolist():
        payload = incoming.read(info.filename)
        if info.filename == "xl/styles.xml":
            payload = payload.replace(
                b'<fills count="2">',
                b'<fills count="3">',
                1,
            )
            payload = payload.replace(b"</fills>", b"<fill/></fills>", 1)
        outgoing.writestr(info, payload)
    outgoing.close()
    incoming.close()
    return output.getvalue()
```

Add assertions:

```python
def test_inspect_excel_workbook_repairs_empty_fill_and_preserves_active_sheet():
    raw = workbook_bytes_with_empty_fill()
    original_hash = sha256(raw).hexdigest()

    inspection = inspect_excel_workbook(raw, "supplier.xlsx")

    assert sha256(raw).hexdigest() == original_hash
    assert inspection.active_sheet == "Sheet1"
    assert [sheet.name for sheet in inspection.sheets] == ["Sheet1", "Sheet2"]
    assert inspection.sheets[0].columns[2].key == "C"
    assert inspection.sheets[0].columns[2].label == "C列（无表头）"
    assert inspection.sheets[0].columns[17].label == "R列 · 成本"
```

- [ ] **Step 2: Run the scan test and verify RED**

Run:

```bash
./start.sh test
```

Expected: Python tests fail because `inspect_excel_workbook` and workbook dataclasses do not exist.

- [ ] **Step 3: Implement the workbook reader and scan dataclasses**

Add these public shapes to `app/services/import_mapping.py`:

```python
@dataclass(frozen=True)
class WorkbookColumn:
    key: str
    header: str
    label: str


@dataclass
class WorkbookSheet:
    name: str
    index: int
    estimated_rows: int
    column_count: int
    suggested_header_row: int
    columns: list[WorkbookColumn]
    sample_rows: list[dict[str, str]]
    suggested_mapping: dict[str, str]


@dataclass
class WorkbookInspection:
    file_name: str
    active_sheet: str
    sheets: list[WorkbookSheet]


@dataclass(frozen=True)
class SheetImportConfig:
    sheet_name: str
    header_row: int
    mapping: dict[str, str]
    defaults: dict[str, str]


@dataclass
class SourcedRow:
    values: dict[str, str]
    source_sheet: str
    source_row: int
```

Implement `_load_xlsx_workbook(raw, *, data_only)` with this behavior:

1. Call `load_workbook(BytesIO(raw), read_only=True, data_only=data_only)` normally.
2. Catch only the style `TypeError` whose text contains `Fill`.
3. Confirm `xl/styles.xml` contains a self-closing empty Fill matching `rb"<fill\s*/>"`.
4. Rebuild the ZIP in memory and replace every matching empty Fill with `<fill><patternFill patternType="none"/></fill>` while preserving archive entry order and Fill indices.
5. Retry `load_workbook`; propagate unrelated errors to `parse_table` so its existing user-facing error remains active.

For `.xls`, use `xlrd.open_workbook(file_contents=raw)` and `sheet_active` as the active index. For both formats, build column keys with `openpyxl.utils.get_column_letter(index + 1)` and labels with:

```python
label = f"{key}列 · {header}" if header else f"{key}列（无表头）"
```

Return at most five sample rows per Sheet. `estimated_rows` counts nonempty rows below the suggested header. Suggested mappings must only use nonempty header text and existing `_header_match_score`; do not guess empty-header fields by position.

- [ ] **Step 4: Add failing tests for independent selected-Sheet parsing**

Add:

```python
def test_parse_excel_sheets_uses_column_keys_and_preserves_source_coordinates():
    rows = parse_excel_sheets(
        workbook_bytes_with_empty_fill(),
        "supplier.xlsx",
        [
            SheetImportConfig(
                sheet_name="Sheet1",
                header_row=1,
                mapping={
                    "supplier_sku": "C",
                    "product_name": "E",
                    "brand": "N",
                    "model": "O",
                    "category": "P",
                    "price": "R",
                },
                defaults={"currency": "CNY"},
            )
        ],
    )

    assert len(rows) == 1
    assert rows[0].source_sheet == "Sheet1"
    assert rows[0].source_row == 2
    assert rows[0].values["supplier_sku"] == "001"
    assert rows[0].values["product_name"] == "商品一"
    assert rows[0].values["price"] == "70"
```

Also assert duplicate Sheet names, missing Sheet names, missing header rows, invalid column letters, and a total above `MAX_IMPORT_ROWS` raise a specific `ValueError`.

- [ ] **Step 5: Run the selected-Sheet test and verify RED**

Run:

```bash
./start.sh test
```

Expected: the new parsing test fails because `parse_excel_sheets` is missing.

- [ ] **Step 6: Implement selected-Sheet parsing and run GREEN**

Read only configured Sheets. Validate the complete config before returning rows. Map source column keys to `FIELD_ORDER`, merge `DEFAULT_VALUES` with per-Sheet defaults, skip wholly blank raw rows, attach the exact Sheet name and one-based Excel row number, and enforce the 10,000-row limit across all selected Sheets.

Run:

```bash
./start.sh test
```

Expected: all Python and Node tests pass.

- [ ] **Step 7: Commit Task 1**

```bash
git add app/services/import_mapping.py tests/test_import_mapping.py
git commit -m "feat: inspect and parse selected Excel sheets"
```

---

### Task 2: 扫描、合并预览与服务端冲突校验 API

**Files:**
- Modify: `tests/test_api.py`
- Modify: `app/api/routes/imports.py`

**Interfaces:**
- Consumes: `inspect_excel_workbook`, `parse_excel_sheets`, `SheetImportConfig`, `SourcedRow`
- Produces: `POST /api/imports/product-offers/workbook/inspect`
- Extends: `POST /api/imports/product-offers/preview` with `sheet_configs_json`
- Extends: `POST /api/imports/product-offers` rows with `source_sheet`, `source_row`, `included`

- [ ] **Step 1: Add failing workbook inspection API test**

Create an in-memory two-Sheet workbook in `tests/test_api.py` and assert:

```python
def test_excel_inspection_returns_all_sheets_and_active_sheet(authenticated_client):
    response = authenticated_client.post(
        "/api/imports/product-offers/workbook/inspect",
        files={"file": ("supplier.xlsx", workbook_content, XLSX_MIME)},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["active_sheet"] == "Sheet1"
    assert [sheet["name"] for sheet in data["sheets"]] == ["Sheet1", "Sheet2"]
    assert data["sheets"][0]["columns"][2]["key"] == "C"
```

Also assert CSV submitted to this endpoint returns HTTP 400 with `工作簿扫描仅支持 XLSX 和 XLS 格式`.

- [ ] **Step 2: Run the inspection API test and verify RED**

Run:

```bash
./start.sh test
```

Expected: HTTP 404 because the inspection route does not exist.

- [ ] **Step 3: Implement the inspection route**

Add an `excel_only=True` option to `_read_upload` or an equivalent explicit extension check without duplicating the 10 MiB limit. Serialize the Task 1 dataclasses into the response schema from the design. Convert workbook parsing `ValueError` to HTTP 400 without logging file contents.

- [ ] **Step 4: Add failing multi-Sheet preview and conflict tests**

Create two Sheets with different headers and the same SKU:

```python
workbook = Workbook()
sheet1 = workbook.active
sheet1.title = "Sheet1"
sheet1.append(["货号", "名称", "成本"])
sheet1.append(["DUP-001", "商品甲", 10])
sheet2 = workbook.create_sheet("Sheet2")
sheet2.append(["供应商成本表"])
sheet2.append(["产品编码", "产品名称", "出厂价"])
sheet2.append(["DUP-001", "商品乙", 12])
content = BytesIO()
workbook.save(content)
```

Send `Sheet1` with header row 1 and mapping A/B/C, and `Sheet2` with header row 2 and mapping A/B/C through `sheet_configs_json`. Assert:

```python
assert response.status_code == 200
assert response.json()["total_rows"] == 2
assert response.json()["conflict_count"] == 1
assert response.json()["can_import"] is False
assert {
    (row["source_sheet"], row["source_row"])
    for row in response.json()["preview_rows"]
} == {("Sheet1", 2), ("Sheet2", 3)}
assert {row["conflict_group"] for row in response.json()["preview_rows"]} == {"DUP-001"}
```

Add a second preview case with distinct SKUs and assert `can_import is True`. Add 400 cases for malformed JSON, empty configuration, duplicate Sheet configuration, unknown Sheet, invalid header row, and invalid column key.

- [ ] **Step 5: Run the preview tests and verify RED**

Run:

```bash
./start.sh test
```

Expected: the response ignores `sheet_configs_json` or lacks `conflict_count`, so the new assertions fail.

- [ ] **Step 6: Implement multi-Sheet preview**

Add `_sheet_configs(value: str) -> list[SheetImportConfig]` that rejects non-array JSON and constructs validated configs. Extend `preview_product_offers` with:

```python
sheet_configs_json: str = Form(default="")
```

When configurations exist, call `parse_excel_sheets`, validate each `SourcedRow.values` with `_validate_row`, and compute duplicate groups from nonempty normalized `supplier_sku` values. Return source fields, `included=True`, `conflict_group`, `conflict_count`, and `can_import`. Keep the current response path unchanged when configurations are absent.

- [ ] **Step 7: Add failing final-import duplicate validation tests**

Submit two included rows with the same SKU and assert HTTP 400 with `供应商 SKU 在本次导入中重复：DUP-001`. Assert no new offer with that SKU exists. Then submit the same rows with one row `included=false` and assert one successful import whose result and any row error retain the submitted Sheet and row coordinates.

- [ ] **Step 8: Run final-import tests and verify RED**

Run:

```bash
./start.sh test
```

Expected: the current endpoint strips source fields and silently Upserts the duplicate SKU, so assertions fail.

- [ ] **Step 9: Implement authoritative submitted-row validation**

Change `_submitted_rows` to return rows containing `values`, `source_sheet`, `source_row`, and `included`. Reject invalid source types, remove excluded rows, require at least one included row, enforce the 10,000-row limit after filtering, and reject duplicate nonempty SKU values before creating or updating products/offers. During row processing, use the preserved Sheet/row coordinates in errors:

```python
errors.append({
    "sheet": submitted.source_sheet,
    "row": submitted.source_row,
    "message": str(exc),
})
```

Legacy `rows_json` objects without source fields remain accepted with `sheet=None` and sequential row numbers.

- [ ] **Step 10: Run API and full backend tests**

Run:

```bash
./start.sh test
```

Expected: all Python and Node tests pass.

- [ ] **Step 11: Commit Task 2**

```bash
git add app/api/routes/imports.py tests/test_api.py
git commit -m "feat: preview and validate multi-sheet imports"
```

---

### Task 3: 多 Sheet 配置、分页预览和冲突处理页面

**Files:**
- Create: `app/web/assets/import-workbook.js`
- Create: `tests/test_import_workbook.js`
- Modify: `app/web/pages/app.html`
- Modify: `app/web/assets/app.js`
- Modify: `app/web/assets/styles.css`
- Modify: `docker-compose.test.yml`

**Interfaces:**
- Consumes: inspection and preview payloads from Task 2
- Produces: `window.MatrixImportWorkbook`
- Produces: pure functions `createWorkbookState`, `toggleSheet`, `updateRow`, `resolveRows`, `pageRows`, `canImport`
- Preserves: existing CSV/PDF single-source UI behavior

- [ ] **Step 1: Add failing frontend state tests**

Create `tests/test_import_workbook.js`, load `import-workbook.js` with `vm.runInNewContext`, and assert:

```javascript
test("active Excel sheet is selected after inspection", () => {
  const state = ImportWorkbook.createWorkbookState({
    active_sheet: "Sheet1",
    sheets: [{ name: "Sheet1" }, { name: "Sheet2" }],
  });
  assert.deepEqual(state.selectedSheets, ["Sheet1"]);
});

test("duplicate included SKUs block import until one record is excluded", () => {
  const rows = [
    { source_sheet: "Sheet1", source_row: 2, included: true, values: { supplier_sku: "A-1", product_name: "甲", category: "模型", price: "10" } },
    { source_sheet: "Sheet2", source_row: 3, included: true, values: { supplier_sku: "A-1", product_name: "乙", category: "模型", price: "12" } },
  ];
  assert.equal(ImportWorkbook.canImport(rows), false);
  rows[1].included = false;
  assert.equal(ImportWorkbook.canImport(rows), true);
});

test("pagination retains off-page edits", () => {
  const rows = Array.from({ length: 120 }, (_, index) => ({
    source_sheet: "Sheet1",
    source_row: index + 2,
    included: true,
    values: { supplier_sku: `SKU-${index}` },
  }));
  const state = { rows, page: 1, pageSize: 50 };
  ImportWorkbook.updateRow(state, 75, "price", "88");
  assert.equal(ImportWorkbook.pageRows(state, 2)[25].values.price, "88");
  assert.equal(state.rows.length, 120);
});
```

- [ ] **Step 2: Register the new Node test and verify RED**

Update `frontend-test` to syntax-check `app/web/assets/import-workbook.js` and run both Node suites:

```yaml
node --check app/web/assets/import-workbook.js &&
node --test tests/test_public_auth.js tests/test_import_workbook.js
```

Run:

```bash
./start.sh test
```

Expected: frontend test fails because `import-workbook.js` does not exist.

- [ ] **Step 3: Implement pure workbook state helpers**

Create `window.MatrixImportWorkbook` without reading the DOM. `createWorkbookState` selects only `active_sheet`, copies inspection data, and initializes each Sheet configuration. `resolveRows` recomputes conflict groups across all included rows. `pageRows` returns exactly the requested 50-row slice after current Sheet/conflict filters. `canImport` requires at least one included row, no duplicate included SKU, and required values on at least one included row.

- [ ] **Step 4: Run frontend state tests and verify GREEN**

Run:

```bash
./start.sh test
```

Expected: all Node tests pass; backend tests remain green.

- [ ] **Step 5: Add workbook configuration markup and styles**

Load `/assets/import-workbook.js` before `/assets/app.js`. Add hidden containers after the upload panel:

```html
<section id="import-workbook-config" class="panel import-workbook-config hidden">
  <header class="panel-head">
    <div><h2>选择并配置工作表</h2><p id="import-workbook-summary"></p></div>
    <button id="select-all-sheets" class="btn btn-secondary btn-sm" type="button">全选</button>
  </header>
  <div class="panel-body">
    <div id="import-sheet-list" class="import-sheet-list"></div>
    <div id="import-sheet-configs" class="import-sheet-configs"></div>
    <div class="import-actions">
      <span>每个工作表可以使用不同的表头和字段映射。</span>
      <button id="preview-selected-sheets" class="btn btn-primary" type="button" disabled>生成合并预览</button>
    </div>
  </div>
</section>
```

Add preview controls for Sheet filter, conflict-only filter, previous/next page, and page status. Style selected Sheet chips, configuration cards, conflict rows, excluded rows, and responsive two-column mappings without changing unrelated workspace styles.

- [ ] **Step 6: Wire Excel scanning and per-Sheet configuration**

In `selectImportFile`, clear all earlier workbook and preview state. For `.xlsx` and `.xls`, call `/api/imports/product-offers/workbook/inspect`, render every Sheet with a checkbox, default to the returned active Sheet, and hide the old direct analyze button. CSV/PDF retain the old analyze button.

Each selected Sheet card must render its own header-row input, column dropdowns keyed by column letter, and default inputs. Build `sheet_configs_json` from state rather than querying one shared mapping grid. Changing the file, Sheet selection, header row, mapping, or defaults invalidates the old merged preview.

- [ ] **Step 7: Wire paginated preview and conflict resolution**

Store every response row in `state.importWorkbook.rows`. Render only `pageRows(state, page)` and identify rows by their index in the full state. Row edits and include/exclude actions update the full state, call `resolveRows`, refresh conflict labels, and recompute the confirm-button state. `collectPreviewRows` must serialize all state rows, including off-page rows, rather than scrape `#import-preview-tbody`.

Source labels use `Sheet1 · 第2行`. Duplicate rows use `row-conflict`; excluded rows use `row-excluded`. The confirm button remains disabled until every included SKU is unique.

- [ ] **Step 8: Run syntax, frontend, and full tests**

Run:

```bash
./start.sh test
```

Expected: all Python tests and both Node test files pass.

- [ ] **Step 9: Commit Task 3**

```bash
git add app/web/assets/import-workbook.js app/web/assets/app.js app/web/assets/styles.css \
  app/web/pages/app.html tests/test_import_workbook.js docker-compose.test.yml
git commit -m "feat: add multi-sheet import workflow"
```

---

### Task 4: 文档、真实工作簿验收与服务验证

**Files:**
- Modify: `README.md`
- Modify: `docs/product/project-status.md`
- Modify: `docs/operations/validation.md`
- Modify: `docs/README.md`
- Modify: `docs/plans/2026-09-08-multi-sheet-excel-import.md`

**Interfaces:**
- Consumes: complete backend and frontend flow from Tasks 1–3
- Produces: operator instructions and dated validation evidence

- [ ] **Step 1: Document the multi-Sheet workflow**

Update README import instructions to say:

- Excel files are scanned before preview.
- The active Sheet is selected by default.
- Users can select one or multiple Sheets.
- Header row, mapping, and defaults are configured independently per Sheet.
- Duplicate SKU conflicts must be resolved before import.
- Preview renders 50 rows per page while submitting the complete edited list.

Add the current `Sheet1` example mapping C/E/N/O/P/R without committing or embedding source workbook data. Update project status from CSV-only wording to CSV/Excel/PDF and multi-Sheet preview.

- [ ] **Step 2: Run the actual Trumpeter workbook acceptance check**

Record the source hash without printing workbook contents:

```bash
shasum -a 256 Trumpeter.xlsx
```

Use the implemented service inside the application image to assert:

- filename is `Trumpeter.xlsx`;
- active Sheet is `Sheet1`;
- Sheet names are `Sheet1`, `Sheet2`, `618Trumpeter`;
- `Sheet1` is parsed with header row 1 and mapping C/E/N/O/P/R;
- normalized row count is 3,694;
- the first row has nonempty SKU, product name, category, and positive cost;
- source Sheet and source row are preserved.

Hash the source again and assert it is unchanged. Do not add `Trumpeter.xlsx` to Git.

- [ ] **Step 3: Run complete automated verification**

Run:

```bash
./start.sh test
./start.sh test
git diff --check
git status --short
```

Expected: both consecutive test runs pass against the same persistent test volume; the only permitted untracked business file is `Trumpeter.xlsx`; `.env` is not tracked.

- [ ] **Step 4: Restart and verify the local service**

Run:

```bash
./start.sh restart
curl --fail --silent http://127.0.0.1:6790/api/health
./start.sh status
```

Expected: health endpoint succeeds, application and PostgreSQL are healthy, and PostgreSQL continues to use internal port `6432`.

- [ ] **Step 5: Record validation evidence**

Update `docs/operations/validation.md` with the exact test totals, Node totals, workbook Sheet count, `Sheet1` normalized row count, source-hash preservation, service health, and PostgreSQL port result. Mark all completed checkboxes in this plan.

- [ ] **Step 6: Commit Task 4**

```bash
git add README.md docs/README.md docs/product/project-status.md \
  docs/operations/validation.md docs/plans/2026-09-08-multi-sheet-excel-import.md \
  docs/designs/2026-09-08-multi-sheet-excel-import-design.md
git commit -m "docs: document multi-sheet import validation"
```

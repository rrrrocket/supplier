# 导入安全边界补强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 关闭最终复审中剩余的损坏 OLE XLS、伪造 XLSX dimension 和真实 10,000 行请求传输三个阻断项。

**Architecture:** XLS 读取器只包装已知的 Compound Document 解析异常；XLSX read-only 工作表不再信任声明维度，而是重置维度并在实际行迭代时执行共享资源预算。最终导入端点自行以受控上限解析 multipart，允许完整预览状态通过，同时由应用和 Nginx 共同限制请求规模。

**Tech Stack:** Python 3.13、FastAPI 0.128、Starlette 0.52、openpyxl、xlrd、PostgreSQL 16、Nginx、pytest

**Spec:** `.superpowers/sdd/2026-09-08-multi-sheet-excel-import/final-re-review.md`

## Global Constraints

- PostgreSQL 是唯一数据库，内部端口保持 `6432`。
- 用户运行入口保持 `./start.sh`。
- 单次导入最多 10,000 个 included 行，前端最终请求提交完整编辑状态。
- `.env` 不读取、不输出、不提交；`Trumpeter.xlsx` 只读验收且不提交。
- 保留现有 migrations 和测试持久卷。

---

### Task 1: 损坏 OLE XLS 安全错误

**Files:**
- Modify: `app/services/import_mapping.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Preserves: `_load_xls_workbook(raw)` programming-error passthrough
- Produces: truncated OLE compound documents return `WorkbookFileError` and API HTTP 400

- [x] **Step 1: Add failing inspect and configured-preview tests**

Use a literal OLE header plus truncated compound data and assert both endpoints return status 400 with the existing `WORKBOOK_PARSE_ERROR`, without `CompDocError` in the response.

- [x] **Step 2: Run the two tests and verify RED**

Run the targeted tests in the existing test runner. Expected: both requests surface 500 because `xlrd.compdoc.CompDocError` is not wrapped.

- [x] **Step 3: Add the narrow exception mapping**

Import/catch `xlrd.compdoc.CompDocError` only alongside the existing xlrd parse exceptions. Do not catch `Exception` or `RuntimeError`.

- [x] **Step 4: Run targeted tests and verify GREEN**

Expected: inspect and configured preview both return the stable safe 400, while the programming-error passthrough test remains green.

---

### Task 2: XLSX actual-dimension streaming budget

**Files:**
- Modify: `app/services/import_mapping.py`
- Modify: `tests/test_import_mapping.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `WorkbookBudget` shared across worksheet iterators
- Produces: `_bounded_workbook_rows(rows, *, name, budget)` enforcing actual row, column, and cumulative dimension-cell limits
- Preserves: inspection retains 20 header candidates and at most 5 samples

- [x] **Step 1: Add failing forged/missing dimension tests**

Build XLSX bytes in memory, replace `xl/worksheets/sheet1.xml` dimension `A1:R11` with `A1`, and separately remove the dimension element. Assert inspection still sees all 10 data rows and configured parsing preserves the final source row instead of truncating or raising `TypeError`.

- [x] **Step 2: Add failing runtime budget tests**

Monkeypatch row/column/cell ceilings below a small workbook's actual XML content. Assert actual streaming rejects over-row, over-column, and accumulated dimension-cell cases even when the declared dimension is understated.

- [x] **Step 3: Run targeted tests and verify RED**

Expected: understated dimension reports zero/partial data, missing dimension errors, and runtime ceilings can be bypassed.

- [x] **Step 4: Reset XLSX read-only dimensions and enforce actual budgets**

After load, call `reset_dimensions()` for every read-only XLSX worksheet. Wrap all inspection, configured parsing, and legacy XLSX row iterators in one-pass budget enforcement. Validate header existence and mapped-column reachability using observed rows instead of `max_row/max_column`. Keep XLS dimension validation using trusted xlrd sheet dimensions.

- [x] **Step 5: Run targeted and existing parser tests GREEN**

Expected: forged/missing dimension workbooks are fully scanned or safely rejected by actual budgets, `Trumpeter.xlsx` remains under limits, and the single-pass inspection test still iterates each row once.

---

### Task 3: Real 10,000-row multipart transport

**Files:**
- Modify: `app/api/routes/imports.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_database_backend.py`
- Modify: `deploy/nginx-supplier.conf`

**Interfaces:**
- Produces: `MAX_IMPORT_FORM_PART_SIZE = 8 * 1024 * 1024`
- Produces: `MAX_FINAL_IMPORT_REQUEST_SIZE = 20 * 1024 * 1024`
- Produces: final import route uses `MultiPartParser` with a bounded request stream, one file, five text fields and an 8 MiB per-field limit
- Produces: uploaded files are read in chunks no larger than 1 MiB and rejected above 10 MiB
- Produces: Nginx request limit exceeds the application's complete multipart request limit

- [x] **Step 1: Replace compact boundary fixtures with real nested payload tests**

Create 10,000 included nested rows with the same 12-field shape emitted by `collectPreviewRows`, unique SKU values, one valid row and remaining deliberately invalid rows. Submit with a valid one-Sheet workbook plus `sheet_configs_json`; assert 10,000 reaches the business layer and at least one row imports. Assert 10,001 rejects and excluding one returns the included count to 10,000.

- [x] **Step 2: Run the boundary tests and verify RED**

Expected: Starlette rejects the `rows_json` part at its default 1 MiB limit before `_submitted_rows` runs.

- [x] **Step 3: Implement bounded manual multipart parsing**

Change only the final import endpoint from `File`/`Form` parameters to `Request`; use Starlette's `MultiPartParser` with an 8 MiB field limit and a bounded request stream capped at 20 MiB. Validate the single upload and five string fields, enforce the existing 2,000-character description limit, read the upload in bounded chunks capped at 10 MiB, then reuse all current business validation.

- [x] **Step 4: Align Nginx and application limits**

Set `client_max_body_size` to `24m`. Update the contract test to require the Nginx limit to exceed `MAX_FINAL_IMPORT_REQUEST_SIZE`.

- [x] **Step 5: Run boundary and full API tests GREEN**

Expected: actual nested 10,000 requests reach/import, 10,001 rejects at the business rule, and oversized form parts remain bounded.

---

### Task 4: Verification, documentation, and commit

**Files:**
- Modify: `docs/operations/validation.md`
- Modify: `docs/plans/2026-09-08-import-hardening-follow-up.md`

- [x] **Step 1: Run all targeted tests and static checks**

Run Python parser/API/config tests, Node tests, `bash -n start.sh`, Python compile checks, and `git diff --check`.

- [x] **Step 2: Run `./start.sh test` twice**

Record exact Python and Node totals from both runs against the persistent test database.

- [x] **Step 3: Re-run real workbook and service acceptance**

Verify `Trumpeter.xlsx` before/after SHA-256, active `Sheet1`, three Sheets, C/E/N/O/P/R, 3,694 rows and `Sheet1:2`; then run `./start.sh restart`, health and status checks and confirm PostgreSQL 6432.

- [x] **Step 4: Update validation evidence and checkboxes**

Replace overstatements with actual passing evidence and preserve the AnyIO warning as a non-blocking deferred item.

- [x] **Step 5: Commit**

Stage only implementation, tests, Nginx, validation and this plan. Keep `.env` and `Trumpeter.xlsx` untracked. Commit as `rrrrocket <standxh@163.com>` with message `fix: close workbook import safety gaps`.

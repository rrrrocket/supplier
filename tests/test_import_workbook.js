const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


function loadImportWorkbook() {
  const window = {};
  const context = { window };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "app", "web", "assets", "import-workbook.js"),
    "utf8",
  );
  vm.runInNewContext(source, context);
  return window.MatrixImportWorkbook;
}


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}


function loadImportApp(api) {
  class FakeClassList {
    constructor() {
      this.values = new Set();
    }

    add(...names) {
      names.forEach((name) => this.values.add(name));
    }

    remove(...names) {
      names.forEach((name) => this.values.delete(name));
    }

    toggle(name, force) {
      const enabled = force === undefined ? !this.values.has(name) : force;
      if (enabled) this.values.add(name);
      else this.values.delete(name);
      return enabled;
    }

    contains(name) {
      return this.values.has(name);
    }
  }

  class FakeElement {
    constructor() {
      this.classList = new FakeClassList();
      this.dataset = {};
      this.disabled = false;
      this.checked = false;
      this.innerHTML = "";
      this.textContent = "";
      this.value = "";
      this.listeners = new Map();
    }

    addEventListener(type, listener) {
      if (!this.listeners.has(type)) this.listeners.set(type, []);
      this.listeners.get(type).push(listener);
    }

    closest() {
      return null;
    }

    matches() {
      return false;
    }

    querySelector() {
      return new FakeElement();
    }

    querySelectorAll() {
      return [];
    }

    scrollIntoView() {}
  }

  class FakeFormData {
    constructor() {
      this.entries = [];
    }

    append(key, value) {
      this.entries.push([key, value]);
    }
  }

  const elements = new Map();
  const element = (selector) => {
    if (!elements.has(selector)) elements.set(selector, new FakeElement());
    return elements.get(selector);
  };
  const toasts = [];
  const document = {
    addEventListener() {},
    querySelector: element,
    querySelectorAll() {
      return [];
    },
  };
  const window = {
    MatrixImportWorkbook: loadImportWorkbook(),
    addEventListener() {},
    location: { hash: "", href: "" },
  };
  const Matrix = {
    api,
    escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll('"', "&quot;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
    },
    formatDate: String,
    formatMoney: String,
    statusBadge: String,
    toast(...args) {
      toasts.push(args);
    },
  };
  const context = vm.createContext({
    clearTimeout,
    console,
    document,
    FormData: FakeFormData,
    Matrix,
    setTimeout,
    URLSearchParams,
    window,
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, "..", "app", "web", "assets", "app.js"), "utf8"),
    context,
  );
  return {
    context,
    element,
    evaluate(source) {
      return vm.runInContext(source, context);
    },
    toasts,
  };
}


function inspection(fileName, sheetName = "Sheet1") {
  return {
    file_name: fileName,
    active_sheet: sheetName,
    sheets: [{
      name: sheetName,
      estimated_rows: 1,
      column_count: 4,
      suggested_header_row: 1,
      suggested_mapping: {},
      columns: [],
      sample_rows: [],
    }],
  };
}


function previewResult(fileName, sku = "SKU-1") {
  return {
    file_name: fileName,
    sheet_name: "Sheet1",
    header_row: 1,
    total_rows: 1,
    headers: [],
    mapping: [],
    defaults: {},
    warnings: [],
    preview_rows: [{
      source_sheet: "Sheet1",
      source_row: 2,
      included: true,
      conflict_group: null,
      values: { product_name: "商品", category: "模型", supplier_sku: sku, price: "10" },
      errors: [],
    }],
  };
}


test("active Excel sheet is selected after inspection", () => {
  const ImportWorkbook = loadImportWorkbook();
  const state = ImportWorkbook.createWorkbookState({
    active_sheet: "Sheet1",
    sheets: [
      {
        name: "Sheet1",
        suggested_header_row: 2,
        suggested_mapping: { supplier_sku: "C" },
      },
      {
        name: "Sheet2",
        suggested_header_row: 1,
        suggested_mapping: { product_name: "A" },
      },
    ],
  });

  assert.deepEqual(state.selectedSheets, ["Sheet1"]);
  assert.deepEqual(JSON.parse(JSON.stringify(state.configs.Sheet1)), {
    sheet_name: "Sheet1",
    header_row: 2,
    mapping: { supplier_sku: "C" },
    defaults: {},
  });
  assert.deepEqual(JSON.parse(JSON.stringify(state.configs.Sheet2)), {
    sheet_name: "Sheet2",
    header_row: 1,
    mapping: { product_name: "A" },
    defaults: {},
  });
});


test("sheet selection changes independently and invalidates merged rows", () => {
  const ImportWorkbook = loadImportWorkbook();
  const state = ImportWorkbook.createWorkbookState({
    active_sheet: "Sheet1",
    sheets: [{ name: "Sheet1" }, { name: "Sheet2" }],
  });
  state.rows = [{ source_sheet: "Sheet1", included: true, values: {} }];

  ImportWorkbook.toggleSheet(state, "Sheet2", true);

  assert.deepEqual(JSON.parse(JSON.stringify(state.selectedSheets)), ["Sheet1", "Sheet2"]);
  assert.equal(state.rows.length, 0);
  ImportWorkbook.toggleSheet(state, "Sheet1", false);
  assert.deepEqual(JSON.parse(JSON.stringify(state.selectedSheets)), ["Sheet2"]);
});


test("duplicate included SKUs block import until one record is excluded", () => {
  const ImportWorkbook = loadImportWorkbook();
  const rows = [
    { source_sheet: "Sheet1", source_row: 2, included: true, values: { supplier_sku: "A-1", product_name: "甲", category: "模型", price: "10" } },
    { source_sheet: "Sheet2", source_row: 3, included: true, values: { supplier_sku: "A-1", product_name: "乙", category: "模型", price: "12" } },
  ];

  ImportWorkbook.resolveRows(rows);
  assert.equal(ImportWorkbook.canImport(rows), false);
  assert.equal(rows[0].conflict_group, "A-1");
  assert.equal(rows[1].conflict_group, "A-1");

  rows[1].included = false;
  ImportWorkbook.resolveRows(rows);
  assert.equal(ImportWorkbook.canImport(rows), true);
  assert.equal(rows[0].conflict_group, null);
  assert.equal(rows[1].conflict_group, null);
});


test("canImport requires an included row with all required values", () => {
  const ImportWorkbook = loadImportWorkbook();
  const blank = { included: true, values: { supplier_sku: "", product_name: "", category: "", price: "" } };
  const valid = { included: true, values: { supplier_sku: "SKU-1", product_name: "商品", category: "模型", price: "10" } };

  assert.equal(ImportWorkbook.canImport([]), false);
  assert.equal(ImportWorkbook.canImport([blank]), false);
  assert.equal(ImportWorkbook.canImport([blank, valid]), true);
});


test("pagination retains off-page edits", () => {
  const ImportWorkbook = loadImportWorkbook();
  const rows = Array.from({ length: 120 }, (_, index) => ({
    source_sheet: "Sheet1",
    source_row: index + 2,
    included: true,
    values: { supplier_sku: `SKU-${index}` },
  }));
  const state = { rows, page: 1, pageSize: 50, sheetFilter: "", conflictOnly: false };

  ImportWorkbook.updateRow(state, 75, "price", "88");

  assert.equal(ImportWorkbook.pageRows(state, 2)[25].values.price, "88");
  assert.equal(state.rows.length, 120);
});


test("correctionCount ignores excluded rows and changes when they are restored", () => {
  const ImportWorkbook = loadImportWorkbook();
  const rows = [
    { included: true, errors: ["商品名称不能为空"], conflict_group: null },
    { included: false, errors: ["价格不能为空"], conflict_group: null },
    { included: true, errors: [], conflict_group: "DUP" },
  ];

  assert.equal(ImportWorkbook.correctionCount(rows), 1);
  rows[0].included = false;
  assert.equal(ImportWorkbook.correctionCount(rows), 0);
  rows[0].included = true;
  assert.equal(ImportWorkbook.correctionCount(rows), 1);
});


test("pageRows applies sheet and conflict filters before slicing fifty rows", () => {
  const ImportWorkbook = loadImportWorkbook();
  const rows = Array.from({ length: 75 }, (_, index) => ({
    source_sheet: index < 60 ? "Sheet1" : "Sheet2",
    source_row: index + 2,
    included: true,
    conflict_group: index % 2 === 0 ? "DUP" : null,
    values: { supplier_sku: `SKU-${index}` },
  }));
  const state = {
    rows,
    page: 1,
    pageSize: 50,
    sheetFilter: "Sheet1",
    conflictOnly: true,
  };

  const firstPage = ImportWorkbook.pageRows(state, 1);
  const secondPage = ImportWorkbook.pageRows(state, 2);

  assert.equal(firstPage.length, 30);
  assert.equal(firstPage.every((row) => row.source_sheet === "Sheet1"), true);
  assert.equal(firstPage.every((row) => row.conflict_group === "DUP"), true);
  assert.deepEqual(firstPage.map((row) => state.rows.indexOf(row)).slice(0, 3), [0, 2, 4]);
  assert.deepEqual(secondPage, []);
});


test("pageRows combines correction, sheet, and conflict filters", () => {
  const ImportWorkbook = loadImportWorkbook();
  const rows = [
    { source_sheet: "Sheet1", included: true, conflict_group: "DUP", errors: ["价格不能为空"] },
    { source_sheet: "Sheet1", included: true, conflict_group: null, errors: ["类目不能为空"] },
    { source_sheet: "Sheet1", included: false, conflict_group: null, errors: ["商品名称不能为空"] },
    { source_sheet: "Sheet2", included: true, conflict_group: "DUP", errors: ["价格不能为空"] },
    { source_sheet: "Sheet1", included: true, conflict_group: "DUP", errors: [] },
  ];
  const state = {
    rows,
    page: 1,
    pageSize: 50,
    sheetFilter: "Sheet1",
    conflictOnly: true,
    correctionOnly: true,
  };

  assert.deepEqual(ImportWorkbook.pageRows(state), [rows[0]]);
});


test("preview response for file A cannot overwrite file B after a switch", async () => {
  const previewA = deferred();
  const inspectB = deferred();
  const requests = [];
  const app = loadImportApp((url) => {
    requests.push(url);
    if (url.endsWith("/preview")) return previewA.promise;
    if (url.endsWith("/inspect")) return inspectB.promise;
    throw new Error(`Unexpected API request: ${url}`);
  });
  app.context.fileA = { name: "A.xlsx", size: 100 };
  app.context.fileB = { name: "B.xlsx", size: 100 };
  app.context.inspectionA = inspection("A.xlsx");
  app.context.inspectionB = inspection("B.xlsx", "B-Sheet");
  app.context.previewAResult = previewResult("A.xlsx", "A-SKU");
  app.evaluate("state.importFile = fileA; state.importWorkbook = ImportWorkbook.createWorkbookState(inspectionA)");

  const pendingPreview = app.evaluate("previewSelectedSheets()");
  const pendingSelection = app.evaluate("selectImportFile(fileB)");
  inspectB.resolve(app.context.inspectionB);
  await pendingSelection;
  previewA.resolve(app.context.previewAResult);
  await pendingPreview;

  assert.deepEqual(requests, [
    "/api/imports/product-offers/preview",
    "/api/imports/product-offers/workbook/inspect",
  ]);
  assert.equal(app.evaluate("state.importFile.name"), "B.xlsx");
  assert.equal(app.evaluate("state.importWorkbook.inspection.file_name"), "B.xlsx");
  assert.equal(app.evaluate("state.importWorkbook.rows.length"), 0);
  assert.equal(app.element("#import-preview").classList.contains("hidden"), true);
  assert.deepEqual(app.toasts, []);
});


test("changing a sheet config invalidates an in-flight preview", async () => {
  const preview = deferred();
  const app = loadImportApp((url) => {
    if (url.endsWith("/preview")) return preview.promise;
    throw new Error(`Unexpected API request: ${url}`);
  });
  app.context.file = { name: "config.xlsx", size: 100 };
  app.context.inspection = inspection("config.xlsx");
  app.context.result = previewResult("config.xlsx");
  app.evaluate(`
    state.importFile = file;
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspection);
    state.importWorkbook.lastExcludedCorrections = [{ source_row: 2 }];
    bindEvents();
  `);

  const pendingPreview = app.evaluate("previewSelectedSheets()");
  const configListener = app.element("#import-sheet-configs").listeners.get("input")[0];
  configListener({
    target: {
      closest: () => ({ dataset: { sheetConfig: "Sheet1" } }),
      dataset: {},
      matches: (selector) => selector === "[data-sheet-header-row]",
      value: "2",
    },
  });
  preview.resolve(app.context.result);
  await pendingPreview;

  assert.equal(app.evaluate("state.importWorkbook.configs.Sheet1.header_row"), 2);
  assert.equal(app.evaluate("state.importWorkbook.rows.length"), 0);
  assert.equal(app.evaluate("state.importWorkbook.lastExcludedCorrections.length"), 0);
  assert.equal(app.element("#import-preview").classList.contains("hidden"), true);
  assert.deepEqual(app.toasts, []);
});


test("completion of an old import cannot reset a newly selected file", async () => {
  const oldImport = deferred();
  const inspectB = deferred();
  const app = loadImportApp((url) => {
    if (url === "/api/imports/product-offers") return oldImport.promise;
    if (url.endsWith("/inspect")) return inspectB.promise;
    if (["/api/imports", "/api/products", "/api/offers/brands", "/api/offers"].includes(url)) return Promise.resolve([]);
    throw new Error(`Unexpected API request: ${url}`);
  });
  app.context.fileA = { name: "A.xlsx", size: 100 };
  app.context.fileB = { name: "B.xlsx", size: 100 };
  app.context.inspectionA = inspection("A.xlsx");
  app.context.inspectionB = inspection("B.xlsx", "B-Sheet");
  app.context.previewAResult = previewResult("A.xlsx", "A-SKU");
  app.evaluate(`
    state.importFile = fileA;
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspectionA);
    renderImportPreview(previewAResult, true);
  `);

  const pendingImport = app.evaluate("confirmSmartImport()");
  const pendingSelection = app.evaluate("selectImportFile(fileB)");
  inspectB.resolve(app.context.inspectionB);
  await pendingSelection;
  oldImport.resolve({ success_rows: 1, error_rows: 0 });
  await pendingImport;

  assert.equal(app.evaluate("state.importFile.name"), "B.xlsx");
  assert.equal(app.evaluate("state.importWorkbook.inspection.file_name"), "B.xlsx");
  assert.equal(app.element("#import-workbook-config").classList.contains("hidden"), false);
  assert.deepEqual(app.toasts, []);
});


test("editing the last duplicate removes rows from conflict-only view immediately", () => {
  const app = loadImportApp(() => Promise.reject(new Error("API should not be called")));
  app.context.inspection = inspection("conflicts.xlsx");
  app.context.rows = [
    { source_sheet: "Sheet1", source_row: 2, included: true, conflict_group: "DUP", values: { supplier_sku: "DUP" }, errors: [] },
    { source_sheet: "Sheet1", source_row: 3, included: true, conflict_group: "DUP", values: { supplier_sku: "DUP" }, errors: [] },
  ];
  app.evaluate(`
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspection);
    state.importWorkbook.rows = rows;
    state.importWorkbook.conflictOnly = true;
    renderImportRows();
    bindEvents();
  `);
  const inputListener = app.element("#import-preview-tbody").listeners.get("input")[0];
  inputListener({
    target: {
      dataset: { rowIndex: "0", rowField: "supplier_sku" },
      matches: (selector) => selector === "[data-row-field]",
      value: "UNIQUE",
    },
  });

  assert.equal(app.evaluate("state.importWorkbook.rows.every((row) => !row.conflict_group)"), true);
  assert.equal(app.element("#import-preview-tbody").innerHTML, "");
});


test("excluding a correction row updates its count and correction-only results", () => {
  const app = loadImportApp(() => Promise.reject(new Error("API should not be called")));
  app.context.inspection = inspection("corrections.xlsx");
  app.context.rows = [
    {
      source_sheet: "Sheet1",
      source_row: 2,
      included: true,
      conflict_group: null,
      values: { supplier_sku: "FIX-1" },
      errors: ["价格不能为空"],
    },
    {
      source_sheet: "Sheet1",
      source_row: 3,
      included: false,
      conflict_group: null,
      values: { supplier_sku: "FIX-2" },
      errors: ["类目不能为空"],
    },
    {
      source_sheet: "Sheet1",
      source_row: 4,
      included: true,
      conflict_group: null,
      values: {
        product_name: "可导入商品",
        category: "模型",
        supplier_sku: "OK-1",
        price: "10",
      },
      errors: [],
    },
  ];
  app.context.result = {
    file_name: "corrections.xlsx",
    sheet_name: null,
    header_row: null,
    total_rows: 3,
    headers: [],
    mapping: [],
    defaults: {},
    warnings: ["检测到 2 行数据需要修正", "保留此提示"],
    preview_rows: app.context.rows,
  };
  app.evaluate(`
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspection);
    renderImportPreview(result, true);
    state.importWorkbook.page = 2;
    bindEvents();
  `);

  const correctionListener = app.element("#import-correction-only").listeners.get("change")[0];
  correctionListener({ target: { checked: true } });

  assert.equal(app.evaluate("state.importWorkbook.correctionOnly"), true);
  assert.equal(app.evaluate("state.importWorkbook.page"), 1);
  assert.match(app.element("#import-preview-count").textContent, /需修正 1 行/);
  assert.match(app.element("#import-preview-warnings").innerHTML, /检测到 1 行数据需要修正/);
  assert.match(app.element("#import-preview-warnings").innerHTML, /保留此提示/);
  assert.match(app.element("#import-preview-tbody").innerHTML, /data-import-row="0"/);
  assert.doesNotMatch(app.element("#import-preview-tbody").innerHTML, /data-import-row="1"/);
  assert.doesNotMatch(app.element("#import-preview-tbody").innerHTML, /data-import-row="2"/);

  const rowClickListener = app.element("#import-preview-tbody").listeners.get("click")[0];
  rowClickListener({
    target: {
      closest: (selector) => selector === "[data-toggle-import-row]"
        ? { dataset: { toggleImportRow: "0" } }
        : null,
    },
  });

  assert.equal(app.evaluate("state.importWorkbook.rows[0].included"), false);
  assert.match(app.element("#import-preview-count").textContent, /需修正 0 行/);
  assert.doesNotMatch(app.element("#import-preview-warnings").innerHTML, /行数据需要修正/);
  assert.match(app.element("#import-preview-warnings").innerHTML, /保留此提示/);
  assert.equal(app.element("#import-preview-tbody").innerHTML, "");
});


test("bulk correction exclusion can be restored without deleting rows", () => {
  const app = loadImportApp(() => Promise.reject(new Error("API should not be called")));
  app.context.inspection = inspection("bulk-corrections.xlsx");
  app.context.result = {
    file_name: "bulk-corrections.xlsx",
    sheet_name: null,
    header_row: null,
    total_rows: 3,
    headers: [],
    mapping: [],
    defaults: {},
    warnings: ["检测到 2 行数据需要修正"],
    preview_rows: [
      { source_sheet: "Sheet1", source_row: 2, included: true, conflict_group: null, values: { supplier_sku: "FIX-1" }, errors: ["价格不能为空"] },
      { source_sheet: "Sheet1", source_row: 3, included: true, conflict_group: null, values: { supplier_sku: "FIX-2" }, errors: ["类目不能为空"] },
      { source_sheet: "Sheet1", source_row: 4, included: true, conflict_group: null, values: { product_name: "商品", category: "模型", supplier_sku: "OK-1", price: "10" }, errors: [] },
    ],
  };
  app.evaluate(`
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspection);
    renderImportPreview(result, true);
    bindEvents();
  `);

  const excludeListener = app.element("#exclude-correction-rows").listeners.get("click")[0];
  excludeListener();

  assert.equal(app.evaluate("state.importWorkbook.rows.length"), 3);
  assert.deepEqual(
    app.evaluate("state.importWorkbook.rows.map((row) => row.included)"),
    [false, false, true],
  );
  assert.match(app.element("#import-preview-count").textContent, /需修正 0 行/);
  assert.doesNotMatch(app.element("#import-preview-warnings").innerHTML, /行数据需要修正/);
  assert.equal(app.element("#exclude-correction-rows").disabled, true);
  assert.equal(app.element("#restore-correction-rows").classList.contains("hidden"), false);

  const restoreListener = app.element("#restore-correction-rows").listeners.get("click")[0];
  restoreListener();

  assert.deepEqual(
    app.evaluate("state.importWorkbook.rows.map((row) => row.included)"),
    [true, true, true],
  );
  assert.match(app.element("#import-preview-count").textContent, /需修正 2 行/);
  assert.match(app.element("#import-preview-warnings").innerHTML, /检测到 2 行数据需要修正/);
  assert.equal(app.element("#restore-correction-rows").classList.contains("hidden"), true);
});


test("final import posts all 120 state rows including an off-page edit and sheet configs", async () => {
  let submittedBody;
  const app = loadImportApp((url, options = {}) => {
    if (url === "/api/imports/product-offers") {
      submittedBody = options.body;
      return Promise.resolve({ success_rows: 120, error_rows: 0 });
    }
    if (["/api/imports", "/api/products", "/api/offers/brands", "/api/offers"].includes(url)) {
      return Promise.resolve([]);
    }
    throw new Error(`Unexpected API request: ${url}`);
  });
  app.context.file = { name: "all-rows.xlsx", size: 100 };
  app.context.inspection = inspection("all-rows.xlsx");
  app.context.rows = Array.from({ length: 120 }, (_, index) => ({
    source_sheet: "Sheet1",
    source_row: index + 2,
    included: true,
    conflict_group: null,
    values: {
      product_name: `商品-${index}`,
      category: "模型",
      supplier_sku: `SKU-${index}`,
      price: "10",
    },
    errors: [],
  }));
  app.evaluate(`
    state.importFile = file;
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspection);
    state.importWorkbook.rows = rows;
    state.importPreview = { defaults: {} };
    ImportWorkbook.updateRow(state.importWorkbook, 75, "price", "88");
  `);

  await app.evaluate("confirmSmartImport()");

  const entries = new Map(submittedBody.entries);
  const submittedRows = JSON.parse(entries.get("rows_json"));
  const configs = JSON.parse(entries.get("sheet_configs_json"));
  assert.equal(submittedRows.length, 120);
  assert.equal(submittedRows[75].price, undefined);
  assert.equal(submittedRows[75].values.price, "88");
  assert.equal(configs.length, 1);
  assert.equal(configs[0].sheet_name, "Sheet1");
});


test("an invalid file B immediately invalidates a pending scan for file A", async () => {
  const inspectA = deferred();
  const app = loadImportApp((url) => {
    if (url.endsWith("/inspect")) return inspectA.promise;
    throw new Error(`Unexpected API request: ${url}`);
  });
  app.context.fileA = { name: "A.xlsx", size: 100 };
  app.context.invalidB = { name: "B.exe", size: 100 };
  app.context.inspectionA = inspection("A.xlsx");

  const pendingScan = app.evaluate("selectImportFile(fileA)");
  await app.evaluate("selectImportFile(invalidB)");
  inspectA.resolve(app.context.inspectionA);
  await pendingScan;

  assert.equal(app.evaluate("state.importFile"), null);
  assert.equal(app.evaluate("state.importWorkbook"), null);
  assert.equal(app.element("#import-workbook-config").classList.contains("hidden"), true);
  assert.equal(app.toasts.length, 1);
  assert.equal(app.toasts[0][0], "文件格式错误");
});

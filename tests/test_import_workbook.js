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

(function initMatrixImportWorkbook(global) {
  "use strict";

  const REQUIRED_FIELDS = ["product_name", "category", "supplier_sku", "price"];

  function normalizedSku(row) {
    return String(row?.values?.supplier_sku || "").trim();
  }

  function createWorkbookState(inspection) {
    const sheets = Array.isArray(inspection?.sheets)
      ? inspection.sheets.map((sheet) => ({ ...sheet }))
      : [];
    const activeSheet = sheets.some((sheet) => sheet.name === inspection?.active_sheet)
      ? inspection.active_sheet
      : "";
    const configs = {};
    sheets.forEach((sheet) => {
      configs[sheet.name] = {
        sheet_name: sheet.name,
        header_row: Number(sheet.suggested_header_row) || 1,
        mapping: { ...(sheet.suggested_mapping || {}) },
        defaults: {},
      };
    });
    return {
      inspection: { ...inspection, sheets },
      selectedSheets: sheets
        .filter((sheet) => sheet.name === activeSheet)
        .map((sheet) => sheet.name),
      configs,
      rows: [],
      page: 1,
      pageSize: 50,
      sheetFilter: "",
      conflictOnly: false,
    };
  }

  function toggleSheet(state, sheetName, selected) {
    const exists = state.inspection?.sheets?.some((sheet) => sheet.name === sheetName);
    if (!exists) return state;
    const selectedSheets = state.selectedSheets || [];
    if (selected && !selectedSheets.includes(sheetName)) {
      state.selectedSheets = [...selectedSheets, sheetName];
    } else if (!selected) {
      state.selectedSheets = selectedSheets.filter((name) => name !== sheetName);
    }
    state.rows = [];
    state.page = 1;
    return state;
  }

  function resolveRows(rows) {
    const counts = new Map();
    rows.forEach((row) => {
      if (!row.included) return;
      const sku = normalizedSku(row);
      if (sku) counts.set(sku, (counts.get(sku) || 0) + 1);
    });
    rows.forEach((row) => {
      const sku = normalizedSku(row);
      row.conflict_group = row.included && sku && counts.get(sku) > 1 ? sku : null;
    });
    return rows;
  }

  function updateRow(state, rowIndex, field, value) {
    const row = state.rows?.[rowIndex];
    if (!row || !row.values) return state;
    row.values[field] = value;
    resolveRows(state.rows);
    return state;
  }

  function filteredRows(state) {
    return (state.rows || []).filter((row) => {
      if (state.sheetFilter && row.source_sheet !== state.sheetFilter) return false;
      if (state.conflictOnly && !row.conflict_group) return false;
      return true;
    });
  }

  function pageRows(state, requestedPage = state.page || 1) {
    const pageSize = Number(state.pageSize) || 50;
    const page = Math.max(1, Number(requestedPage) || 1);
    const start = (page - 1) * pageSize;
    return filteredRows(state).slice(start, start + pageSize);
  }

  function canImport(rows) {
    const includedRows = (rows || []).filter((row) => row.included);
    if (!includedRows.length) return false;
    const skus = new Set();
    for (const row of includedRows) {
      const sku = normalizedSku(row);
      if (sku && skus.has(sku)) return false;
      if (sku) skus.add(sku);
    }
    return includedRows.some((row) => REQUIRED_FIELDS.every(
      (field) => String(row.values?.[field] || "").trim(),
    ));
  }

  global.MatrixImportWorkbook = {
    createWorkbookState,
    toggleSheet,
    updateRow,
    resolveRows,
    pageRows,
    canImport,
  };
})(window);

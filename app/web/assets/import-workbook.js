(function initMatrixImportWorkbook(global) {
  "use strict";

  const REQUIRED_FIELDS = ["product_name", "brand", "category", "supplier_sku", "price"];
  const REQUIRED_MESSAGES = {
    product_name: "商品名称不能为空",
    brand: "品牌不能为空",
    category: "类目不能为空",
    supplier_sku: "供应商SKU不能为空",
    price: "价格不能为空",
  };
  const MAX_IMPORT_INTEGER = 2147483647;
  const INTEGER_WITH_OPTIONAL_UNIT = /^([+-]?\d+)(?:\.0+)?(?:\s*[\p{L}]+)?$/u;

  function parseInteger(value) {
    const normalized = String(value || "").replaceAll(",", "").trim();
    if (!normalized) return null;
    const match = normalized.match(INTEGER_WITH_OPTIONAL_UNIT);
    if (!match) return undefined;
    return Number(match[1]);
  }

  function validateRow(values) {
    const errors = [];
    REQUIRED_FIELDS.forEach((field) => {
      if (!String(values?.[field] || "").trim()) errors.push(REQUIRED_MESSAGES[field]);
    });
    const rawPrice = String(values?.price || "").trim();
    if (rawPrice) {
      const cleaned = rawPrice.replaceAll(",", "").replace(/[^0-9.\-]/g, "");
      const parsed = Number(cleaned);
      if (!cleaned || !Number.isFinite(parsed)) errors.push("价格格式不正确");
      else if (parsed <= 0) errors.push("价格必须大于0");
    }
    [["moq", "起订量"], ["stock_qty", "库存"], ["lead_time_days", "交期"]].forEach(([field, label]) => {
      const raw = String(values?.[field] || "").trim();
      if (!raw) return;
      const parsed = parseInteger(raw);
      if (parsed === undefined) errors.push(`${label}必须是整数`);
      else if (parsed < 0) errors.push(`${label}不能小于0`);
      else if (parsed > MAX_IMPORT_INTEGER) errors.push(`${label}不能大于${MAX_IMPORT_INTEGER}`);
    });
    return errors;
  }

  function normalizedSku(row) {
    return String(row?.values?.supplier_sku || "").trim();
  }

  function needsCorrection(row) {
    return Boolean(row?.included && row.errors?.length);
  }

  function correctionCount(rows) {
    return (rows || []).filter(needsCorrection).length;
  }

  function excludeCorrectionRows(state) {
    const excluded = (state.rows || []).filter(needsCorrection);
    excluded.forEach((row) => {
      row.included = false;
    });
    state.lastExcludedCorrections = excluded;
    resolveRows(state.rows || []);
    return excluded.length;
  }

  function restoreExcludedCorrections(state) {
    const currentRows = new Set(state.rows || []);
    let restored = 0;
    (state.lastExcludedCorrections || []).forEach((row) => {
      if (!currentRows.has(row) || row.included) return;
      row.included = true;
      restored += 1;
    });
    state.lastExcludedCorrections = [];
    resolveRows(state.rows || []);
    return restored;
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
      correctionOnly: false,
      lastExcludedCorrections: [],
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
    state.lastExcludedCorrections = [];
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
    row.errors = validateRow(row.values);
    resolveRows(state.rows);
    return state;
  }

  function filteredRows(state) {
    return (state.rows || []).filter((row) => {
      if (state.sheetFilter && row.source_sheet !== state.sheetFilter) return false;
      if (state.conflictOnly && !row.conflict_group) return false;
      if (state.correctionOnly && !needsCorrection(row)) return false;
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
    return includedRows.every((row) => (
      validateRow(row.values).length === 0 && !row.conflict_group
    ));
  }

  global.MatrixImportWorkbook = {
    createWorkbookState,
    toggleSheet,
    updateRow,
    resolveRows,
    needsCorrection,
    correctionCount,
    excludeCorrectionRows,
    restoreExcludedCorrections,
    pageRows,
    canImport,
    validateRow,
  };
})(window);

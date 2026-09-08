const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


const source = fs.readFileSync(
  path.join(__dirname, "..", "app", "web", "assets", "app.js"),
  "utf8",
);


function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}


function element() {
  return {
    addEventListener() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {},
    disabled: false,
    innerHTML: "",
    textContent: "",
    value: "",
  };
}


function supplierListsHarness(api) {
  const elements = new Map();
  const getElement = (selector) => {
    if (!elements.has(selector)) elements.set(selector, element());
    return elements.get(selector);
  };
  const document = {
    addEventListener() {},
    querySelector: getElement,
    querySelectorAll() { return []; },
  };
  const context = vm.createContext({
    clearTimeout,
    console,
    document,
    FormData,
    Matrix: {
      api,
      escapeHtml(value) { return String(value ?? ""); },
      formatDate(value) { return String(value ?? ""); },
      formatMoney(value) { return String(value ?? ""); },
      statusBadge(value) { return String(value ?? ""); },
      toast() {},
    },
    setTimeout,
    URLSearchParams,
    window: {
      MatrixImportWorkbook: {},
      addEventListener() {},
      location: { hash: "", href: "" },
    },
  });
  vm.runInContext(source, context);
  return {
    elements,
    evaluate(expression) { return vm.runInContext(expression, context); },
  };
}


function rows(prefix, count) {
  return Array.from({ length: count }, (_, index) => ({
    id: `${prefix}-${String(index + 1).padStart(4, "0")}`,
    name: `${prefix} ${index + 1}`,
    product_name: `${prefix} ${index + 1}`,
    brand: "TEST",
    model: `M-${index + 1}`,
    category: "测试",
    status: "ACTIVE",
    offer_count: 1,
    supplier_sku: `SKU-${index + 1}`,
    price: "10.0000",
    currency: "CNY",
    moq: 1,
    stock_qty: 20,
    lead_time_days: 3,
    fulfillment_mode: "PURCHASE",
    updated_at: "2026-09-09T00:00:00Z",
  }));
}


function chunkApi(collections, requests) {
  return async (requestPath) => {
    requests.push(requestPath);
    const url = new URL(requestPath, "https://supplier.test");
    const collection = url.pathname === "/api/products" ? collections.products : collections.offers;
    const offset = Number(url.searchParams.get("offset"));
    const limit = Number(url.searchParams.get("limit"));
    return collection.slice(offset, offset + limit);
  };
}


test("products load all 1,792 rows in chunks and render 50-row UI pages", async () => {
  const requests = [];
  const products = rows("Product", 1792);
  const harness = supplierListsHarness(chunkApi({ products, offers: [] }, requests));

  await harness.evaluate("loadProducts() ");

  assert.deepEqual(
    requests.map((requestPath) => Number(new URL(requestPath, "https://supplier.test").searchParams.get("offset"))),
    [0, 500, 1000, 1500],
  );
  assert.equal(harness.evaluate("state.products.length"), 1792);
  assert.equal(new Set(harness.evaluate("state.products.map((item) => item.id)")).size, 1792);
  assert.equal((harness.elements.get("#products-tbody").innerHTML.match(/<tr>/g) || []).length, 50);
  assert.match(harness.elements.get("#products-tbody").innerHTML, /Product 1/);
  assert.doesNotMatch(harness.elements.get("#products-tbody").innerHTML, /Product 51</);
  assert.equal(harness.elements.get("#products-count").textContent, "显示 1–50 / 共 1792 条");

  harness.evaluate("state.productPage = 36; renderProducts()");
  assert.equal((harness.elements.get("#products-tbody").innerHTML.match(/<tr>/g) || []).length, 42);
  assert.match(harness.elements.get("#products-tbody").innerHTML, /Product 1751/);
  assert.match(harness.elements.get("#products-tbody").innerHTML, /Product 1792/);
});


test("product table pagination never truncates offer product options", async () => {
  const products = rows("Selectable product", 1792);
  const harness = supplierListsHarness(chunkApi({ products, offers: [] }, []));

  await harness.evaluate("loadProducts()");
  harness.evaluate("state.productPage = 20; renderProducts()");

  const options = harness.elements.get("#offer-product-id").innerHTML;
  assert.equal((options.match(/<option/g) || []).length, 1793);
  assert.match(options, /Selectable product 1792/);
});


test("offers load all rows, paginate, and search or brand changes reset page one", async () => {
  const requests = [];
  const offers = rows("Offer", 1792);
  const harness = supplierListsHarness(chunkApi({ products: [], offers }, requests));
  harness.elements.get("#offers-search") || harness.evaluate("void 0");
  harness.elements.get("#offers-brand") || harness.evaluate("void 0");

  await harness.evaluate("loadOffers() ");
  assert.deepEqual(
    requests.map((requestPath) => Number(new URL(requestPath, "https://supplier.test").searchParams.get("offset"))),
    [0, 500, 1000, 1500],
  );
  assert.equal(harness.evaluate("state.offers.length"), 1792);
  assert.equal((harness.elements.get("#offers-tbody").innerHTML.match(/<tr>/g) || []).length, 50);
  harness.evaluate("state.offerPage = 36; renderOffers()");
  assert.equal((harness.elements.get("#offers-tbody").innerHTML.match(/<tr>/g) || []).length, 42);
  assert.match(harness.elements.get("#offers-tbody").innerHTML, /Offer 1751/);
  assert.match(harness.elements.get("#offers-tbody").innerHTML, /Offer 1792/);

  await harness.evaluate('loadOffers("needle", null)');
  assert.equal(harness.evaluate("state.offerPage"), 1);
  assert.equal(new URL(requests.at(-4), "https://supplier.test").searchParams.get("q"), "needle");
  harness.evaluate("state.offerPage = 8");
  await harness.evaluate('loadOffers(null, "TEST")');
  assert.equal(harness.evaluate("state.offerPage"), 1);
  assert.equal(new URL(requests.at(-4), "https://supplier.test").searchParams.get("brand"), "TEST");
});


test("a slow old product request cannot overwrite a newer search result", async () => {
  const oldRequest = deferred();
  const newRows = rows("New result", 2);
  const requests = [];
  const api = (requestPath) => {
    requests.push(requestPath);
    const url = new URL(requestPath, "https://supplier.test");
    if (url.searchParams.get("q") === "old") return oldRequest.promise;
    return Promise.resolve(newRows);
  };
  const harness = supplierListsHarness(api);

  const oldLoad = harness.evaluate('loadProducts("old")');
  await harness.evaluate('loadProducts("new")');
  oldRequest.resolve(rows("Old result", 1));
  await oldLoad;

  assert.deepEqual(
    JSON.parse(JSON.stringify(harness.evaluate("state.products.map((item) => item.name)"))),
    ["New result 1", "New result 2"],
  );
  assert.match(harness.elements.get("#products-tbody").innerHTML, /New result 1/);
  assert.doesNotMatch(harness.elements.get("#products-tbody").innerHTML, /Old result/);
});


test("chunk loading deduplicates IDs and stops if a full page makes no progress", async () => {
  const repeated = rows("Repeated", 500);
  let calls = 0;
  const harness = supplierListsHarness(async () => {
    calls += 1;
    return repeated;
  });

  await harness.evaluate("loadProducts()");

  assert.equal(calls, 2);
  assert.equal(harness.evaluate("state.products.length"), 500);
});

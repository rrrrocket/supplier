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
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}


function element() {
  let html = "";
  return {
    addEventListener() {},
    classList: { add() {}, remove() {}, toggle() {} },
    dataset: {},
    disabled: false,
    get innerHTML() { return html; },
    set innerHTML(value) {
      html = value;
      this.innerHTMLWrites += 1;
    },
    innerHTMLWrites: 0,
    modalOpened: false,
    reset() {},
    showModal() { this.modalOpened = true; },
    textContent: "",
    value: "",
  };
}


function supplierListsHarness(api) {
  const elements = new Map();
  const toasts = [];
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
      toast(...args) { toasts.push(args); },
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
    toasts,
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
    supplier_sku_code: `SKU-${index + 1}`,
    supplier_sku_id: `supplier-sku-${String(index + 1).padStart(4, "0")}`,
    commercial_mode: "SELF_PURCHASE",
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


test("product page changes do not rebuild all offer product options", async () => {
  let products = rows("Initial product", 1792);
  const harness = supplierListsHarness(chunkApi({ get products() { return products; }, offers: [] }, []));

  await harness.evaluate("loadProducts()");
  const productOptions = harness.elements.get("#offer-product-id");
  const initialWrites = productOptions.innerHTMLWrites;

  harness.evaluate("state.productPage = 2; renderProducts()");
  assert.equal(productOptions.innerHTMLWrites, initialWrites);

  harness.evaluate("state.productPage = 36");
  products = rows("Refreshed product", 60);
  await harness.evaluate("loadProducts()");
  assert.equal(productOptions.innerHTMLWrites, initialWrites + 1);
  assert.equal((productOptions.innerHTML.match(/<option/g) || []).length, 61);
  assert.match(productOptions.innerHTML, /Refreshed product 60/);
  assert.equal(harness.evaluate("state.productPage"), 2);
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


test("stale rejected product and offer requests are ignored", async () => {
  for (const resource of ["products", "offers"]) {
    const oldRequest = deferred();
    const currentRows = rows(`Current ${resource}`, 1);
    const harness = supplierListsHarness((requestPath) => {
      const url = new URL(requestPath, "https://supplier.test");
      if (url.searchParams.get("q") === "old") return oldRequest.promise;
      return Promise.resolve(currentRows);
    });
    const loadFunction = resource === "products" ? "loadProducts" : "loadOffers";

    const oldLoad = harness.evaluate(`${loadFunction}("old")`);
    await harness.evaluate(`${loadFunction}("new")`);
    oldRequest.reject(new Error(`stale ${resource} failure`));

    await assert.doesNotReject(oldLoad);
    assert.equal(harness.evaluate(`state.${resource}[0].name`), `Current ${resource} 1`);
  }
});


test("current product and offer request failures still reject", async () => {
  for (const resource of ["products", "offers"]) {
    const harness = supplierListsHarness(async () => {
      throw new Error(`current ${resource} failure`);
    });
    const loadFunction = resource === "products" ? "loadProducts" : "loadOffers";

    await assert.rejects(
      harness.evaluate(`${loadFunction}("current")`),
      new RegExp(`current ${resource} failure`),
    );
  }
});


test("an old offer-brand route load cannot restore an obsolete filter", async () => {
  const brandRequest = deferred();
  const requests = [];
  const harness = supplierListsHarness((requestPath) => {
    requests.push(requestPath);
    const url = new URL(requestPath, "https://supplier.test");
    if (url.pathname === "/api/offers/brands") return brandRequest.promise;
    const brand = url.searchParams.get("brand") || "A";
    return Promise.resolve(rows(`Offer brand ${brand}`, 1));
  });
  const brandSelect = harness.elements.get("#offers-brand") || harness.evaluate('document.querySelector("#offers-brand")');
  brandSelect.value = "A";

  const routeLoad = harness.evaluate('renderRoute("offers")');
  brandSelect.value = "B";
  await harness.evaluate('loadOffers(null, "B")');
  brandRequest.resolve(["A", "B"]);
  await routeLoad;

  assert.equal(brandSelect.value, "B");
  assert.equal(harness.evaluate("state.offers[0].name"), "Offer brand B 1");
  assert.equal(
    requests.filter((requestPath) => requestPath.startsWith("/api/offers?")).length,
    1,
  );
});


test("a rejected old offer-brand route load is silent after brand B loads", async () => {
  const oldBrandRequest = deferred();
  const requests = [];
  const harness = supplierListsHarness((requestPath) => {
    requests.push(requestPath);
    const url = new URL(requestPath, "https://supplier.test");
    if (url.pathname === "/api/offers/brands") return oldBrandRequest.promise;
    const brand = url.searchParams.get("brand") || "A";
    return Promise.resolve(rows(`Offer brand ${brand}`, 1));
  });
  const brandSelect = harness.evaluate('document.querySelector("#offers-brand")');
  brandSelect.value = "A";

  const oldRouteLoad = harness.evaluate('renderRoute("offers")');
  brandSelect.value = "B";
  await harness.evaluate('loadOffers(null, "B")');
  oldBrandRequest.reject(new Error("stale brand A failure"));

  await assert.doesNotReject(oldRouteLoad);
  assert.equal(brandSelect.value, "B");
  assert.equal(harness.evaluate("state.offers[0].name"), "Offer brand B 1");
  assert.equal(
    requests.filter((requestPath) => requestPath.startsWith("/api/offers?")).length,
    1,
  );
  assert.deepEqual(harness.toasts, []);
});


test("a rejected current offer-brand request still rejects", async () => {
  const harness = supplierListsHarness(async (requestPath) => {
    if (requestPath === "/api/offers/brands") throw new Error("current brand failure");
    return [];
  });

  await assert.rejects(
    harness.evaluate("loadOfferBrands()"),
    /current brand failure/,
  );
});


test("empty supplier lists keep both pagination boundaries disabled", () => {
  const harness = supplierListsHarness(async () => []);

  harness.evaluate("renderProducts(); renderOffers()");

  assert.equal(harness.elements.get("#products-count").textContent, "显示 0–0 / 共 0 条");
  assert.equal(harness.elements.get("#products-prev-page").disabled, true);
  assert.equal(harness.elements.get("#products-next-page").disabled, true);
  assert.equal(harness.elements.get("#offers-count").textContent, "显示 0–0 / 共 0 条");
  assert.equal(harness.elements.get("#offers-prev-page").disabled, true);
  assert.equal(harness.elements.get("#offers-next-page").disabled, true);
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


test("product dialog waits for assigned brands and renders their cooperation modes", async () => {
  const cooperations = deferred();
  const requests = [];
  const harness = supplierListsHarness((requestPath) => {
    requests.push(requestPath);
    if (requestPath === "/api/supplier-catalog/brand-cooperations") {
      return cooperations.promise;
    }
    return Promise.resolve([]);
  });
  const dialog = harness.evaluate('document.querySelector("#product-dialog")');

  const opening = harness.evaluate("openProductDialog()");
  await Promise.resolve();
  assert.equal(dialog.modalOpened, false);

  cooperations.resolve([
    {
      brand_id: "brand-a",
      brand_code: "BRAND-A",
      brand_name: "品牌 A",
      commercial_mode: "SELF_PURCHASE",
      status: "ACTIVE",
    },
    {
      brand_id: "brand-b",
      brand_code: "BRAND-B",
      brand_name: "品牌 B",
      commercial_mode: "B2B",
      status: "ACTIVE",
    },
  ]);
  await opening;

  assert.deepEqual(requests, ["/api/supplier-catalog/brand-cooperations"]);
  assert.equal(dialog.modalOpened, true);
  const options = harness.elements.get("#product-brand").innerHTML;
  assert.match(options, /品牌 A · A 模式（自营采购）/);
  assert.match(options, /品牌 B · C 模式（B2B）/);
});


test("product and offer dialogs catch current brand catalog failures with a clear toast", async () => {
  for (const dialogType of ["product", "offer"]) {
    const harness = supplierListsHarness(async (requestPath) => {
      if (requestPath === "/api/supplier-catalog/brand-cooperations") {
        throw new Error(`current ${dialogType} brand failure`);
      }
      return [];
    });
    if (dialogType === "offer") {
      harness.evaluate('state.products = [{ id: "product-a", brand_id: "brand-a" }]');
    }
    const dialog = harness.evaluate(`document.querySelector("#${dialogType}-dialog")`);

    await assert.doesNotReject(
      harness.evaluate(dialogType === "product" ? "openProductDialog()" : "openOfferDialog()"),
    );

    assert.equal(dialog.modalOpened, false);
    assert.equal(harness.toasts.length, 1);
    assert.match(harness.toasts[0].join(" "), /品牌/);
    assert.match(harness.toasts[0].join(" "), /加载失败/);
  }
});


test("product and offer dialogs stay closed when no active assigned brand exists", async () => {
  for (const dialogType of ["product", "offer"]) {
    const harness = supplierListsHarness(async (requestPath) => {
      if (requestPath === "/api/supplier-catalog/brand-cooperations") return [];
      return [];
    });
    if (dialogType === "offer") {
      harness.evaluate(`
        state.products = [{ id: "product-a", brand_id: "brand-a" }];
        document.querySelector("#offer-form").elements = {
          product_id: { disabled: false },
          supplier_sku_code: { disabled: false },
        };
      `);
    }
    const dialog = harness.evaluate(`document.querySelector("#${dialogType}-dialog")`);

    await assert.doesNotReject(
      harness.evaluate(dialogType === "product" ? "openProductDialog()" : "openOfferDialog()"),
    );

    assert.equal(dialog.modalOpened, false);
    assert.equal(harness.toasts.length, 1);
    assert.match(harness.toasts[0].join(" "), /暂无已分配有效品牌/);
    assert.match(harness.toasts[0].join(" "), /联系平台/);
  }
});


test("a stale rejected brand catalog dialog load remains silent", async () => {
  const oldRequest = deferred();
  let calls = 0;
  const harness = supplierListsHarness((requestPath) => {
    assert.equal(requestPath, "/api/supplier-catalog/brand-cooperations");
    calls += 1;
    if (calls === 1) return oldRequest.promise;
    return Promise.resolve([{
      brand_id: "brand-current",
      brand_code: "CURRENT",
      brand_name: "当前品牌",
      commercial_mode: "B2B",
      status: "ACTIVE",
    }]);
  });

  const staleOpening = harness.evaluate("openProductDialog()");
  await harness.evaluate("openProductDialog()");
  oldRequest.reject(new Error("stale brand failure"));

  await assert.doesNotReject(staleOpening);
  assert.equal(harness.elements.get("#product-dialog").modalOpened, true);
  assert.deepEqual(harness.toasts, []);
});


test("offer rows label mode A cost and show stable SKU IDs without truncating pages", () => {
  const harness = supplierListsHarness(async () => []);
  const offers = rows("Offer mode", 51);
  offers[1].commercial_mode = "B2B";
  harness.evaluate(`state.offers = ${JSON.stringify(offers)}; renderOffers()`);

  const firstPage = harness.elements.get("#offers-tbody").innerHTML;
  assert.equal((firstPage.match(/<tr>/g) || []).length, 50);
  assert.match(firstPage, /SKU-1/);
  assert.match(firstPage, /supplier-sku-0001/);
  assert.match(firstPage, /成本价/);
  assert.match(firstPage, /供货价/);

  harness.evaluate("state.offerPage = 2; renderOffers()");
  assert.equal((harness.elements.get("#offers-tbody").innerHTML.match(/<tr>/g) || []).length, 1);
});


test("offer form price label follows the selected product cooperation mode", () => {
  const harness = supplierListsHarness(async () => []);
  harness.evaluate(`
    state.products = [
      { id: "product-a", brand_id: "brand-a" },
      { id: "product-c", brand_id: "brand-c" },
    ];
    state.brandCooperations = [
      { brand_id: "brand-a", commercial_mode: "SELF_PURCHASE", status: "ACTIVE" },
      { brand_id: "brand-c", commercial_mode: "B2B", status: "ACTIVE" },
    ];
  `);

  harness.evaluate('refreshOfferPriceLabel("product-a")');
  assert.equal(harness.elements.get("#offer-price-label").textContent, "成本价");

  harness.evaluate('refreshOfferPriceLabel("product-c")');
  assert.equal(harness.elements.get("#offer-price-label").textContent, "供货价");
});

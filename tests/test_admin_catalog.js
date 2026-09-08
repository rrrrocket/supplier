const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


const source = fs.readFileSync(
  path.join(__dirname, "..", "app", "web", "assets", "admin.js"),
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


function element({ select = false } = {}) {
  let html = "";
  return {
    checked: false,
    classList: { add() {}, remove() {}, toggle() {} },
    close() {},
    dataset: {},
    disabled: false,
    querySelectorAll() { return []; },
    showModal() {},
    textContent: "",
    value: "",
    addEventListener() {},
    get innerHTML() { return html; },
    set innerHTML(value) {
      html = value;
      if (select) {
        const firstOption = value.match(/<option value="([^"]+)"/);
        this.value = firstOption ? firstOption[1] : "";
      }
    },
  };
}


function adminHarness(api) {
  const elements = new Map();
  const select = element({ select: true });
  elements.set("#brand-cooperation-brand", select);
  elements.set("#brand-cooperation-mode", element({ select: true }));
  elements.set("#brand-cooperation-dialog", element());
  elements.set("#brand-cooperation-dialog-title", element());
  elements.set("#brand-cooperation-dialog-subtitle", element());
  elements.set("#brand-cooperation-list", element());
  elements.set("#brand-cooperation-current", element());
  elements.set("#save-brand-cooperation", element());

  const document = {
    addEventListener() {},
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, element());
      return elements.get(selector);
    },
    querySelectorAll() { return []; },
  };
  const context = vm.createContext({
    console,
    document,
    FormData,
    Matrix: {
      api,
      escapeHtml(value) { return String(value ?? ""); },
      statusBadge(status) { return `<span>${status}</span>`; },
      toast() {},
    },
    navigator: { clipboard: { writeText: async () => {} } },
    setTimeout,
    window: {
      addEventListener() {},
      confirm() { return true; },
      location: { hash: "", href: "", origin: "https://supplier.test" },
    },
  });
  vm.runInContext(source, context);
  return { context, elements };
}


const supplierA = {
  organization_id: "supplier-a",
  organization_code: "SUP-A",
  organization_name: "供应商 A",
};
const supplierB = {
  organization_id: "supplier-b",
  organization_code: "SUP-B",
  organization_name: "供应商 B",
};
const brandA = {
  id: "brand-a",
  code: "BRAND-A",
  name: "品牌 A",
  status: "ACTIVE",
  updated_at: "2026-09-09T00:00:00Z",
};
const brandB = {
  id: "brand-b",
  code: "BRAND-B",
  name: "品牌 B",
  status: "ACTIVE",
  updated_at: "2026-09-09T00:00:00Z",
};


test("opening a supplier clears stale brand choices and disables save while loading", () => {
  const never = deferred();
  const { context, elements } = adminHarness(() => never.promise);
  vm.runInContext(
    `adminState.suppliers = ${JSON.stringify([supplierA])}`,
    context,
  );
  const select = elements.get("#brand-cooperation-brand");
  const save = elements.get("#save-brand-cooperation");
  select.innerHTML = '<option value="stale-brand">旧品牌</option>';
  save.disabled = false;

  vm.runInContext('openBrandCooperation("supplier-a")', context);

  assert.equal(select.innerHTML, "");
  assert.equal(select.value, "");
  assert.equal(save.disabled, true);
});


test("a stale supplier response cannot replace the latest dialog data or save target", async () => {
  const pendingGets = [];
  const requests = [];
  const api = (requestPath, options = {}) => {
    requests.push({ options, path: requestPath });
    if (options.method === "PUT") {
      return Promise.resolve({
        id: "cooperation-b",
        brand_id: "brand-b",
        brand_name: "品牌 B",
        commercial_mode: options.body.commercial_mode,
        status: "ACTIVE",
        supplier_id: "supplier-b",
        updated_at: "2026-09-09T00:00:00Z",
        valid_from: null,
        valid_to: null,
      });
    }
    if (pendingGets.length >= 4) {
      return Promise.resolve([{
        id: "cooperation-b",
        brand_id: "brand-b",
        brand_name: "品牌 B",
        commercial_mode: "B2B",
        status: "ACTIVE",
        supplier_id: "supplier-b",
        updated_at: "2026-09-09T00:00:00Z",
        valid_from: null,
        valid_to: null,
      }]);
    }
    const request = deferred();
    pendingGets.push({ path: requestPath, request });
    return request.promise;
  };
  const { context, elements } = adminHarness(api);
  vm.runInContext(
    `adminState.suppliers = ${JSON.stringify([supplierA, supplierB])}`,
    context,
  );

  const openingA = vm.runInContext('openBrandCooperation("supplier-a")', context);
  const openingB = vm.runInContext('openBrandCooperation("supplier-b")', context);
  assert.deepEqual(pendingGets.map((item) => item.path), [
    "/api/admin/brands",
    "/api/admin/suppliers/supplier-a/brand-cooperations",
    "/api/admin/brands",
    "/api/admin/suppliers/supplier-b/brand-cooperations",
  ]);

  pendingGets[2].request.resolve([brandB]);
  pendingGets[3].request.resolve([{
    id: "cooperation-b",
    brand_id: "brand-b",
    brand_name: "品牌 B",
    commercial_mode: "B2B",
    status: "ACTIVE",
    supplier_id: "supplier-b",
    updated_at: "2026-09-09T00:00:00Z",
    valid_from: null,
    valid_to: null,
  }]);
  await openingB;

  pendingGets[0].request.resolve([brandA]);
  pendingGets[1].request.resolve([{
    id: "cooperation-a",
    brand_id: "brand-a",
    brand_name: "品牌 A",
    commercial_mode: "SELF_PURCHASE",
    status: "ACTIVE",
    supplier_id: "supplier-a",
    updated_at: "2026-09-09T00:00:00Z",
    valid_from: null,
    valid_to: null,
  }]);
  await openingA;

  const select = elements.get("#brand-cooperation-brand");
  assert.match(select.innerHTML, /品牌 B/);
  assert.doesNotMatch(select.innerHTML, /品牌 A/);
  assert.equal(select.value, "brand-b");
  elements.get("#brand-cooperation-mode").value = "JOINT_OPERATION";
  await vm.runInContext(
    "saveBrandCooperation({ preventDefault() {} })",
    context,
  );

  const put = requests.find((request) => request.options.method === "PUT");
  assert.deepEqual(JSON.parse(JSON.stringify(put)), {
    options: {
      body: { commercial_mode: "JOINT_OPERATION" },
      method: "PUT",
    },
    path: "/api/admin/suppliers/supplier-b/brands/brand-b/cooperation",
  });
});

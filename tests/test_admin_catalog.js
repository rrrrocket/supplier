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
  const listeners = new Map();
  return {
    checked: false,
    classList: { add() {}, remove() {}, toggle() {} },
    close() {
      this.open = false;
      this.dispatchEvent({ type: "close" });
    },
    dataset: {},
    disabled: false,
    onclick: null,
    open: false,
    querySelectorAll() { return []; },
    showModal() { this.open = true; },
    textContent: "",
    value: "",
    addEventListener(type, listener) {
      const handlers = listeners.get(type) || [];
      handlers.push(listener);
      listeners.set(type, handlers);
    },
    dispatchEvent(event) {
      event.preventDefault ||= () => {};
      for (const listener of listeners.get(event.type) || []) listener(event);
      if (event.type === "click" && typeof this.onclick === "function") this.onclick(event);
      return true;
    },
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

  let tokenDialogOpened = false;
  const tokenDialog = element();
  tokenDialog.showModal = () => {
    tokenDialog.open = true;
    tokenDialogOpened = true;
  };
  const tokenCloseButtons = [element(), element()];
  elements.set("#integration-token-dialog", tokenDialog);
  elements.set("#integration-token-value", element());
  elements.set("#copy-integration-token", element());
  elements.set("#integration-client-name", element());
  elements.set("#integration-client-expires-at", element());
  elements.set("#integration-client-scopes", element());
  elements.set("#integration-clients-tbody", element());
  elements.set("#integration-clients-count", element());
  elements.set("#create-integration-client", element());

  const storageWrites = [];
  const storage = {
    getItem() { return null; },
    removeItem() {},
    setItem(key, value) { storageWrites.push({ key, value }); },
  };

  const document = {
    addEventListener() {},
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, element());
      return elements.get(selector);
    },
    querySelectorAll(selector) {
      if (selector === "[data-close-integration-token]") return tokenCloseButtons;
      return [];
    },
  };
  const context = vm.createContext({
    console,
    document,
    FormData,
    Matrix: {
      api,
      escapeHtml(value) { return String(value ?? ""); },
      formatDate(value) { return String(value ?? ""); },
      statusBadge(status) { return `<span>${status}</span>`; },
      toast() {},
    },
    navigator: { clipboard: { writeText: async () => {} } },
    localStorage: storage,
    sessionStorage: storage,
    setTimeout,
    window: {
      addEventListener() {},
      confirm() { return true; },
      location: { hash: "", href: "", origin: "https://supplier.test" },
    },
  });
  vm.runInContext(source, context);
  return {
    context,
    elements,
    storageWrites,
    tokenCloseButtons,
    tokenDialogOpened: () => tokenDialogOpened,
  };
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


test("expired integration clients are labeled expired and cannot rotate", () => {
  const { context, elements } = adminHarness(async () => []);
  vm.runInContext(
    `adminState.integrationClients = ${JSON.stringify([{
      expires_at: "2000-01-01T00:00:00Z",
      id: "expired-client",
      is_active: true,
      last_used_at: null,
      name: "已过期调用方",
      scopes: ["suppliers:read"],
      token_prefix: "m1i_expired",
    }])}; renderIntegrationClients();`,
    context,
  );

  const html = elements.get("#integration-clients-tbody").innerHTML;
  assert.match(html, />EXPIRED</);
  assert.match(html, /data-rotate-integration="expired-client" disabled/);
});


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


test("creating an integration client shows the token only in the warning dialog", async () => {
  const token = "m1i_once-only-secret-token";
  const requests = [];
  const api = async (requestPath, options = {}) => {
    requests.push({ options, path: requestPath });
    if (options.method === "POST") {
      return {
        id: "integration-a",
        is_active: true,
        name: "ERP 同步",
        scopes: ["suppliers:read"],
        token,
        token_prefix: token.slice(0, 12),
      };
    }
    return [{
      id: "integration-a",
      is_active: true,
      name: "ERP 同步",
      scopes: ["suppliers:read"],
      token_prefix: token.slice(0, 12),
    }];
  };
  const harness = adminHarness(api);
  harness.elements.get("#integration-client-name").value = "ERP 同步";
  harness.elements.get("#integration-client-expires-at").value = "";
  const checkedScope = element();
  checkedScope.value = "suppliers:read";
  harness.elements.get("#integration-client-scopes").querySelectorAll = () => [checkedScope];

  await vm.runInContext(
    "createIntegrationClient({ preventDefault() {} })",
    harness.context,
  );

  assert.equal(harness.tokenDialogOpened(), true);
  assert.equal(harness.elements.get("#integration-token-value").textContent, token);
  assert.equal(JSON.stringify(vm.runInContext("adminState", harness.context)).includes(token), false);
  assert.deepEqual(harness.storageWrites, []);
  assert.deepEqual(JSON.parse(JSON.stringify(requests[0])), {
    options: {
      body: {
        expires_at: null,
        name: "ERP 同步",
        scopes: ["suppliers:read"],
      },
      method: "POST",
    },
    path: "/api/admin/integration-clients",
  });
});


test("escape, native close, and close buttons all clear the one-time token", () => {
  const token = "m1i_escape-must-not-leave-a-secret";
  const harness = adminHarness(async () => []);
  const dialog = harness.elements.get("#integration-token-dialog");
  const tokenValue = harness.elements.get("#integration-token-value");
  const copyButton = harness.elements.get("#copy-integration-token");
  const showToken = () => vm.runInContext(
    `showIntegrationToken({name: "ERP", token_prefix: "m1i_escape", token: ${JSON.stringify(token)}})`,
    harness.context,
  );

  vm.runInContext("bindIntegrationTokenDialog()", harness.context);

  showToken();
  dialog.dispatchEvent({ type: "cancel" });
  dialog.dispatchEvent({ type: "close" });
  assert.equal(tokenValue.textContent, "");
  assert.equal(copyButton.onclick, null);

  showToken();
  dialog.dispatchEvent({ type: "close" });
  assert.equal(tokenValue.textContent, "");
  assert.equal(copyButton.onclick, null);

  showToken();
  harness.tokenCloseButtons[0].dispatchEvent({ type: "click" });
  assert.equal(tokenValue.textContent, "");
  assert.equal(copyButton.onclick, null);
});

test("all admin tables render the first fifty rows through unified pagination", () => {
  const harness = adminHarness(async () => []);
  const applications = Array.from({ length: 120 }, (_, index) => ({ id: `a-${index}`, application_no: `A-${index}`, company_name: `申请 ${index}`, company_type: "企业", province: "上海", city: "上海", contact_name: "联系人", email: "a@example.com", categories: [], cooperation_modes: [], created_at: "2026-09-09", status: "PENDING" }));
  const suppliers = Array.from({ length: 120 }, (_, index) => ({ organization_id: `s-${index}`, organization_code: `S-${index}`, organization_name: `供应商 ${index}`, legal_name: "公司", contact_name: "联系人", contact_email: "s@example.com", profile_completion: 100, product_count: 1, active_offer_count: 1, status: "ACTIVE", created_at: "2026-09-09" }));
  const clients = Array.from({ length: 120 }, (_, index) => ({ id: `c-${index}`, name: `调用方 ${index}`, token_prefix: "m1i_test", scopes: [], is_active: true }));
  harness.context.applicationsFixture = applications;
  harness.context.suppliersFixture = suppliers;
  harness.context.clientsFixture = clients;
  vm.runInContext("adminState.applications = applicationsFixture; adminState.suppliers = suppliersFixture; adminState.integrationClients = clientsFixture; renderApplications(); renderSuppliers(); renderIntegrationClients();", harness.context);
  assert.equal((harness.elements.get("#applications-tbody").innerHTML.match(/<tr>/g) || []).length, 50);
  assert.equal((harness.elements.get("#suppliers-tbody").innerHTML.match(/<tr>/g) || []).length, 50);
  assert.equal((harness.elements.get("#integration-clients-tbody").innerHTML.match(/<tr>/g) || []).length, 50);
});

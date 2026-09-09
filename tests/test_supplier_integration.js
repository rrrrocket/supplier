const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const modulePath = path.join(
  __dirname,
  "..",
  "app",
  "web",
  "assets",
  "supplier-integration.js",
);
const source = fs.existsSync(modulePath) ? fs.readFileSync(modulePath, "utf8") : "";

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
  const listeners = new Map();
  return {
    addEventListener(type, listener) {
      const current = listeners.get(type) || [];
      current.push(listener);
      listeners.set(type, current);
    },
    close() { this.open = false; this.dispatch("close"); },
    dataset: {},
    disabled: false,
    dispatch(type, event = {}) {
      const results = (listeners.get(type) || []).map((listener) => listener({
        preventDefault() {},
        target: this,
        currentTarget: this,
        ...event,
      }));
      return results.at(-1);
    },
    elements: {},
    innerHTML: "",
    open: false,
    querySelector() { return null; },
    querySelectorAll() { return []; },
    reset() { this.resetCalled = true; },
    resetCalled: false,
    showModal() { this.open = true; },
    textContent: "",
    value: "",
  };
}

function supplierIntegrationHarness({
  api,
  clipboard = { writeText() {} },
  confirm = () => true,
} = {}) {
  const elements = new Map();
  const toasts = [];
  const windowListeners = new Map();
  const paginationCalls = [];
  const form = element();
  const submitButton = element();
  form.elements.name = { value: "仓储 ERP" };
  const scopes = ["supplier-skus:read", "supplier-costs:read"].map((value) => ({
    checked: true,
    value,
  }));
  form.querySelector = (selector) => selector === '[type="submit"]' ? submitButton : null;
  form.querySelectorAll = (selector) => selector === '[name="scopes"]:checked' ? scopes : [];
  elements.set("#supplier-client-form", form);
  elements.set("#supplier-clients-tbody", element());
  elements.set("#supplier-client-pagination", element());
  elements.set("#supplier-token-dialog", element());
  elements.set("#supplier-token-value", element());
  elements.set("#copy-supplier-token", element());
  elements.set("#logout-button", element());
  elements.set("[data-close-supplier-token]", element());

  const document = {
    addEventListener() {},
    querySelector(selector) { return elements.get(selector) || null; },
    querySelectorAll(selector) {
      if (selector === "[data-close-supplier-token]") {
        return [elements.get("[data-close-supplier-token]")];
      }
      return [];
    },
  };
  const window = {
    addEventListener(type, listener) {
      const current = windowListeners.get(type) || [];
      current.push(listener);
      windowListeners.set(type, current);
    },
    dispatch(type) {
      (windowListeners.get(type) || []).forEach((listener) => listener());
    },
    location: { hash: "#erp-integration" },
  };
  const context = vm.createContext({
    confirm,
    console,
    document,
    Matrix: {
      api,
      escapeHtml(value) {
        return String(value ?? "")
          .replaceAll("&", "&amp;")
          .replaceAll("<", "&lt;")
          .replaceAll(">", "&gt;")
          .replaceAll('"', "&quot;")
          .replaceAll("'", "&#039;");
      },
      formatDate(value) { return String(value ?? ""); },
      statusBadge(value) { return `<span>${value}</span>`; },
      toast(...args) { toasts.push(args); },
    },
    MatrixPagination: {
      render(_container, options) {
        paginationCalls.push(options);
        return options;
      },
    },
    navigator: { clipboard },
    window,
  });
  vm.runInContext(source, context);
  assert.ok(window.SupplierIntegration, "supplier integration module must register");
  window.SupplierIntegration.init();
  return { elements, form, paginationCalls, submitButton, toasts, window };
}

function client(overrides = {}) {
  return {
    id: "client-a",
    name: "仓储 ERP",
    token_prefix: "m1i_abcd1234",
    scopes: ["supplier-skus:read"],
    is_active: true,
    expires_at: null,
    created_at: "2026-09-10T00:00:00Z",
    ...overrides,
  };
}

function page(items = []) {
  return { items, total: items.length, page: 1, page_size: 50 };
}

test("creation shows plaintext once and list rendering never includes it", async () => {
  const secret = "m1i_secret";
  const harness = supplierIntegrationHarness({
    api: async (_requestPath, options) => options?.method === "POST"
      ? client({ token: secret })
      : page([client({ token: secret })]),
  });

  await harness.form.dispatch("submit");

  assert.equal(harness.elements.get("#supplier-token-value").textContent, secret);
  assert.equal(harness.elements.get("#supplier-token-dialog").open, true);
  assert.doesNotMatch(harness.elements.get("#supplier-clients-tbody").innerHTML, /m1i_secret/);
  harness.elements.get("#supplier-token-dialog").dispatch("close");
  assert.equal(harness.elements.get("#supplier-token-value").textContent, "");
});

test("cancel and leaving the ERP view clear the plaintext token", () => {
  const harness = supplierIntegrationHarness({ api: async () => page() });
  const tokenValue = harness.elements.get("#supplier-token-value");
  const dialog = harness.elements.get("#supplier-token-dialog");

  tokenValue.textContent = "first-secret";
  dialog.dispatch("cancel");
  assert.equal(tokenValue.textContent, "");

  tokenValue.textContent = "second-secret";
  harness.window.location.hash = "#products";
  harness.window.dispatch("hashchange");
  assert.equal(tokenValue.textContent, "");

  tokenValue.textContent = "third-secret";
  harness.window.dispatch("pagehide");
  assert.equal(tokenValue.textContent, "");
});

test("clipboard rejection tells the supplier to copy the token manually", async () => {
  const harness = supplierIntegrationHarness({
    api: async () => page(),
    clipboard: {
      async writeText() {
        throw new Error("clipboard permission denied");
      },
    },
  });
  harness.elements.get("#supplier-token-value").textContent = "m1i_copy_me";

  await harness.elements.get("#copy-supplier-token").dispatch("click");

  assert.deepEqual(harness.toasts, [[
    "复制失败",
    "浏览器无法自动复制，请手动选择并复制上方令牌。",
    "error",
  ]]);
});

test("unavailable clipboard API tells the supplier to copy the token manually", async () => {
  const harness = supplierIntegrationHarness({
    api: async () => page(),
    clipboard: null,
  });
  harness.elements.get("#supplier-token-value").textContent = "m1i_copy_me";

  await harness.elements.get("#copy-supplier-token").dispatch("click");

  assert.deepEqual(harness.toasts, [[
    "复制失败",
    "浏览器无法自动复制，请手动选择并复制上方令牌。",
    "error",
  ]]);
});

test("rotation clears a previous token before starting the request", async () => {
  const rotation = deferred();
  const harness = supplierIntegrationHarness({
    api: async (requestPath) => requestPath.endsWith("/rotate")
      ? rotation.promise
      : page([client()]),
  });
  await harness.window.SupplierIntegration.loadSupplierClients();
  harness.elements.get("#supplier-token-value").textContent = "old-secret";

  const pending = harness.elements.get("#supplier-clients-tbody").dispatch("click", {
    target: { closest: () => ({ dataset: { rotate: "client-a" } }) },
  });

  assert.equal(harness.elements.get("#supplier-token-value").textContent, "");
  rotation.resolve(client({ token: "new-secret" }));
  await pending;
  assert.equal(harness.elements.get("#supplier-token-value").textContent, "new-secret");
});

test("revocation requires confirmation before sending the request", async () => {
  const requests = [];
  let approved = false;
  const harness = supplierIntegrationHarness({
    api: async (requestPath, options) => {
      requests.push([requestPath, options]);
      return requestPath.endsWith("/revoke") ? client({ is_active: false }) : page([client()]);
    },
    confirm: () => approved,
  });
  await harness.window.SupplierIntegration.loadSupplierClients();
  const revoke = () => harness.elements.get("#supplier-clients-tbody").dispatch("click", {
    target: { closest: () => ({ dataset: { revoke: "client-a" } }) },
  });

  await revoke();
  assert.equal(requests.filter(([requestPath]) => requestPath.endsWith("/revoke")).length, 0);

  approved = true;
  await revoke();
  assert.equal(requests.filter(([requestPath]) => requestPath.endsWith("/revoke")).length, 1);
});

test("pagination sends the selected supported page size", async () => {
  const requests = [];
  const harness = supplierIntegrationHarness({
    api: async (requestPath) => {
      requests.push(requestPath);
      return page();
    },
  });
  await harness.window.SupplierIntegration.loadSupplierClients();

  await harness.paginationCalls.at(-1).onChange(1, 200);

  const url = new URL(requests.at(-1), "https://supplier.test");
  assert.equal(url.searchParams.get("page"), "1");
  assert.equal(url.searchParams.get("page_size"), "200");
});

test("the current failed list request shows an error toast", async () => {
  const harness = supplierIntegrationHarness({
    api: async () => { throw new Error("网络中断"); },
  });

  await harness.window.SupplierIntegration.loadSupplierClients();

  assert.deepEqual(harness.toasts, [["凭证加载失败", "网络中断", "error"]]);
});

test("pending creation is single-flight and route exit invalidates its token response", async () => {
  const creation = deferred();
  const requests = [];
  const harness = supplierIntegrationHarness({
    api: async (requestPath, options) => {
      requests.push([requestPath, options]);
      return options?.method === "POST" ? creation.promise : page();
    },
  });

  const first = harness.form.dispatch("submit");
  const duplicate = harness.form.dispatch("submit");
  const disabledWhilePending = harness.submitButton.disabled;
  harness.window.location.hash = "#products";
  harness.window.dispatch("hashchange");
  creation.resolve(client({ token: "abandoned-create-secret" }));
  await Promise.all([first, duplicate]);

  assert.equal(
    requests.filter(([, options]) => options?.method === "POST").length,
    1,
  );
  assert.equal(disabledWhilePending, true);
  assert.equal(harness.submitButton.disabled, false);
  assert.equal(harness.elements.get("#supplier-token-value").textContent, "");
  assert.equal(harness.elements.get("#supplier-token-dialog").open, false);
});

test("pending rotation is single-flight and logout invalidation ignores its token response", async () => {
  const rotation = deferred();
  const requests = [];
  const harness = supplierIntegrationHarness({
    api: async (requestPath, options) => {
      requests.push([requestPath, options]);
      return requestPath.endsWith("/rotate") ? rotation.promise : page([client()]);
    },
  });
  await harness.window.SupplierIntegration.loadSupplierClients();
  const rotateButton = element();
  rotateButton.dataset.rotate = "client-a";
  const rotate = () => harness.elements.get("#supplier-clients-tbody").dispatch("click", {
    target: { closest: () => rotateButton },
  });

  const first = rotate();
  const duplicate = rotate();
  const disabledWhilePending = rotateButton.disabled;
  harness.elements.get("#logout-button").dispatch("click");
  rotation.resolve(client({ token: "abandoned-rotate-secret" }));
  await Promise.all([first, duplicate]);

  assert.equal(
    requests.filter(([requestPath]) => requestPath.endsWith("/rotate")).length,
    1,
  );
  assert.equal(disabledWhilePending, true);
  assert.equal(rotateButton.disabled, false);
  assert.equal(harness.elements.get("#supplier-token-value").textContent, "");
  assert.equal(harness.elements.get("#supplier-token-dialog").open, false);
});

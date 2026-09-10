const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


const source = fs.readFileSync(
  path.join(__dirname, "..", "app", "web", "assets", "admin.js"),
  "utf8",
);
const operatorSource = fs.readFileSync(
  path.join(__dirname, "..", "app", "web", "assets", "admin-operator.js"),
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


function element({ select = false, selector = "" } = {}) {
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
    selector,
    querySelector() { return null; },
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


function adminHarness(api, { includeOperator = false } = {}) {
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

  const paginationCalls = [];
  const pagination = {
    render(container, options) {
      paginationCalls.push({ container: container.selector, options });
    },
  };
  const document = {
    addEventListener() {},
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, element({ selector }));
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
    MatrixPagination: pagination,
    alert() {},
    prompt() { return ""; },
    navigator: { clipboard: { writeText: async () => {} } },
    localStorage: storage,
    sessionStorage: storage,
    setTimeout,
    window: {
      addEventListener() {},
      confirm() { return true; },
      location: { hash: "", href: "", origin: "https://supplier.test" },
      MatrixPagination: pagination,
    },
  });
  vm.runInContext(source, context);
  if (includeOperator) vm.runInContext(operatorSource, context);
  return {
    context,
    elements,
    storageWrites,
    paginationCalls,
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
      client_type: "SYSTEM",
      owner_organization_id: null,
      scopes: ["suppliers:read"],
      token_prefix: "m1i_expired",
    }])}; renderIntegrationClients();`,
    context,
  );

  const html = elements.get("#integration-clients-tbody").innerHTML;
  assert.match(html, />EXPIRED</);
  assert.doesNotMatch(html, /data-rotate-integration="expired-client"/);
});


test("platform credentials rotate and revoke while supplier credentials only revoke", () => {
  const { context, elements } = adminHarness(async () => []);
  const clients = [
    {
      id: "system-client",
      name: "平台调用方",
      client_type: "SYSTEM",
      owner_organization_id: null,
      token_prefix: "m1i_system",
      scopes: ["suppliers:read"],
      is_active: true,
      expires_at: null,
      last_used_at: null,
    },
    {
      id: "supplier-client",
      name: "供应商 ERP",
      client_type: "SUPPLIER",
      owner_organization_id: "supplier-organization-id",
      token_prefix: "m1i_supplier",
      scopes: ["supplier-skus:read"],
      is_active: true,
      expires_at: null,
      last_used_at: null,
    },
  ];
  context.integrationClientsFixture = clients;

  vm.runInContext(
    "adminState.integrationClients = integrationClientsFixture; renderIntegrationClients();",
    context,
  );

  const rows = elements.get("#integration-clients-tbody").innerHTML.match(/<tr>[\s\S]*?<\/tr>/g);
  const systemRow = rows.find((row) => row.includes("system-client"));
  const supplierRow = rows.find((row) => row.includes("supplier-client"));
  assert.match(systemRow, /data-rotate-integration="system-client"/);
  assert.match(systemRow, /data-revoke-integration="system-client"/);
  assert.doesNotMatch(supplierRow, /data-rotate-integration/);
  assert.match(supplierRow, /data-revoke-integration="supplier-client"/);
  assert.match(supplierRow, /SUPPLIER/);
  assert.match(supplierRow, /supplier-organization-id/);
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


test("operator account search resets pagination and stale responses cannot replace results", async () => {
  const pending = [];
  const requests = [];
  const api = (requestPath) => {
    requests.push(requestPath);
    const request = deferred();
    pending.push(request);
    return request.promise;
  };
  const harness = adminHarness(api, { includeOperator: true });
  vm.runInContext("bindAdminOperatorControls(); adminOperatorState.operators.page = 4;", harness.context);
  const search = harness.elements.get("#operators-search");

  search.value = "旧运营商";
  search.dispatchEvent({ type: "input" });
  assert.equal(vm.runInContext("adminOperatorState.operators.page", harness.context), 1);
  search.value = "新运营商";
  search.dispatchEvent({ type: "input" });

  assert.match(requests[0], /page=1/);
  assert.match(requests[0], /keyword=%E6%97%A7%E8%BF%90%E8%90%A5%E5%95%86/);
  assert.match(requests[1], /keyword=%E6%96%B0%E8%BF%90%E8%90%A5%E5%95%86/);
  pending[1].resolve({
    items: [{
      organization_id: "operator-new",
      organization_code: "OPR-NEW",
      organization_name: "新运营商",
      is_active: true,
      contact_name: "新联系人",
      contact_phone: "13900000000",
      contact_email: "new@example.com",
      company_name: "新运营公司",
      operator_type: "代运营",
      erp_name: "新 ERP",
      created_at: "2026-09-10T00:00:00Z",
    }],
    total: 1,
    page: 1,
    page_size: 50,
  });
  await Promise.resolve();
  await Promise.resolve();
  pending[0].resolve({
    items: [{
      organization_id: "operator-old",
      organization_code: "OPR-OLD",
      organization_name: "旧运营商",
      is_active: true,
      contact_name: "旧联系人",
      contact_phone: "13800000000",
      contact_email: "old@example.com",
      company_name: "旧运营公司",
      operator_type: "代运营",
      erp_name: "旧 ERP",
      created_at: "2026-09-09T00:00:00Z",
    }],
    total: 1,
    page: 1,
    page_size: 50,
  });
  await Promise.resolve();
  await Promise.resolve();

  const html = harness.elements.get("#operators-tbody").innerHTML;
  assert.match(html, /新运营商/);
  assert.doesNotMatch(html, /旧运营商/);
});


test("cooperation pagination changes do not alter application or account pagination", async () => {
  const requests = [];
  const api = async (requestPath) => {
    requests.push(requestPath);
    return { items: [], total: 0, page: 2, page_size: 200 };
  };
  const harness = adminHarness(api, { includeOperator: true });
  vm.runInContext(`
    adminOperatorState.applications.page = 3;
    adminOperatorState.applications.pageSize = 20;
    adminOperatorState.operators.page = 4;
    adminOperatorState.operators.pageSize = 100;
    adminOperatorState.cooperations.page = 2;
    adminOperatorState.cooperations.pageSize = 200;
  `, harness.context);

  await vm.runInContext("loadAdminOperatorCooperations()", harness.context);

  assert.equal(requests[0], "/api/admin/operator-cooperations?page=2&page_size=200");
  const pagination = harness.paginationCalls.find(
    (call) => call.container === "#admin-operator-cooperation-pagination",
  );
  assert.ok(pagination);
  pagination.options.onChange(3, 50);
  assert.deepEqual(
    JSON.parse(JSON.stringify(vm.runInContext(`({
      applications: {
        page: adminOperatorState.applications.page,
        pageSize: adminOperatorState.applications.pageSize,
      },
      operators: {
        page: adminOperatorState.operators.page,
        pageSize: adminOperatorState.operators.pageSize,
      },
      cooperations: {
        page: adminOperatorState.cooperations.page,
        pageSize: adminOperatorState.cooperations.pageSize,
      },
    })`, harness.context))),
    {
      applications: { page: 3, pageSize: 20 },
      operators: { page: 4, pageSize: 100 },
      cooperations: { page: 3, pageSize: 50 },
    },
  );
});


test("cooperation rows render response time and use a dash while pending", () => {
  const harness = adminHarness(async () => ({ items: [], total: 0, page: 1, page_size: 50 }), {
    includeOperator: true,
  });
  const data = {
    items: [
      {
        id: "accepted-cooperation",
        operator_id: "operator-a",
        supplier_id: "supplier-a",
        operator_name: "运营商 A",
        supplier_name: "供应商 A",
        status: "ACTIVE",
        binding: null,
        created_at: "2026-09-09T01:00:00Z",
        responded_at: "2026-09-10T02:00:00Z",
      },
      {
        id: "pending-cooperation",
        operator_id: "operator-b",
        supplier_id: "supplier-b",
        operator_name: "运营商 B",
        supplier_name: "供应商 B",
        status: "PENDING",
        binding: null,
        created_at: "2026-09-09T03:00:00Z",
        responded_at: null,
      },
    ],
    total: 2,
    page: 1,
    page_size: 50,
  };
  harness.context.cooperationRows = data;

  vm.runInContext("renderAdminOperatorCooperations(cooperationRows)", harness.context);

  const rows = harness.elements.get("#admin-operator-cooperations-tbody").innerHTML
    .match(/<tr>[\s\S]*?<\/tr>/g);
  assert.match(rows[0], /2026-09-10T02:00:00Z/);
  assert.equal((rows[1].match(/>—<\/td>/g) || []).length, 2);
});


test("reviewing an operator refreshes applications accounts and summary", async () => {
  const requests = [];
  const api = async (requestPath, options = {}) => {
    requests.push({ options, path: requestPath });
    if (options.method === "POST") {
      return { login_email: "operator@example.com", temporary_password: "temporary-secret" };
    }
    if (requestPath === "/api/admin/operator-summary") {
      return { pending_applications: 0, approved_applications: 1, active_operators: 1 };
    }
    return { items: [], total: 0, page: 1, page_size: 50 };
  };
  const harness = adminHarness(api, { includeOperator: true });

  await vm.runInContext('reviewOperator("application-id", "approve")', harness.context);

  assert.deepEqual(
    requests.map((request) => request.path),
    [
      "/api/admin/operator-applications/application-id/approve",
      "/api/admin/operator-applications?page=1&page_size=50",
      "/api/admin/operators?page=1&page_size=50",
      "/api/admin/operator-summary",
    ],
  );
  assert.equal(
    harness.elements.get("#operator-admin-metrics").innerHTML.match(/class="metric-card"/g).length,
    3,
  );
});


test("a stale operator summary response cannot replace the latest metrics", async () => {
  const firstSummary = deferred();
  const secondSummary = deferred();
  const summaries = [firstSummary, secondSummary];
  const harness = adminHarness((requestPath) => {
    assert.equal(requestPath, "/api/admin/operator-summary");
    return summaries.shift().promise;
  }, { includeOperator: true });

  const firstRequest = vm.runInContext("loadAdminOperatorSummary()", harness.context);
  const secondRequest = vm.runInContext("loadAdminOperatorSummary()", harness.context);
  secondSummary.resolve({
    pending_applications: 22,
    approved_applications: 23,
    active_operators: 24,
  });
  await secondRequest;
  firstSummary.resolve({
    pending_applications: 11,
    approved_applications: 12,
    active_operators: 13,
  });
  await firstRequest;

  const html = harness.elements.get("#operator-admin-metrics").innerHTML;
  assert.match(html, /metric-value">22</);
  assert.doesNotMatch(html, /metric-value">11</);
});


test("operator summary errors render an explicit metrics error state", async () => {
  const harness = adminHarness(async (requestPath) => {
    assert.equal(requestPath, "/api/admin/operator-summary");
    throw new Error("统计服务不可用");
  }, { includeOperator: true });

  await vm.runInContext("loadAdminOperatorSummary()", harness.context);

  const html = harness.elements.get("#operator-admin-metrics").innerHTML;
  assert.match(html, /运营概览加载失败/);
  assert.match(html, /统计服务不可用/);
});

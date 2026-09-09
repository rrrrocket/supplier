const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");


function loadMatrix({ documentOverrides = {}, fetchImpl = fetch, location = { replace() {} } } = {}) {
  const eventListeners = {};
  const document = {
    addEventListener(type, listener) { eventListeners[type] = listener; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    body: { dataset: {} },
    ...documentOverrides,
  };
  const window = { setTimeout, location };
  const context = {
    Date,
    Error,
    FormData,
    Intl,
    console,
    document,
    fetch: fetchImpl,
    setTimeout,
    window,
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "app", "web", "assets", "common.js"),
    "utf8",
  );
  vm.runInNewContext(source, context);
  return { Matrix: window.Matrix, document, eventListeners, window };
}


test("supplier session resolves to the supplier workspace", () => {
  const { Matrix } = loadMatrix();
  const view = Matrix.publicAuthView({
    id: "supplier-user-id",
    email: "supplier@example.com",
    name: "供应商联系人",
    role: "SUPPLIER",
    organization_id: "supplier-org-id",
    organization_type: "SUPPLIER",
    organization_name: "测试供应企业",
  });

  assert.deepEqual(JSON.parse(JSON.stringify(view)), {
    authenticated: true,
    identityLabel: "测试供应企业",
    workspaceHref: "/app",
    workspaceLabel: "进入工作台",
  });
});


test("operator session resolves to the operator workspace", () => {
  const { Matrix } = loadMatrix();
  const view = Matrix.publicAuthView({
    role: "OPERATOR",
    organization_type: "OPERATOR",
    organization_name: "测试运营团队",
  });

  assert.deepEqual(JSON.parse(JSON.stringify(view)), {
    authenticated: true,
    identityLabel: "测试运营团队",
    workspaceHref: "/operator",
    workspaceLabel: "进入工作台",
  });
  assert.equal(Matrix.userRoleLabel({ role: "OPERATOR" }), "运营商");
});


function jsonResponse(status, data) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: () => "application/json" },
    async json() { return data; },
  };
}


test("authenticated session replaces every guest action with workspace actions", async () => {
  const guestNodes = [{ hidden: false }, { hidden: false }];
  const memberNodes = [{ hidden: true }, { hidden: true }];
  const identityNodes = [{ textContent: "", href: "" }];
  const workspaceNodes = [{ textContent: "", href: "" }, { textContent: "", href: "" }];
  const selectorNodes = {
    "[data-auth-guest]": guestNodes,
    "[data-auth-member]": memberNodes,
    "[data-auth-identity]": identityNodes,
    "[data-auth-workspace]": workspaceNodes,
  };
  const user = {
    id: "supplier-user-id",
    email: "supplier@example.com",
    name: "供应商联系人",
    role: "SUPPLIER",
    organization_id: "supplier-org-id",
    organization_type: "SUPPLIER",
    organization_name: "测试供应企业",
  };
  const { Matrix } = loadMatrix({
    documentOverrides: {
      querySelectorAll(selector) { return selectorNodes[selector] || []; },
    },
    fetchImpl: async () => jsonResponse(200, user),
  });

  await Matrix.syncPublicAuth();

  assert.equal(guestNodes.every((node) => node.hidden), true);
  assert.equal(memberNodes.every((node) => !node.hidden), true);
  assert.equal(identityNodes[0].textContent, "测试供应企业");
  assert.equal(identityNodes[0].href, "/app");
  assert.equal(identityNodes[0].title, "测试供应企业");
  assert.equal(workspaceNodes.every((node) => node.textContent === "进入工作台"), true);
  assert.equal(workspaceNodes.every((node) => node.href === "/app"), true);
});


test("authenticated session reveals only the matching role-specific action", async () => {
  const roleNodes = [
    { hidden: true, dataset: { authRole: "SUPPLIER" } },
    { hidden: true, dataset: { authRole: "OPERATOR" } },
  ];
  const user = {
    role: "SUPPLIER",
    organization_type: "SUPPLIER",
    organization_name: "测试供应企业",
  };
  const { Matrix } = loadMatrix({
    documentOverrides: {
      querySelectorAll(selector) {
        if (selector === "[data-auth-role]") return roleNodes;
        return [];
      },
    },
    fetchImpl: async () => jsonResponse(200, user),
  });

  await Matrix.syncPublicAuth();

  assert.equal(roleNodes[0].hidden, false);
  assert.equal(roleNodes[1].hidden, true);
});


test("unauthenticated session restores guest actions without an uncaught error", async () => {
  const guestNodes = [{ hidden: true }, { hidden: true }];
  const memberNodes = [{ hidden: false }, { hidden: false }];
  const selectorNodes = {
    "[data-auth-guest]": guestNodes,
    "[data-auth-member]": memberNodes,
    "[data-auth-identity]": [],
    "[data-auth-workspace]": [],
  };
  const { Matrix } = loadMatrix({
    documentOverrides: {
      querySelectorAll(selector) { return selectorNodes[selector] || []; },
    },
    fetchImpl: async () => jsonResponse(401, { detail: "未登录或会话已过期" }),
  });

  const user = await Matrix.syncPublicAuth();

  assert.equal(user, null);
  assert.equal(guestNodes.every((node) => !node.hidden), true);
  assert.equal(memberNodes.every((node) => node.hidden), true);
});


test("guest-only page does not redirect when the session lookup fails", async () => {
  const redirects = [];
  const { Matrix } = loadMatrix({
    documentOverrides: { body: { dataset: { authRedirect: "workspace" } } },
    fetchImpl: async () => jsonResponse(401, { detail: "未登录或会话已过期" }),
    location: { replace(pathname) { redirects.push(pathname); } },
  });

  const user = await Matrix.syncPublicAuth();

  assert.equal(user, null);
  assert.deepEqual(redirects, []);
});


test("authenticated visitor on a guest-only page is redirected to the correct workspace", async () => {
  const redirects = [];
  const user = {
    id: "platform-user-id",
    email: "admin@example.com",
    name: "平台管理员",
    role: "PLATFORM_ADMIN",
    organization_id: "platform-org-id",
    organization_type: "PLATFORM",
    organization_name: "Matrix One Platform",
  };
  const { Matrix } = loadMatrix({
    documentOverrides: { body: { dataset: { authRedirect: "workspace" } } },
    fetchImpl: async () => jsonResponse(200, user),
    location: { replace(pathname) { redirects.push(pathname); } },
  });

  await Matrix.syncPublicAuth();

  assert.deepEqual(redirects, ["/admin"]);
});


test("supplier visitor on a guest-only page is redirected to the supplier workspace", async () => {
  const redirects = [];
  const user = {
    id: "supplier-user-id",
    email: "supplier@example.com",
    name: "供应商联系人",
    role: "SUPPLIER",
    organization_id: "supplier-org-id",
    organization_type: "SUPPLIER",
    organization_name: "测试供应企业",
  };
  const { Matrix } = loadMatrix({
    documentOverrides: { body: { dataset: { authRedirect: "workspace" } } },
    fetchImpl: async () => jsonResponse(200, user),
    location: { replace(pathname) { redirects.push(pathname); } },
  });

  await Matrix.syncPublicAuth();

  assert.deepEqual(redirects, ["/app"]);
});


test("unknown authenticated role is not treated as a supplier", () => {
  const { Matrix } = loadMatrix();
  const view = Matrix.publicAuthView({
    id: "unknown-user-id",
    email: "unknown@example.com",
    name: "未知账号",
    role: "UNKNOWN",
    organization_id: "unknown-org-id",
    organization_type: "SUPPLIER",
    organization_name: "未知组织",
  });

  assert.equal(view.authenticated, false);
  assert.equal(view.workspaceHref, "");
});


test("supplier role has the plain supplier label", () => {
  const { Matrix } = loadMatrix();

  assert.equal(Matrix.userRoleLabel?.({ role: "SUPPLIER" }), "供应商");
});


test("role and organization type must describe the same workspace", () => {
  const { Matrix } = loadMatrix();

  assert.equal(Matrix.publicAuthView({
    role: "PLATFORM_ADMIN",
    organization_type: "SUPPLIER",
    organization_name: "供应商组织",
  }).authenticated, false);
  assert.equal(Matrix.publicAuthView({
    role: "SUPPLIER",
    organization_type: "PLATFORM",
    organization_name: "平台组织",
  }).authenticated, false);
});


test("platform administrator session resolves to the management console", () => {
  const { Matrix } = loadMatrix();
  const view = Matrix.publicAuthView({
    id: "platform-user-id",
    email: "admin@example.com",
    name: "平台管理员",
    role: "PLATFORM_ADMIN",
    organization_id: "platform-org-id",
    organization_type: "PLATFORM",
    organization_name: "Matrix One Platform",
  });

  assert.deepEqual(JSON.parse(JSON.stringify(view)), {
    authenticated: true,
    identityLabel: "Matrix One Platform",
    workspaceHref: "/admin",
    workspaceLabel: "进入管理端",
  });
});


test("DOMContentLoaded automatically synchronizes pages with auth markers", async () => {
  let fetchCount = 0;
  const { eventListeners } = loadMatrix({
    documentOverrides: {
      querySelector(selector) {
        return selector === "[data-auth-guest], [data-auth-member]" ? {} : null;
      },
    },
    fetchImpl: async () => {
      fetchCount += 1;
      return jsonResponse(401, { detail: "请先登录" });
    },
  });

  eventListeners.DOMContentLoaded();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(fetchCount, 1);
});

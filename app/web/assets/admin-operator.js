const adminOperatorState = {
  applications: { page: 1, pageSize: 50, keyword: "", statusFilter: "", generation: 0 },
  operators: { page: 1, pageSize: 50, keyword: "", generation: 0 },
  cooperations: { page: 1, pageSize: 50, generation: 0 },
  summary: null,
};

function adminOperatorQuery(path, state, filters = {}) {
  const query = [`page=${state.page}`, `page_size=${state.pageSize}`];
  Object.entries(filters).forEach(([key, value]) => {
    if (value) query.push(`${key}=${encodeURIComponent(value)}`);
  });
  return `${path}?${query.join("&")}`;
}

function renderAdminOperatorPagination(containerSelector, state, total, reload) {
  MatrixPagination.render(document.querySelector(containerSelector), {
    total,
    page: state.page,
    pageSize: state.pageSize,
    onChange(nextPage, nextSize) {
      state.page = nextPage;
      state.pageSize = nextSize;
      reload();
    },
  });
}

function renderAdminOperatorSummary(summary) {
  adminOperatorState.summary = summary;
  document.querySelector("#operator-admin-metrics").innerHTML = [
    ["待审核申请", summary.pending_applications, "需要平台人工核验", "orange", "pending"],
    ["累计通过申请", summary.approved_applications, "已建立运营商组织", "green", "approved"],
    ["活跃运营商", summary.active_operators, "当前有效组织总量", "purple", "supplier"],
  ].map(([label, value, hint, tone, icon]) => `
    <article class="metric-card" data-tone="${tone}">
      <div class="metric-card-top"><span class="metric-label">${label}</span><span class="metric-icon">${metricIcon(icon)}</span></div>
      <div class="metric-value">${value}</div><div class="metric-hint">${hint}</div>
    </article>
  `).join("");
}

async function loadAdminOperatorSummary() {
  const summary = await Matrix.api("/api/admin/operator-summary");
  renderAdminOperatorSummary(summary);
}

function renderAdminOperatorApplications(data) {
  const state = adminOperatorState.applications;
  state.page = data.page;
  state.pageSize = data.page_size;
  document.querySelector("#operator-applications-count").textContent = `共 ${data.total} 条`;
  renderAdminOperatorPagination("#operator-application-pagination", state, data.total, loadAdminOperatorApplications);
  const tbody = document.querySelector("#operator-applications-tbody");
  tbody.innerHTML = data.items.length ? data.items.map((item) => `
    <tr>
      <td><strong>${Matrix.escapeHtml(item.application_no)}</strong></td>
      <td>${Matrix.escapeHtml(item.contact_name)}</td>
      <td><div>${Matrix.escapeHtml(item.phone)}</div><div class="table-secondary">${Matrix.escapeHtml(item.email)}</div></td>
      <td><div>${Matrix.escapeHtml(item.company_name || "—")}</div><div class="table-secondary">${Matrix.escapeHtml([item.operator_type, item.erp_name].filter(Boolean).join(" / ") || "类型与 ERP 未填写")}</div></td>
      <td>${Matrix.statusBadge(item.status)}</td>
      <td>${item.status === "PENDING" ? `<div class="row"><button class="btn btn-primary btn-sm" data-approve-operator="${item.id}">通过</button><button class="btn btn-danger btn-sm" data-reject-operator="${item.id}">驳回</button></div>` : ""}</td>
    </tr>
  `).join("") : '<tr><td colspan="6" class="table-empty"><strong>没有符合条件的运营商申请</strong>调整搜索或状态筛选后重试。</td></tr>';
  tbody.querySelectorAll("[data-approve-operator]").forEach((button) => {
    button.onclick = () => reviewOperator(button.dataset.approveOperator, "approve");
  });
  tbody.querySelectorAll("[data-reject-operator]").forEach((button) => {
    button.onclick = () => reviewOperator(button.dataset.rejectOperator, "reject");
  });
}

async function loadAdminOperatorApplications() {
  const state = adminOperatorState.applications;
  const generation = state.generation + 1;
  state.generation = generation;
  const path = adminOperatorQuery("/api/admin/operator-applications", state, {
    keyword: state.keyword,
    status_filter: state.statusFilter,
  });
  try {
    const data = await Matrix.api(path);
    if (generation !== state.generation) return;
    renderAdminOperatorApplications(data);
  } catch (error) {
    if (generation !== state.generation) return;
    document.querySelector("#operator-applications-tbody").innerHTML = `<tr><td colspan="6" class="table-empty table-error"><strong>运营商申请加载失败</strong>${Matrix.escapeHtml(error.message)}</td></tr>`;
  }
}

function renderAdminOperators(data) {
  const state = adminOperatorState.operators;
  state.page = data.page;
  state.pageSize = data.page_size;
  document.querySelector("#operators-count").textContent = `共 ${data.total} 家`;
  renderAdminOperatorPagination("#operator-account-pagination", state, data.total, loadAdminOperators);
  const tbody = document.querySelector("#operators-tbody");
  tbody.innerHTML = data.items.length ? data.items.map((item) => `
    <tr>
      <td><strong>${Matrix.escapeHtml(item.organization_name)}</strong><div class="table-secondary">${Matrix.escapeHtml(item.organization_code)}</div></td>
      <td>${Matrix.escapeHtml(item.contact_name)}</td>
      <td><div>${Matrix.escapeHtml(item.contact_phone)}</div><div class="table-secondary">${Matrix.escapeHtml(item.contact_email)}</div></td>
      <td>${Matrix.escapeHtml([item.operator_type, item.erp_name].filter(Boolean).join(" / ") || "—")}</td>
      <td>${Matrix.statusBadge(item.is_active ? "ACTIVE" : "INACTIVE")}</td>
    </tr>
  `).join("") : '<tr><td colspan="5" class="table-empty"><strong>没有符合条件的运营商</strong>调整搜索后重试。</td></tr>';
}

async function loadAdminOperators() {
  const state = adminOperatorState.operators;
  const generation = state.generation + 1;
  state.generation = generation;
  const path = adminOperatorQuery("/api/admin/operators", state, { keyword: state.keyword });
  try {
    const data = await Matrix.api(path);
    if (generation !== state.generation) return;
    renderAdminOperators(data);
  } catch (error) {
    if (generation !== state.generation) return;
    document.querySelector("#operators-tbody").innerHTML = `<tr><td colspan="5" class="table-empty table-error"><strong>运营商列表加载失败</strong>${Matrix.escapeHtml(error.message)}</td></tr>`;
  }
}

function renderAdminOperatorCooperations(data) {
  const state = adminOperatorState.cooperations;
  state.page = data.page;
  state.pageSize = data.page_size;
  renderAdminOperatorPagination("#admin-operator-cooperation-pagination", state, data.total, loadAdminOperatorCooperations);
  const tbody = document.querySelector("#admin-operator-cooperations-tbody");
  tbody.innerHTML = data.items.length ? data.items.map((item) => `
    <tr>
      <td>${Matrix.escapeHtml(item.operator_name || item.operator_id)}</td>
      <td>${Matrix.escapeHtml(item.supplier_name || item.supplier_id)}</td>
      <td>${Matrix.statusBadge(item.status)}</td>
      <td>${item.binding ? `<code>${Matrix.escapeHtml(item.binding.id)}</code> ${Matrix.statusBadge(item.binding.status)}` : "—"}</td>
      <td>${Matrix.formatDate(item.created_at, true)}</td>
    </tr>
  `).join("") : '<tr><td colspan="5" class="table-empty">暂无合作记录</td></tr>';
}

async function loadAdminOperatorCooperations() {
  const state = adminOperatorState.cooperations;
  const generation = state.generation + 1;
  state.generation = generation;
  const path = adminOperatorQuery("/api/admin/operator-cooperations", state);
  try {
    const data = await Matrix.api(path);
    if (generation !== state.generation) return;
    renderAdminOperatorCooperations(data);
  } catch (error) {
    if (generation !== state.generation) return;
    document.querySelector("#admin-operator-cooperations-tbody").innerHTML = `<tr><td colspan="5" class="table-empty table-error"><strong>合作记录加载失败</strong>${Matrix.escapeHtml(error.message)}</td></tr>`;
  }
}

async function reviewOperator(id, action) {
  const notes = prompt(action === "approve" ? "确认通过，可填写审核备注：" : "请填写驳回原因：", "");
  if (notes === null) return;
  const result = await Matrix.api(`/api/admin/operator-applications/${id}/${action}`, {
    method: "POST",
    body: { notes },
  });
  if (action === "approve") {
    alert(`账号已创建。请立即安全交付：\n登录邮箱：${result.login_email}\n临时密码：${result.temporary_password}`);
  }
  Matrix.toast("审核完成", "运营商申请状态已更新。", "success");
  await Promise.all([loadAdminOperatorApplications(), loadAdminOperators(), loadAdminOperatorSummary()]);
}

function bindAdminOperatorControls() {
  document.querySelector("#refresh-operator-applications")?.addEventListener("click", () => {
    loadAdminOperatorApplications();
    loadAdminOperatorSummary();
  });
  document.querySelector("#refresh-operators")?.addEventListener("click", loadAdminOperators);
  const applicationSearch = document.querySelector("#operator-applications-search");
  applicationSearch?.addEventListener("input", () => {
    adminOperatorState.applications.keyword = applicationSearch.value;
    adminOperatorState.applications.page = 1;
    loadAdminOperatorApplications();
  });
  const applicationStatus = document.querySelector("#operator-applications-status");
  applicationStatus?.addEventListener("change", () => {
    adminOperatorState.applications.statusFilter = applicationStatus.value;
    adminOperatorState.applications.page = 1;
    loadAdminOperatorApplications();
  });
  const operatorSearch = document.querySelector("#operators-search");
  operatorSearch?.addEventListener("input", () => {
    adminOperatorState.operators.keyword = operatorSearch.value;
    adminOperatorState.operators.page = 1;
    loadAdminOperators();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bindAdminOperatorControls();
  loadAdminOperatorApplications();
  loadAdminOperators();
  loadAdminOperatorCooperations();
  loadAdminOperatorSummary();
});

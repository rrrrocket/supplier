const adminState = {
  user: null,
  applications: [],
  suppliers: [],
  selectedApplication: null,
};

const adminRoutes = {
  applications: ["入驻申请", "中国供应网络 / 平台管理 / 入驻申请"],
  suppliers: ["入驻供应商", "中国供应网络 / 平台管理 / 供应商"],
  system: ["系统架构", "中国供应网络 / 平台管理 / 系统架构"],
};

function metricIcon(type) {
  const icons = {
    pending: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    approved: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="m5 12 4 4L19 6"/><circle cx="12" cy="12" r="9"/></svg>',
    supplier: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 20V8l8-4 8 4v12"/><path d="M8 20v-6h8v6"/></svg>',
  };
  return icons[type] || icons.supplier;
}

function routeTo(route, updateHash = true) {
  const target = adminRoutes[route] ? route : "applications";
  document.querySelectorAll(".nav-item[data-route]").forEach((item) => {
    item.classList.toggle("active", item.dataset.route === target);
  });
  document.querySelectorAll(".app-view").forEach((view) => {
    view.classList.toggle("active", view.dataset.view === target);
  });
  document.querySelector("#page-title").textContent = adminRoutes[target][0];
  document.querySelector("#breadcrumb").textContent = adminRoutes[target][1];
  document.querySelector("#sidebar").classList.remove("open");
  if (updateHash && window.location.hash !== `#${target}`) window.location.hash = target;
}

function renderAdminMetrics() {
  const pending = adminState.applications.filter((item) => item.status === "PENDING").length;
  const approved = adminState.applications.filter((item) => item.status === "APPROVED").length;
  const suppliers = adminState.suppliers.length;
  document.querySelector("#pending-nav-badge").textContent = String(pending);
  document.querySelector("#admin-metrics").innerHTML = [
    ["待审核申请", pending, "需要平台人工核验", "orange", "pending"],
    ["累计通过申请", approved, "已建立供应商组织", "green", "approved"],
    ["入驻供应商", suppliers, "当前有效组织总量", "purple", "supplier"],
  ].map(([label, value, hint, tone, icon]) => `
    <article class="metric-card" data-tone="${tone}">
      <div class="metric-card-top"><span class="metric-label">${label}</span><span class="metric-icon">${metricIcon(icon)}</span></div>
      <div class="metric-value">${value}</div><div class="metric-hint">${hint}</div>
    </article>
  `).join("");
}

function applicationSearchText(item) {
  return [item.application_no, item.company_name, item.company_type, item.province, item.city, item.contact_name, item.phone, item.email, ...(item.categories || []), ...(item.cooperation_modes || [])].join(" ").toLowerCase();
}

function renderApplications() {
  const query = document.querySelector("#applications-search").value.trim().toLowerCase();
  const status = document.querySelector("#applications-status").value;
  const rows = adminState.applications.filter((item) => {
    return (!query || applicationSearchText(item).includes(query)) && (!status || item.status === status);
  });
  const tbody = document.querySelector("#applications-tbody");
  document.querySelector("#applications-count").textContent = `显示 ${rows.length} 条 / 共 ${adminState.applications.length} 条`;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty"><strong>没有符合条件的申请</strong>调整搜索或状态筛选后重试。</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((item) => `
    <tr>
      <td><div class="application-company"><strong>${Matrix.escapeHtml(item.company_name)}</strong><span>${Matrix.escapeHtml(item.application_no)}</span></div></td>
      <td><div class="table-primary">${Matrix.escapeHtml(item.company_type)}</div><div class="table-secondary">${Matrix.escapeHtml(item.province)} · ${Matrix.escapeHtml(item.city)}</div></td>
      <td><div class="table-primary">${Matrix.escapeHtml(item.contact_name)}</div><div class="table-secondary">${Matrix.escapeHtml(item.email)}</div></td>
      <td><div class="tag-list">${[...(item.categories || []), ...(item.cooperation_modes || [])].slice(0, 5).map((tag) => `<span class="tag">${Matrix.escapeHtml(tag)}</span>`).join("") || '<span class="muted">—</span>'}</div></td>
      <td>${Matrix.formatDate(item.created_at, true)}</td>
      <td>${Matrix.statusBadge(item.status)}</td>
      <td class="text-right"><button class="btn btn-secondary btn-sm" type="button" data-review-id="${item.id}">${item.status === "PENDING" ? "审核" : "查看"}</button></td>
    </tr>
  `).join("");
  tbody.querySelectorAll("[data-review-id]").forEach((button) => {
    button.addEventListener("click", () => openApplicationReview(button.dataset.reviewId));
  });
}

function supplierSearchText(item) {
  return [item.organization_code, item.organization_name, item.legal_name, item.contact_name, item.contact_email].join(" ").toLowerCase();
}

function renderSuppliers() {
  const query = document.querySelector("#suppliers-search").value.trim().toLowerCase();
  const rows = adminState.suppliers.filter((item) => !query || supplierSearchText(item).includes(query));
  const tbody = document.querySelector("#suppliers-tbody");
  document.querySelector("#suppliers-count").textContent = `显示 ${rows.length} 家 / 共 ${adminState.suppliers.length} 家`;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty"><strong>还没有符合条件的供应商</strong>审核通过申请后，组织会显示在这里。</td></tr>';
    return;
  }
  tbody.innerHTML = rows.map((item) => `
    <tr>
      <td><div class="table-primary">${Matrix.escapeHtml(item.organization_name)}</div><div class="table-secondary">${Matrix.escapeHtml(item.organization_code)} · ${Matrix.escapeHtml(item.legal_name)}</div></td>
      <td><div class="table-primary">${Matrix.escapeHtml(item.contact_name || "—")}</div><div class="table-secondary">${Matrix.escapeHtml(item.contact_email || "—")}</div></td>
      <td><div class="row"><strong>${item.profile_completion}%</strong><span class="muted">${item.profile_completion >= 80 ? "可进入合作评估" : "待补充资料"}</span></div></td>
      <td><strong>${item.product_count}</strong></td>
      <td><strong>${item.active_offer_count}</strong></td>
      <td>${Matrix.statusBadge(item.status)}</td>
      <td>${Matrix.formatDate(item.created_at)}</td>
    </tr>
  `).join("");
}

function detailItem(label, value, full = false) {
  return `<div class="detail-item${full ? " full" : ""}"><span>${Matrix.escapeHtml(label)}</span><strong>${value || "—"}</strong></div>`;
}

function boolLabel(value) {
  return value ? '<span class="text-success">支持</span>' : '<span class="muted">暂不支持</span>';
}

function openApplicationReview(id) {
  const item = adminState.applications.find((application) => application.id === id);
  if (!item) return;
  adminState.selectedApplication = item;
  document.querySelector("#review-dialog-title").textContent = item.status === "PENDING" ? "审核供应商申请" : "查看供应商申请";
  document.querySelector("#review-dialog-subtitle").textContent = `${item.application_no} · 提交于 ${Matrix.formatDate(item.created_at, true)}`;
  document.querySelector("#application-detail").innerHTML = [
    detailItem("企业名称", Matrix.escapeHtml(item.company_name)),
    detailItem("企业类型", Matrix.escapeHtml(item.company_type)),
    detailItem("统一社会信用代码", Matrix.escapeHtml(item.unified_social_credit_code || "未填写")),
    detailItem("所在地区", `${Matrix.escapeHtml(item.province)} · ${Matrix.escapeHtml(item.city)}`),
    detailItem("联系人", `${Matrix.escapeHtml(item.contact_name)} · ${Matrix.escapeHtml(item.phone)}`),
    detailItem("联系邮箱", Matrix.escapeHtml(item.email)),
    detailItem("产品类目", (item.categories || []).map((tag) => `<span class="tag">${Matrix.escapeHtml(tag)}</span>`).join(" ") || "—", true),
    detailItem("合作模式", (item.cooperation_modes || []).map((tag) => `<span class="tag">${Matrix.escapeHtml(tag)}</span>`).join(" ") || "—", true),
    detailItem("供货能力", `一件代发：${boolLabel(item.supports_dropshipping)}　OEM：${boolLabel(item.supports_oem)}　出口经验：${boolLabel(item.has_export_experience)}`, true),
    detailItem("年营收区间", Matrix.escapeHtml(item.annual_revenue_range || "未填写")),
    detailItem("当前状态", Matrix.statusBadge(item.status)),
    detailItem("申请说明", Matrix.escapeHtml(item.message || "未填写"), true),
    ...(item.review_notes ? [detailItem("审核备注", Matrix.escapeHtml(item.review_notes), true)] : []),
  ].join("");
  document.querySelector("#review-notes").value = item.review_notes || "";
  document.querySelector("#approval-credentials").classList.add("hidden");
  document.querySelector("#approval-credentials").innerHTML = "";
  const isPending = item.status === "PENDING";
  document.querySelector("#review-notes-group").classList.toggle("hidden", !isPending);
  document.querySelector("#approve-application").classList.toggle("hidden", !isPending);
  document.querySelector("#reject-application").classList.toggle("hidden", !isPending);
  document.querySelector("#application-review-dialog").showModal();
}

async function approveSelectedApplication() {
  const item = adminState.selectedApplication;
  if (!item) return;
  const button = document.querySelector("#approve-application");
  button.disabled = true;
  button.textContent = "正在创建…";
  try {
    const result = await Matrix.api(`/api/admin/applications/${item.id}/approve`, {
      method: "POST",
      body: { notes: document.querySelector("#review-notes").value.trim() || null },
    });
    const credentialBox = document.querySelector("#approval-credentials");
    credentialBox.classList.remove("hidden");
    credentialBox.innerHTML = `
      <h3>供应商组织与账号已创建</h3>
      <p>临时密码不会再次返回。请复制后通过安全渠道发送给供应商；生产环境正式开放前需接入邀请与密码重置机制。</p>
      <div class="credential-row"><span>组织编码</span><code>${Matrix.escapeHtml(result.organization_code)}</code></div>
      <div class="credential-row"><span>登录邮箱</span><code>${Matrix.escapeHtml(result.login_email)}</code></div>
      <div class="credential-row"><span>临时密码</span><code id="temporary-password">${Matrix.escapeHtml(result.temporary_password)}</code></div>
      <button id="copy-credentials" class="btn btn-secondary btn-sm" type="button" style="margin-top:14px">复制账号信息</button>
    `;
    document.querySelector("#copy-credentials").addEventListener("click", async () => {
      const text = `Matrix One 供应商工作台\n登录地址：${window.location.origin}/login\n邮箱：${result.login_email}\n临时密码：${result.temporary_password}`;
      try {
        await navigator.clipboard.writeText(text);
        Matrix.toast("已复制", "账号信息已复制到剪贴板。", "success");
      } catch {
        Matrix.toast("复制失败", "请手动选择并复制账号信息。", "error");
      }
    });
    document.querySelector("#approve-application").classList.add("hidden");
    document.querySelector("#reject-application").classList.add("hidden");
    document.querySelector("#review-notes-group").classList.add("hidden");
    Matrix.toast("审核通过", "组织、供应商档案和管理员账号已建立。", "success");
    await Promise.all([loadApplications(), loadSuppliers()]);
  } catch (error) {
    Matrix.toast("审核失败", error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "通过并创建账号";
  }
}

async function rejectSelectedApplication() {
  const item = adminState.selectedApplication;
  if (!item) return;
  const notes = document.querySelector("#review-notes").value.trim();
  if (!notes) {
    Matrix.toast("请填写驳回理由", "明确原因有助于后续补充材料和再次审核。", "error");
    return;
  }
  if (!window.confirm(`确定驳回“${item.company_name}”的入驻申请？`)) return;
  const button = document.querySelector("#reject-application");
  button.disabled = true;
  try {
    await Matrix.api(`/api/admin/applications/${item.id}/reject`, { method: "POST", body: { notes } });
    document.querySelector("#application-review-dialog").close();
    Matrix.toast("申请已驳回", "驳回原因已保存到审核记录。", "success");
    await loadApplications();
  } catch (error) {
    Matrix.toast("操作失败", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function loadApplications() {
  try {
    adminState.applications = await Matrix.api("/api/admin/applications");
    renderApplications();
    renderAdminMetrics();
  } catch (error) {
    document.querySelector("#applications-tbody").innerHTML = `<tr><td colspan="7" class="table-empty"><strong>申请数据加载失败</strong>${Matrix.escapeHtml(error.message)}</td></tr>`;
  }
}

async function loadSuppliers() {
  try {
    adminState.suppliers = await Matrix.api("/api/admin/suppliers");
    renderSuppliers();
    renderAdminMetrics();
  } catch (error) {
    document.querySelector("#suppliers-tbody").innerHTML = `<tr><td colspan="7" class="table-empty"><strong>供应商数据加载失败</strong>${Matrix.escapeHtml(error.message)}</td></tr>`;
  }
}

async function logout() {
  try {
    await Matrix.api("/api/auth/logout", { method: "POST" });
  } finally {
    window.location.href = "/login";
  }
}

async function bootAdmin() {
  try {
    adminState.user = await Matrix.api("/api/auth/me");
    if (adminState.user.role !== "PLATFORM_ADMIN") {
      window.location.href = "/app";
      return;
    }
  } catch {
    window.location.href = "/login";
    return;
  }

  document.querySelector("#user-name").textContent = adminState.user.name;
  document.querySelectorAll(".nav-item[data-route]").forEach((item) => item.addEventListener("click", () => routeTo(item.dataset.route)));
  document.querySelector("#mobile-menu").addEventListener("click", () => document.querySelector("#sidebar").classList.toggle("open"));
  document.querySelector("#logout-button").addEventListener("click", logout);
  document.querySelector("#refresh-applications").addEventListener("click", loadApplications);
  document.querySelector("#refresh-suppliers").addEventListener("click", loadSuppliers);
  document.querySelector("#applications-search").addEventListener("input", renderApplications);
  document.querySelector("#applications-status").addEventListener("change", renderApplications);
  document.querySelector("#suppliers-search").addEventListener("input", renderSuppliers);
  document.querySelectorAll("[data-close-review]").forEach((button) => button.addEventListener("click", () => document.querySelector("#application-review-dialog").close()));
  document.querySelector("#approve-application").addEventListener("click", approveSelectedApplication);
  document.querySelector("#reject-application").addEventListener("click", rejectSelectedApplication);
  window.addEventListener("hashchange", () => routeTo(window.location.hash.slice(1), false));

  routeTo(window.location.hash.slice(1) || "applications", false);
  await Promise.all([loadApplications(), loadSuppliers()]);
}

document.addEventListener("DOMContentLoaded", bootAdmin);

const adminState = {
  user: null,
  applications: [],
  suppliers: [],
  brands: [],
  brandCooperations: [],
  integrationClients: [],
  applicationPage: 1,
  applicationPageSize: 50,
  supplierPage: 1,
  supplierPageSize: 50,
  integrationPage: 1,
  integrationPageSize: 50,
  selectedApplication: null,
  selectedSupplier: null,
  brandCooperationGeneration: 0,
  loadedBrandCooperationSupplierId: null,
};

function paginateAdmin(kind, rows) {
  const pageKey = `${kind}Page`;
  const sizeKey = `${kind}PageSize`;
  const pageSize = adminState[sizeKey];
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  adminState[pageKey] = Math.min(Math.max(1, adminState[pageKey]), pages);
  const page = adminState[pageKey];
  const start = rows.length ? (page - 1) * pageSize + 1 : 0;
  const end = rows.length ? Math.min(page * pageSize, rows.length) : 0;
  const container = document.querySelector(`#${kind}-pagination`);
  if (window.MatrixPagination && typeof container?.querySelector === "function") {
    window.MatrixPagination.render(container, { total: rows.length, page, pageSize, onChange(nextPage, nextSize) { adminState[pageKey] = nextPage; adminState[sizeKey] = nextSize; ({ application: renderApplications, supplier: renderSuppliers, integration: renderIntegrationClients })[kind](); } });
  }
  return rows.slice(start ? start - 1 : 0, end);
}

const cooperationModeLabels = {
  SELF_PURCHASE: "模式 A · 自营采购",
  JOINT_OPERATION: "模式 B · 联营",
  B2B: "模式 C · ToB 合作",
};

const adminRoutes = {
  applications: ["供应商入驻申请", "供应网络 / 供应商管理 / 入驻申请"],
  suppliers: ["供应商列表", "供应网络 / 供应商管理 / 供应商列表"],
  "operator-applications": ["运营商入驻申请", "供应网络 / 运营商管理 / 入驻申请"],
  operators: ["运营商列表", "供应网络 / 运营商管理 / 运营商列表"],
  "operator-cooperations": ["合作记录", "供应网络 / 合作管理 / 合作记录"],
  integrations: ["平台 API 凭证", "供应网络 / 平台管理 / 平台 API 凭证"],
  system: ["平台能力", "供应网络 / 平台管理 / 平台能力"],
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
  const visibleRows = paginateAdmin("application", rows);
  const tbody = document.querySelector("#applications-tbody");
  document.querySelector("#applications-count").textContent = `显示 ${rows.length} 条 / 共 ${adminState.applications.length} 条`;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty"><strong>没有符合条件的申请</strong>调整搜索或状态筛选后重试。</td></tr>';
    return;
  }
  tbody.innerHTML = visibleRows.map((item) => `
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
  const visibleRows = paginateAdmin("supplier", rows);
  const tbody = document.querySelector("#suppliers-tbody");
  document.querySelector("#suppliers-count").textContent = `显示 ${rows.length} 家 / 共 ${adminState.suppliers.length} 家`;
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="8" class="table-empty"><strong>还没有符合条件的供应商</strong>审核通过申请后，组织会显示在这里。</td></tr>';
    return;
  }
  tbody.innerHTML = visibleRows.map((item) => `
    <tr>
      <td><div class="table-primary">${Matrix.escapeHtml(item.organization_name)}</div><div class="table-secondary">${Matrix.escapeHtml(item.organization_code)} · ${Matrix.escapeHtml(item.legal_name)}</div></td>
      <td><div class="table-primary">${Matrix.escapeHtml(item.contact_name || "—")}</div><div class="table-secondary">${Matrix.escapeHtml(item.contact_email || "—")}</div></td>
      <td><div class="row"><strong>${item.profile_completion}%</strong><span class="muted">${item.profile_completion >= 80 ? "可进入合作评估" : "待补充资料"}</span></div></td>
      <td><strong>${item.product_count}</strong></td>
      <td><strong>${item.active_offer_count}</strong></td>
      <td>${Matrix.statusBadge(item.status)}</td>
      <td>${Matrix.formatDate(item.created_at)}</td>
      <td class="text-right"><button class="btn btn-secondary btn-sm" type="button" data-brand-cooperation-id="${item.organization_id}">品牌合作</button></td>
    </tr>
  `).join("");
  tbody.querySelectorAll("[data-brand-cooperation-id]").forEach((button) => {
    button.addEventListener("click", () => openBrandCooperation(button.dataset.brandCooperationId));
  });
}

function renderBrandCooperations() {
  const container = document.querySelector("#brand-cooperation-list");
  if (!adminState.brandCooperations.length) {
    container.innerHTML = '<div class="cooperation-empty">尚未配置品牌合作。请在下方选择品牌和模式。</div>';
    return;
  }
  container.innerHTML = adminState.brandCooperations.map((item) => `
    <div class="cooperation-item">
      <div><strong>${Matrix.escapeHtml(item.brand_name)}</strong><span>${Matrix.escapeHtml(cooperationModeLabels[item.commercial_mode] || item.commercial_mode)}</span></div>
      ${Matrix.statusBadge(item.status)}
    </div>
  `).join("");
}

function renderIntegrationClients() {
  const tbody = document.querySelector("#integration-clients-tbody");
  const visibleRows = paginateAdmin("integration", adminState.integrationClients);
  document.querySelector("#integration-clients-count").textContent = `共 ${adminState.integrationClients.length} 个`;
  if (!adminState.integrationClients.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty"><strong>还没有集成调用方</strong>创建后，明文令牌只会显示一次。</td></tr>';
    return;
  }
  tbody.innerHTML = visibleRows.map((item) => {
    const expired = item.expires_at && new Date(item.expires_at).getTime() <= Date.now();
    const usable = item.is_active && !expired;
    const canRotate = item.client_type === "SYSTEM" && usable;
    const actions = [
      canRotate ? `<button class="btn btn-secondary btn-sm" type="button" data-rotate-integration="${item.id}">轮换</button>` : "",
      item.is_active ? `<button class="btn btn-danger btn-sm" type="button" data-revoke-integration="${item.id}">撤销</button>` : "",
    ].join("");
    return `
    <tr>
      <td><div class="table-primary">${Matrix.escapeHtml(item.name)}</div><div class="table-secondary">${Matrix.escapeHtml(item.client_type)}${item.owner_organization_id ? ` · ${Matrix.escapeHtml(item.owner_organization_id)}` : " · 平台级"}</div></td>
      <td><code>${Matrix.escapeHtml(item.token_prefix)}</code></td>
      <td><div class="tag-list">${(item.scopes || []).map((scope) => `<span class="tag">${Matrix.escapeHtml(scope)}</span>`).join("")}</div></td>
      <td>${item.expires_at ? Matrix.formatDate(item.expires_at, true) : "永不过期"}</td>
      <td>${item.last_used_at ? Matrix.formatDate(item.last_used_at, true) : "尚未使用"}</td>
      <td>${Matrix.statusBadge(expired ? "EXPIRED" : (item.is_active ? "ACTIVE" : "INACTIVE"))}</td>
      <td class="text-right"><div class="row">${actions || "—"}</div></td>
    </tr>
  `;
  }).join("");
  tbody.querySelectorAll("[data-rotate-integration]").forEach((button) => {
    button.addEventListener("click", () => rotateIntegrationClient(button.dataset.rotateIntegration));
  });
  tbody.querySelectorAll("[data-revoke-integration]").forEach((button) => {
    button.addEventListener("click", () => revokeIntegrationClient(button.dataset.revokeIntegration));
  });
}

async function loadIntegrationClients() {
  try {
    adminState.integrationClients = await Matrix.api("/api/admin/integration-clients");
    renderIntegrationClients();
  } catch (error) {
    document.querySelector("#integration-clients-tbody").innerHTML = `<tr><td colspan="7" class="table-empty"><strong>平台 API 凭证加载失败</strong>${Matrix.escapeHtml(error.message)}</td></tr>`;
  }
}

function showIntegrationToken(result) {
  document.querySelector("#integration-token-dialog-subtitle").textContent = `${result.name} · ${result.token_prefix} · 关闭后将无法再次查看`;
  document.querySelector("#integration-token-value").textContent = result.token;
  document.querySelector("#copy-integration-token").onclick = async () => {
    try {
      await navigator.clipboard.writeText(result.token);
      Matrix.toast("已复制", "令牌已复制到剪贴板。", "success");
    } catch {
      Matrix.toast("复制失败", "请手动选择并复制令牌。", "error");
    }
  };
  document.querySelector("#integration-token-dialog").showModal();
}

function clearIntegrationToken() {
  document.querySelector("#integration-token-value").textContent = "";
  document.querySelector("#copy-integration-token").onclick = null;
}

function closeIntegrationToken() {
  const dialog = document.querySelector("#integration-token-dialog");
  clearIntegrationToken();
  if (dialog.open) dialog.close();
}

function bindIntegrationTokenDialog() {
  const dialog = document.querySelector("#integration-token-dialog");
  dialog.addEventListener("cancel", clearIntegrationToken);
  dialog.addEventListener("close", clearIntegrationToken);
  document.querySelectorAll("[data-close-integration-token]").forEach((button) => {
    button.addEventListener("click", closeIntegrationToken);
  });
}

async function createIntegrationClient(event) {
  event.preventDefault();
  const nameInput = document.querySelector("#integration-client-name");
  const expiresInput = document.querySelector("#integration-client-expires-at");
  const scopeInputs = [...document.querySelector("#integration-client-scopes").querySelectorAll("input:checked")];
  if (!scopeInputs.length) {
    Matrix.toast("请选择权限范围", "调用方至少需要一个读取权限。", "error");
    return;
  }
  const button = document.querySelector("#create-integration-client");
  button.disabled = true;
  try {
    const result = await Matrix.api("/api/admin/integration-clients", {
      method: "POST",
      body: {
        name: nameInput.value.trim(),
        scopes: scopeInputs.map((input) => input.value),
        expires_at: expiresInput.value ? new Date(expiresInput.value).toISOString() : null,
      },
    });
    showIntegrationToken(result);
    nameInput.value = "";
    expiresInput.value = "";
    scopeInputs.forEach((input) => { input.checked = false; });
    await loadIntegrationClients();
  } catch (error) {
    Matrix.toast("创建失败", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function rotateIntegrationClient(clientId) {
  if (!window.confirm("轮换后旧令牌会立即失效，确定继续？")) return;
  try {
    const result = await Matrix.api(`/api/admin/integration-clients/${clientId}/rotate`, { method: "POST" });
    showIntegrationToken(result);
    await loadIntegrationClients();
  } catch (error) {
    Matrix.toast("轮换失败", error.message, "error");
  }
}

async function revokeIntegrationClient(clientId) {
  if (!window.confirm("撤销后该调用方将立即无法访问集成 API，确定继续？")) return;
  try {
    await Matrix.api(`/api/admin/integration-clients/${clientId}/revoke`, { method: "POST" });
    await loadIntegrationClients();
    Matrix.toast("凭证已撤销", "该令牌已立即失效。", "success");
  } catch (error) {
    Matrix.toast("撤销失败", error.message, "error");
  }
}

function syncBrandCooperationForm() {
  const brandId = document.querySelector("#brand-cooperation-brand").value;
  const current = adminState.brandCooperations.find((item) => item.brand_id === brandId);
  document.querySelector("#brand-cooperation-mode").value = current?.commercial_mode || "SELF_PURCHASE";
  document.querySelector("#brand-cooperation-current").innerHTML = current
    ? `当前合作：<strong>${Matrix.escapeHtml(cooperationModeLabels[current.commercial_mode] || current.commercial_mode)}</strong> ${Matrix.statusBadge(current.status)}`
    : "当前合作：尚未配置";
}

async function loadBrandCooperations(supplierId, generation) {
  const cooperations = await Matrix.api(`/api/admin/suppliers/${supplierId}/brand-cooperations`);
  if (
    generation !== adminState.brandCooperationGeneration
    || adminState.selectedSupplier?.organization_id !== supplierId
    || adminState.loadedBrandCooperationSupplierId !== supplierId
  ) return;
  adminState.brandCooperations = cooperations;
  renderBrandCooperations();
  syncBrandCooperationForm();
}

async function openBrandCooperation(supplierId) {
  const supplier = adminState.suppliers.find((item) => item.organization_id === supplierId);
  if (!supplier) return;
  const generation = adminState.brandCooperationGeneration + 1;
  adminState.brandCooperationGeneration = generation;
  adminState.selectedSupplier = supplier;
  adminState.loadedBrandCooperationSupplierId = null;
  adminState.brandCooperations = [];
  document.querySelector("#brand-cooperation-brand").innerHTML = "";
  document.querySelector("#save-brand-cooperation").disabled = true;
  document.querySelector("#brand-cooperation-dialog-title").textContent = "管理品牌合作";
  document.querySelector("#brand-cooperation-dialog-subtitle").textContent = `${supplier.organization_name} · ${supplier.organization_code}`;
  document.querySelector("#brand-cooperation-list").innerHTML = '<div class="cooperation-empty">正在加载品牌合作…</div>';
  document.querySelector("#brand-cooperation-dialog").showModal();
  try {
    const [brands, cooperations] = await Promise.all([
      Matrix.api("/api/admin/brands"),
      Matrix.api(`/api/admin/suppliers/${supplier.organization_id}/brand-cooperations`),
    ]);
    if (
      generation !== adminState.brandCooperationGeneration
      || adminState.selectedSupplier?.organization_id !== supplier.organization_id
    ) return;
    adminState.brands = brands;
    adminState.brandCooperations = cooperations;
    adminState.loadedBrandCooperationSupplierId = supplier.organization_id;
    const select = document.querySelector("#brand-cooperation-brand");
    select.innerHTML = brands.map((brand) => `<option value="${brand.id}">${Matrix.escapeHtml(brand.name)} · ${Matrix.escapeHtml(brand.code)}</option>`).join("");
    document.querySelector("#save-brand-cooperation").disabled = !brands.length;
    renderBrandCooperations();
    syncBrandCooperationForm();
  } catch (error) {
    if (generation !== adminState.brandCooperationGeneration) return;
    document.querySelector("#brand-cooperation-list").innerHTML = `<div class="cooperation-empty">${Matrix.escapeHtml(error.message)}</div>`;
    Matrix.toast("品牌合作加载失败", error.message, "error");
  }
}

async function saveBrandCooperation(event) {
  event.preventDefault();
  const supplier = adminState.selectedSupplier;
  const supplierId = adminState.loadedBrandCooperationSupplierId;
  const generation = adminState.brandCooperationGeneration;
  const brandId = document.querySelector("#brand-cooperation-brand").value;
  if (!supplier || supplier.organization_id !== supplierId || !brandId) return;
  const button = document.querySelector("#save-brand-cooperation");
  button.disabled = true;
  try {
    await Matrix.api(`/api/admin/suppliers/${supplierId}/brands/${brandId}/cooperation`, {
      method: "PUT",
      body: { commercial_mode: document.querySelector("#brand-cooperation-mode").value },
    });
    await loadBrandCooperations(supplierId, generation);
    if (generation !== adminState.brandCooperationGeneration) return;
    Matrix.toast("品牌合作已保存", "当前合作模式已更新并保留历史记录。", "success");
  } catch (error) {
    Matrix.toast("品牌合作保存失败", error.message, "error");
  } finally {
    if (generation === adminState.brandCooperationGeneration) {
      button.disabled = !adminState.brands.length;
    }
  }
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
    Matrix.toast("审核通过", "组织、供应商档案和供应商账号已建立。", "success");
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
    const view = Matrix.publicAuthView(adminState.user);
    if (view.workspaceHref !== "/admin") {
      window.location.href = view.authenticated ? view.workspaceHref : "/login";
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
  document.querySelector("#refresh-integration-clients").addEventListener("click", loadIntegrationClients);
  document.querySelector("#applications-search").addEventListener("input", () => { adminState.applicationPage = 1; renderApplications(); });
  document.querySelector("#applications-status").addEventListener("change", () => { adminState.applicationPage = 1; renderApplications(); });
  document.querySelector("#suppliers-search").addEventListener("input", () => { adminState.supplierPage = 1; renderSuppliers(); });
  document.querySelectorAll("[data-close-review]").forEach((button) => button.addEventListener("click", () => document.querySelector("#application-review-dialog").close()));
  document.querySelectorAll("[data-close-brand-cooperation]").forEach((button) => button.addEventListener("click", () => document.querySelector("#brand-cooperation-dialog").close()));
  bindIntegrationTokenDialog();
  document.querySelector("#approve-application").addEventListener("click", approveSelectedApplication);
  document.querySelector("#reject-application").addEventListener("click", rejectSelectedApplication);
  document.querySelector("#brand-cooperation-brand").addEventListener("change", syncBrandCooperationForm);
  document.querySelector("#brand-cooperation-form").addEventListener("submit", saveBrandCooperation);
  document.querySelector("#integration-client-form").addEventListener("submit", createIntegrationClient);
  window.addEventListener("hashchange", () => routeTo(window.location.hash.slice(1), false));

  routeTo(window.location.hash.slice(1) || "applications", false);
  await Promise.all([loadApplications(), loadSuppliers(), loadIntegrationClients()]);
}

document.addEventListener("DOMContentLoaded", bootAdmin);

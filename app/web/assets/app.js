const state = {
  user: null,
  dashboard: null,
  products: [],
  offers: [],
  offerBrands: [],
  imports: [],
  profile: null,
  editingOfferId: null,
  importFile: null,
  importPreview: null,
};

const routes = {
  dashboard: ["供应概览", "中国供应网络 / 工作台"],
  products: ["商品主数据", "中国供应网络 / 商品主数据"],
  offers: ["供应报价", "中国供应网络 / 供应报价"],
  imports: ["批量导入", "中国供应网络 / 数据接入"],
  documents: ["资质文件", "中国供应网络 / 资质文件"],
  orders: ["分发订单", "全球分发 / 订单协同"],
  settlements: ["结算管理", "全球分发 / 结算"],
  settings: ["企业资料", "账号与企业 / 供应能力档案"],
};

const icons = {
  products: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 8l-9 5-9-5 9-5 9 5Z"/><path d="m3 8 9 5 9-5M3 13l9 5 9-5"/></svg>',
  active_offers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M20 13V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h7"/><path d="M8 9h8M8 13h5M17 17l2 2 4-4"/></svg>',
  low_stock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 7h16l-1 13H5L4 7Z"/><path d="M8 7a4 4 0 0 1 8 0M12 11v4M12 18h.01"/></svg>',
  pending: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
};

function debounce(fn, wait = 280) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function currentRoute() {
  const route = window.location.hash.replace("#", "") || "dashboard";
  return routes[route] ? route : "dashboard";
}

function setRoute(route) {
  if (window.location.hash !== `#${route}`) {
    window.location.hash = route;
  } else {
    renderRoute(route);
  }
}

async function renderRoute(route) {
  document.querySelectorAll(".app-view").forEach((node) => {
    node.classList.toggle("active", node.dataset.view === route);
  });
  document.querySelectorAll(".nav-item[data-route]").forEach((node) => {
    node.classList.toggle("active", node.dataset.route === route);
  });
  document.querySelector("#page-title").textContent = routes[route][0];
  document.querySelector("#breadcrumb").textContent = routes[route][1];
  document.querySelector("#sidebar").classList.remove("open");

  try {
    if (route === "dashboard") await loadDashboard();
    if (route === "products") await loadProducts();
    if (route === "offers") {
      await loadOfferBrands();
      await loadOffers();
    }
    if (route === "imports") await loadImports();
    if (route === "settings") await loadProfile();
  } catch (error) {
    if (error.status === 401) {
      window.location.href = "/login";
      return;
    }
    Matrix.toast("加载失败", error.message, "error");
  }
}

async function loadDashboard() {
  const root = document.querySelector("#dashboard-root");
  root.innerHTML = '<div class="metric-grid">' + Array(4).fill('<div class="metric-card"><div class="skeleton"></div><div class="skeleton" style="height:34px;margin-top:18px"></div></div>').join("") + '</div>';
  state.dashboard = await Matrix.api("/api/dashboard");
  renderDashboard();
}

function renderDashboard() {
  const data = state.dashboard;
  const metrics = data.metrics.map((metric) => `
    <article class="metric-card" data-tone="${Matrix.escapeHtml(metric.tone)}">
      <div class="metric-card-top">
        <span class="metric-label">${Matrix.escapeHtml(metric.label)}</span>
        <span class="metric-icon">${icons[metric.key] || icons.products}</span>
      </div>
      <div class="metric-value">${Matrix.escapeHtml(metric.value)}</div>
      <div class="metric-hint">${Matrix.escapeHtml(metric.hint)}</div>
    </article>
  `).join("");

  const checklist = data.checklist.map((item) => `
    <a class="check-item ${item.completed ? "done" : ""}" href="${Matrix.escapeHtml(item.action_hash)}">
      <span class="check-mark">${item.completed ? '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3"><path d="m5 12 4 4 10-10"/></svg>' : ""}</span>
      <span class="check-copy"><strong>${Matrix.escapeHtml(item.label)}</strong><span>${Matrix.escapeHtml(item.description)}</span></span>
      <span class="check-action">${item.completed ? "已完成" : "去完成"}</span>
    </a>
  `).join("");

  const events = data.recent_events.length
    ? data.recent_events.map(renderEvent).join("")
    : '<div class="table-empty"><strong>暂无事件</strong>完成一次商品或报价操作后会显示在这里。</div>';

  document.querySelector("#dashboard-root").innerHTML = `
    <div class="metric-grid">${metrics}</div>
    <div class="dashboard-grid">
      <section class="panel">
        <header class="panel-head">
          <div><h2>供应网络接入进度</h2><p>把企业资料和真实供货能力整理为可调用数据。</p></div>
          ${Matrix.statusBadge(data.supplier_status)}
        </header>
        <div class="panel-body">
          <div class="onboarding-overview">
            <div class="progress-ring" style="--progress:${Number(data.profile_completion)}%">
              <div class="progress-ring-copy"><strong>${Number(data.profile_completion)}%</strong><span>资料完整度</span></div>
            </div>
            <div class="checklist">${checklist}</div>
          </div>
        </div>
      </section>
      <section class="panel">
        <header class="panel-head"><div><h2>最近动态</h2><p>关键数据操作均进入事件审计。</p></div><a href="/api/docs" target="_blank" class="btn btn-ghost btn-sm">API</a></header>
        <div class="panel-body"><div class="event-list">${events}</div></div>
      </section>
    </div>
  `;
}

function renderEvent(event) {
  const [title, fallback] = Matrix.eventInfo(event.event_type);
  let detail = fallback;
  const payload = event.payload || {};
  if (payload.product_name) detail = payload.product_name;
  if (payload.file_name) detail = `${payload.file_name} · 成功 ${payload.success_rows ?? 0} 条`;
  if (payload.fields) detail = `更新字段：${payload.fields.join("、")}`;
  return `
    <div class="event-item">
      <span class="event-dot">${Matrix.escapeHtml(title.slice(0, 1))}</span>
      <span class="event-copy"><strong>${Matrix.escapeHtml(title)}</strong><span>${Matrix.escapeHtml(detail)}</span></span>
      <time class="event-time">${Matrix.formatDate(event.occurred_at, true)}</time>
    </div>
  `;
}

async function loadProducts(query = "") {
  const url = query ? `/api/products?q=${encodeURIComponent(query)}` : "/api/products";
  state.products = await Matrix.api(url);
  renderProducts();
}

function renderProducts() {
  const tbody = document.querySelector("#products-tbody");
  if (!state.products.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty"><strong>尚未建立商品主数据</strong>新增单个商品，或通过模板批量导入。</td></tr>';
  } else {
    tbody.innerHTML = state.products.map((product) => `
      <tr>
        <td><div class="table-primary">${Matrix.escapeHtml(product.name)}</div><div class="table-secondary">ID ${Matrix.escapeHtml(product.id.slice(0, 8))}</div></td>
        <td>${Matrix.escapeHtml(product.brand || "—")}</td>
        <td>${Matrix.escapeHtml(product.model || "—")}</td>
        <td>${Matrix.escapeHtml(product.category)}</td>
        <td>${Matrix.statusBadge(product.status)}</td>
        <td>${Number(product.offer_count)}</td>
        <td class="text-right"><button class="btn btn-secondary btn-sm" data-add-offer="${product.id}">新增报价</button></td>
      </tr>
    `).join("");
  }
  document.querySelector("#products-count").textContent = `共 ${state.products.length} 条`;
  refreshOfferProductOptions();
}

async function loadOfferBrands() {
  const select = document.querySelector("#offers-brand");
  const selected = select.value;
  state.offerBrands = await Matrix.api("/api/offers/brands");
  select.innerHTML = '<option value="">全部品牌</option>' + state.offerBrands.map((brand) => `
    <option value="${Matrix.escapeHtml(brand)}">${Matrix.escapeHtml(brand)}</option>
  `).join("");
  if (state.offerBrands.includes(selected)) select.value = selected;
}

async function loadOffers(query = null, brand = null) {
  const params = new URLSearchParams();
  const searchValue = query === null ? document.querySelector("#offers-search").value.trim() : query.trim();
  const brandValue = brand === null ? document.querySelector("#offers-brand").value : brand;
  if (searchValue) params.set("q", searchValue);
  if (brandValue) params.set("brand", brandValue);
  const suffix = params.toString();
  state.offers = await Matrix.api(suffix ? `/api/offers?${suffix}` : "/api/offers");
  renderOffers();
}

function renderOffers() {
  const tbody = document.querySelector("#offers-tbody");
  if (!state.offers.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="table-empty"><strong>暂无供应报价</strong>报价必须包含采购价、MOQ、库存和交期。</td></tr>';
  } else {
    tbody.innerHTML = state.offers.map((offer) => `
      <tr>
        <td><div class="table-primary">${Matrix.escapeHtml(offer.product_name)}</div><div class="table-secondary">${Matrix.escapeHtml(offer.brand || "—")} · ${Matrix.escapeHtml(offer.model || "—")}</div></td>
        <td>${Matrix.escapeHtml(offer.supplier_sku)}</td>
        <td>${Matrix.formatMoney(offer.price, offer.currency)}</td>
        <td>${Number(offer.moq)}</td>
        <td class="${Number(offer.stock_qty) <= 10 ? "text-warning" : ""}">${Number(offer.stock_qty)}</td>
        <td>${Number(offer.lead_time_days)} 天</td>
        <td>${Matrix.escapeHtml(fulfillmentLabel(offer.fulfillment_mode))}</td>
        <td>${Matrix.statusBadge(offer.status)}</td>
        <td>${Matrix.formatDate(offer.updated_at)}</td>
        <td class="text-right"><button class="btn btn-secondary btn-sm" data-edit-offer="${offer.id}">编辑</button></td>
      </tr>
    `).join("");
  }
  document.querySelector("#offers-count").textContent = `共 ${state.offers.length} 条`;
}

function fulfillmentLabel(value) {
  const labels = { PURCHASE: "采购", DROPSHIP: "一件代发", CONSIGNMENT: "寄售", JOINT_OPERATION: "联营" };
  return labels[value] || value || "—";
}

async function loadImports() {
  state.imports = await Matrix.api("/api/imports");
  renderImports();
}

function renderImports() {
  const root = document.querySelector("#import-job-list");
  if (!state.imports.length) {
    root.innerHTML = '<div class="table-empty"><strong>暂无导入记录</strong>下载模板并上传第一批商品报价。</div>';
    return;
  }
  root.innerHTML = state.imports.map((job) => `
    <div class="import-job">
      <div><strong>${Matrix.escapeHtml(job.file_name)}</strong><span>${Matrix.formatDate(job.created_at, true)} · 成功 ${job.success_rows} / ${job.total_rows} · 失败 ${job.error_rows}</span></div>
      ${Matrix.statusBadge(job.status)}
    </div>
  `).join("");
}

async function loadProfile() {
  state.profile = await Matrix.api("/api/profile");
  const profile = state.profile;
  const form = document.querySelector("#profile-form");
  ["legal_name", "unified_social_credit_code", "supplier_type", "province", "city", "address", "contact_name", "contact_phone", "contact_email", "website"].forEach((name) => {
    if (form.elements[name]) form.elements[name].value = profile[name] || "";
  });
  form.elements.categories.value = (profile.categories || []).join("、");
  form.elements.cooperation_modes.value = (profile.cooperation_modes || []).join("、");
  form.elements.export_markets.value = (profile.export_markets || []).join("、");
  form.elements.supports_dropshipping.checked = profile.supports_dropshipping;
  form.elements.supports_oem.checked = profile.supports_oem;
  form.elements.has_export_experience.checked = profile.has_export_experience;
  document.querySelector("#profile-status").innerHTML = Matrix.statusBadge(profile.status);
  document.querySelector("#profile-completion-text").textContent = `${profile.profile_completion}%`;
}

function listFromText(value) {
  return String(value || "").split(/[、,，\n]/).map((item) => item.trim()).filter(Boolean);
}

function attributesFromText(value) {
  const result = {};
  String(value || "").split("\n").forEach((line) => {
    const [key, ...rest] = line.split(/[:：]/);
    const cleanKey = (key || "").trim();
    const cleanValue = rest.join(":").trim();
    if (cleanKey && cleanValue) result[cleanKey] = cleanValue;
  });
  return result;
}

function refreshOfferProductOptions(selectedId = "") {
  const select = document.querySelector("#offer-product-id");
  if (!select) return;
  select.innerHTML = '<option value="">请选择商品</option>' + state.products.map((product) => `
    <option value="${product.id}" ${selectedId === product.id ? "selected" : ""}>${Matrix.escapeHtml(product.name)}${product.model ? ` · ${Matrix.escapeHtml(product.model)}` : ""}</option>
  `).join("");
}

async function openProductDialog() {
  document.querySelector("#product-form").reset();
  document.querySelector("#product-dialog").showModal();
}

async function openOfferDialog(productId = "", offer = null) {
  if (!state.products.length) await loadProducts();
  state.editingOfferId = offer?.id || null;
  const form = document.querySelector("#offer-form");
  form.reset();
  refreshOfferProductOptions(productId || offer?.product_id || "");
  form.elements.product_id.disabled = Boolean(offer);
  form.elements.supplier_sku.disabled = Boolean(offer);
  document.querySelector("#offer-dialog-title").textContent = offer ? "编辑供应报价" : "新增供应报价";
  document.querySelector("#offer-dialog-submit").textContent = offer ? "保存修改" : "创建报价";
  if (offer) {
    ["supplier_sku", "price", "currency", "moq", "stock_qty", "lead_time_days", "fulfillment_mode", "status", "notes"].forEach((name) => {
      if (form.elements[name]) form.elements[name].value = offer[name] ?? "";
    });
  }
  document.querySelector("#offer-dialog").showModal();
}

async function submitProduct(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#product-dialog-submit");
  button.disabled = true;
  try {
    const data = Object.fromEntries(new FormData(form).entries());
    await Matrix.api("/api/products", {
      method: "POST",
      body: {
        name: data.name,
        brand: data.brand || null,
        model: data.model || null,
        category: data.category,
        description: data.description || null,
        attributes: attributesFromText(data.attributes_text),
        status: data.status,
      },
    });
    document.querySelector("#product-dialog").close();
    Matrix.toast("商品已创建", "下一步请为商品维护供应报价。", "success");
    await loadProducts();
  } catch (error) {
    Matrix.toast("创建失败", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

async function submitOffer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#offer-dialog-submit");
  button.disabled = true;
  try {
    const data = Object.fromEntries(new FormData(form).entries());
    const isEdit = Boolean(state.editingOfferId);
    const body = {
      price: Number(data.price),
      currency: data.currency,
      moq: Number(data.moq),
      stock_qty: Number(data.stock_qty),
      lead_time_days: Number(data.lead_time_days),
      fulfillment_mode: data.fulfillment_mode,
      status: data.status,
      notes: data.notes || null,
    };
    if (!isEdit) {
      body.product_id = data.product_id;
      body.supplier_sku = data.supplier_sku;
    }
    await Matrix.api(isEdit ? `/api/offers/${state.editingOfferId}` : "/api/offers", {
      method: isEdit ? "PATCH" : "POST",
      body,
    });
    document.querySelector("#offer-dialog").close();
    Matrix.toast(isEdit ? "报价已更新" : "报价已创建", "库存快照与审计事件已同步写入。", "success");
    await loadOfferBrands();
    await loadOffers();
  } catch (error) {
    Matrix.toast("保存失败", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function selectImportFile(file) {
  if (!file) return;
  if (!/\.(csv|tsv|txt|xlsx|xls|pdf)$/i.test(file.name)) {
    Matrix.toast("文件格式错误", "支持 CSV、XLSX、XLS 和 PDF 格式。", "error");
    return;
  }
  state.importFile = file;
  state.importPreview = null;
  document.querySelector("#selected-import-file").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
  document.querySelector("#csv-dropzone").classList.add("has-file");
  document.querySelector("#analyze-import").disabled = false;
  document.querySelector("#import-preview").classList.add("hidden");
}

function collectImportOptions() {
  const mapping = {};
  const defaults = {};
  document.querySelectorAll("[data-mapping-field]").forEach((select) => {
    mapping[select.dataset.mappingField] = select.value;
  });
  document.querySelectorAll("[data-default-field]").forEach((input) => {
    defaults[input.dataset.defaultField] = input.value.trim();
  });
  return { mapping, defaults };
}

function collectPreviewRows() {
  return [...document.querySelectorAll("#import-preview-tbody [data-import-row]")].map((tableRow) => {
    const row = {};
    tableRow.querySelectorAll("[data-row-field]").forEach((input) => {
      row[input.dataset.rowField] = input.value.trim();
    });
    return row;
  });
}

function importFormData(includeOptions = false, includeRows = false) {
  const body = new FormData();
  body.append("file", state.importFile);
  body.append("description", document.querySelector("#import-description").value.trim());
  if (includeOptions) {
    const { mapping, defaults } = collectImportOptions();
    body.append("mapping_json", JSON.stringify(mapping));
    body.append("defaults_json", JSON.stringify(defaults));
  }
  if (includeRows) body.append("rows_json", JSON.stringify(collectPreviewRows()));
  return body;
}

function importRowInput(field, value, label) {
  return `<input class="input import-cell-input" data-row-field="${field}" value="${Matrix.escapeHtml(value || "")}" aria-label="${label}">`;
}

function appendImportRow(values = {}, source = "新增", errors = []) {
  const defaults = state.importPreview?.defaults || {};
  const row = {
    product_name: "",
    brand: "",
    model: "",
    category: defaults.category || "",
    supplier_sku: "",
    price: "",
    currency: defaults.currency || "CNY",
    moq: defaults.moq || "1",
    stock_qty: defaults.stock_qty || "0",
    lead_time_days: defaults.lead_time_days || "3",
    fulfillment_mode: defaults.fulfillment_mode || "PURCHASE",
    status: defaults.status || "ACTIVE",
    ...values,
  };
  document.querySelector("#import-preview-tbody").insertAdjacentHTML("beforeend", `
    <tr data-import-row class="${errors.length ? "row-invalid" : ""}">
      <td><span class="import-row-source">${Matrix.escapeHtml(source)}</span></td>
      <td>${importRowInput("product_name", row.product_name, "商品名称")}</td>
      <td>${importRowInput("brand", row.brand, "品牌")}</td>
      <td>${importRowInput("model", row.model, "型号")}</td>
      <td>${importRowInput("category", row.category, "类目")}</td>
      <td>${importRowInput("supplier_sku", row.supplier_sku, "供应商 SKU")}</td>
      <td>${importRowInput("price", row.price, "采购价")}</td>
      <td>${importRowInput("currency", row.currency, "币种")}</td>
      <td>${importRowInput("moq", row.moq, "MOQ")}</td>
      <td>${importRowInput("stock_qty", row.stock_qty, "库存")}</td>
      <td>${importRowInput("lead_time_days", row.lead_time_days, "交期")}</td>
      <td>${importRowInput("fulfillment_mode", row.fulfillment_mode, "履约模式")}</td>
      <td>${importRowInput("status", row.status, "状态")}</td>
      <td data-row-validation>${errors.length ? `<span class="import-row-errors">${errors.map(Matrix.escapeHtml).join("；")}</span>` : '<span class="text-success">可导入</span>'}</td>
      <td><button class="btn btn-secondary btn-sm import-row-delete" type="button" data-delete-import-row>删除</button></td>
    </tr>
  `);
}

function updateEditableImportState() {
  const rows = collectPreviewRows();
  const validCandidates = rows.filter((row) => row.product_name && row.category && row.supplier_sku && row.price);
  document.querySelector("#import-preview-count").textContent = `目标列表 ${rows.length} 行 · 可导入 ${validCandidates.length} 行`;
  document.querySelector("#confirm-import").disabled = validCandidates.length === 0;
}

function renderImportPreview(result) {
  state.importPreview = result;
  const sheet = result.sheet_name ? ` · 工作表「${result.sheet_name}」` : "";
  document.querySelector("#import-preview-summary").textContent = `${result.file_name}${sheet} · 第 ${result.header_row} 行为表头 · 共 ${result.total_rows} 行`;
  document.querySelector("#import-preview-count").textContent = `有效 ${result.valid_rows} 行 · 待修正 ${result.invalid_rows} 行 · 最多展示前 20 行`;
  document.querySelector("#import-preview-warnings").innerHTML = result.warnings.length
    ? `<div class="import-warning">${result.warnings.map(Matrix.escapeHtml).join("；")}</div>`
    : "";

  document.querySelector("#import-mapping-grid").innerHTML = result.mapping.map((item) => {
    const options = [
      '<option value="">不映射 / 使用默认值</option>',
      ...result.headers.map((header) => `<option value="${Matrix.escapeHtml(header)}" ${header === item.source ? "selected" : ""}>${Matrix.escapeHtml(header)}</option>`),
    ].join("");
    const defaultValue = result.defaults[item.field] || "";
    return `
      <div class="import-mapping-item">
        <div class="import-mapping-title">
          <strong>${Matrix.escapeHtml(item.label)}${item.required ? '<span class="required-mark"> *</span>' : ""}</strong>
          <span class="mapping-confidence ${item.confidence}">${item.source ? `${item.confidence === "high" ? "高" : item.confidence === "medium" ? "中" : "低"}可信` : "未匹配"}</span>
        </div>
        <div class="import-mapping-controls">
          <select class="select" data-mapping-field="${item.field}" aria-label="${Matrix.escapeHtml(item.label)}来源列">${options}</select>
          <input class="input" data-default-field="${item.field}" value="${Matrix.escapeHtml(defaultValue)}" placeholder="空值默认" aria-label="${Matrix.escapeHtml(item.label)}默认值">
        </div>
      </div>
    `;
  }).join("");

  document.querySelector("#import-preview-tbody").innerHTML = "";
  result.preview_rows.forEach((item) => appendImportRow(item.values, `原表第 ${item.row} 行`, item.errors));
  updateEditableImportState();
  document.querySelector("#import-preview").classList.remove("hidden");
}

async function previewImport(includeOptions = false) {
  if (!state.importFile) return;
  const button = includeOptions
    ? document.querySelector("#refresh-import-preview")
    : document.querySelector("#analyze-import");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "正在识别…";
  try {
    const result = await Matrix.api("/api/imports/product-offers/preview", {
      method: "POST",
      body: importFormData(includeOptions),
    });
    renderImportPreview(result);
    document.querySelector("#import-preview").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    Matrix.toast("识别失败", error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function confirmSmartImport() {
  if (!state.importFile || !state.importPreview) return;
  if (!collectPreviewRows().length) {
    Matrix.toast("无法导入", "目标列表至少保留一行。", "error");
    return;
  }
  const button = document.querySelector("#confirm-import");
  button.disabled = true;
  button.textContent = "正在导入…";
  try {
    const result = await Matrix.api("/api/imports/product-offers", {
      method: "POST",
      body: importFormData(true, true),
    });
    Matrix.toast("导入完成", `成功 ${result.success_rows} 条，失败 ${result.error_rows} 条。`, result.error_rows ? "default" : "success");
    state.importFile = null;
    state.importPreview = null;
    document.querySelector("#csv-file").value = "";
    document.querySelector("#import-description").value = "";
    document.querySelector("#selected-import-file").textContent = "支持 CSV、XLSX、XLS、PDF，单文件最大 10MB。";
    document.querySelector("#csv-dropzone").classList.remove("has-file");
    document.querySelector("#analyze-import").disabled = true;
    document.querySelector("#import-preview").classList.add("hidden");
    await Promise.all([loadImports(), loadProducts()]);
    await loadOfferBrands();
    await loadOffers();
  } catch (error) {
    Matrix.toast("导入失败", error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "确认导入";
  }
}

async function saveProfile(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const button = document.querySelector("#profile-save");
  button.disabled = true;
  const data = Object.fromEntries(new FormData(form).entries());
  try {
    const result = await Matrix.api("/api/profile", {
      method: "PATCH",
      body: {
        legal_name: data.legal_name,
        unified_social_credit_code: data.unified_social_credit_code || null,
        supplier_type: data.supplier_type,
        province: data.province || null,
        city: data.city || null,
        address: data.address || null,
        contact_name: data.contact_name || null,
        contact_phone: data.contact_phone || null,
        contact_email: data.contact_email || null,
        website: data.website || null,
        categories: listFromText(data.categories),
        cooperation_modes: listFromText(data.cooperation_modes),
        export_markets: listFromText(data.export_markets),
        supports_dropshipping: form.elements.supports_dropshipping.checked,
        supports_oem: form.elements.supports_oem.checked,
        has_export_experience: form.elements.has_export_experience.checked,
      },
    });
    state.profile = result;
    document.querySelector("#profile-completion-text").textContent = `${result.profile_completion}%`;
    Matrix.toast("企业资料已保存", "新的供应能力信息已写入审计日志。", "success");
  } catch (error) {
    Matrix.toast("保存失败", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function bindEvents() {
  window.addEventListener("hashchange", () => renderRoute(currentRoute()));
  document.querySelectorAll(".nav-item[data-route]").forEach((item) => {
    item.addEventListener("click", () => setRoute(item.dataset.route));
  });
  document.querySelector("#mobile-menu").addEventListener("click", () => {
    document.querySelector("#sidebar").classList.toggle("open");
  });
  document.querySelector("#logout-button").addEventListener("click", async () => {
    try { await Matrix.api("/api/auth/logout", { method: "POST" }); } finally { window.location.href = "/login"; }
  });

  document.querySelectorAll("[data-open-product]").forEach((button) => button.addEventListener("click", openProductDialog));
  document.querySelectorAll("[data-open-offer]").forEach((button) => button.addEventListener("click", () => openOfferDialog()));
  document.querySelector("#product-form").addEventListener("submit", submitProduct);
  document.querySelector("#offer-form").addEventListener("submit", submitOffer);
  document.querySelector("#profile-form").addEventListener("submit", saveProfile);
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog").close());
  });

  document.querySelector("#products-search").addEventListener("input", debounce((event) => loadProducts(event.target.value)));
  document.querySelector("#offers-search").addEventListener("input", debounce((event) => loadOffers(event.target.value)));
  document.querySelector("#offers-brand").addEventListener("change", (event) => loadOffers(null, event.target.value));

  document.querySelector("#products-tbody").addEventListener("click", (event) => {
    const button = event.target.closest("[data-add-offer]");
    if (button) openOfferDialog(button.dataset.addOffer);
  });
  document.querySelector("#offers-tbody").addEventListener("click", (event) => {
    const button = event.target.closest("[data-edit-offer]");
    if (!button) return;
    const offer = state.offers.find((item) => item.id === button.dataset.editOffer);
    if (offer) openOfferDialog("", offer);
  });

  const input = document.querySelector("#csv-file");
  const choose = document.querySelector("#choose-csv");
  const dropzone = document.querySelector("#csv-dropzone");
  choose.addEventListener("click", () => input.click());
  input.addEventListener("change", () => selectImportFile(input.files[0]));
  document.querySelector("#analyze-import").addEventListener("click", () => previewImport(false));
  document.querySelector("#refresh-import-preview").addEventListener("click", () => previewImport(true));
  document.querySelector("#add-import-row").addEventListener("click", () => {
    appendImportRow();
    updateEditableImportState();
  });
  document.querySelector("#confirm-import").addEventListener("click", confirmSmartImport);
  document.querySelector("#import-preview-tbody").addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-import-row]");
    if (!button) return;
    button.closest("[data-import-row]").remove();
    updateEditableImportState();
  });
  document.querySelector("#import-preview-tbody").addEventListener("input", (event) => {
    const tableRow = event.target.closest("[data-import-row]");
    if (tableRow) {
      tableRow.classList.remove("row-invalid");
      tableRow.querySelector("[data-row-validation]").innerHTML = '<span class="muted">已编辑</span>';
    }
    updateEditableImportState();
  });
  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
  }));
  dropzone.addEventListener("drop", (event) => selectImportFile(event.dataTransfer.files[0]));
}

async function boot() {
  try {
    state.user = await Matrix.api("/api/auth/me");
    const view = Matrix.publicAuthView(state.user);
    if (view.workspaceHref !== "/app") {
      window.location.href = view.authenticated ? view.workspaceHref : "/login";
      return;
    }
  } catch (error) {
    window.location.href = "/login";
    return;
  }
  document.querySelector("#user-name").textContent = state.user.name;
  document.querySelector("#user-role").textContent = Matrix.userRoleLabel(state.user);
  document.querySelector("#user-avatar").textContent = state.user.name.slice(0, 1);
  document.querySelector("#supplier-name-mini").textContent = state.user.organization_name;
  bindEvents();
  await renderRoute(currentRoute());
}

document.addEventListener("DOMContentLoaded", boot);

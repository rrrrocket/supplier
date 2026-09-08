const state = {
  user: null,
  dashboard: null,
  products: [],
  offers: [],
  productPage: 1,
  offerPage: 1,
  productRequestRevision: 0,
  offerRequestRevision: 0,
  offerBrandRequestRevision: 0,
  offerRouteRevision: 0,
  offerBrands: [],
  brandCooperations: [],
  brandCooperationRequestRevision: 0,
  imports: [],
  profile: null,
  editingOfferId: null,
  importFile: null,
  importPreview: null,
  importWorkbook: null,
  importWorkflowRevision: 0,
};

const ImportWorkbook = window.MatrixImportWorkbook;
const listChunkSize = 500;
const tablePageSize = 50;

const importFields = [
  ["product_name", "商品名称", true],
  ["brand", "品牌", false],
  ["model", "型号", false],
  ["category", "类目", true],
  ["supplier_sku", "供应商 SKU", true],
  ["price", "采购价", true],
  ["currency", "币种", false],
  ["moq", "MOQ", false],
  ["stock_qty", "库存", false],
  ["lead_time_days", "交期", false],
  ["fulfillment_mode", "履约模式", false],
  ["status", "状态", false],
];

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
  const offerRouteRevision = ++state.offerRouteRevision;
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
      const brandsLoaded = await loadOfferBrands(offerRouteRevision);
      if (!brandsLoaded || state.offerRouteRevision !== offerRouteRevision) return;
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

async function fetchAllListRows(path, params, isCurrent) {
  const rowsById = new Map();
  const pageSignatures = new Set();
  let offset = 0;
  while (true) {
    const chunkParams = new URLSearchParams(params);
    chunkParams.set("limit", String(listChunkSize));
    chunkParams.set("offset", String(offset));
    let chunk;
    try {
      chunk = await Matrix.api(`${path}?${chunkParams.toString()}`);
    } catch (error) {
      if (!isCurrent()) return null;
      throw error;
    }
    if (!isCurrent()) return null;
    const signature = chunk.map((row) => row.id).join("\n");
    if (pageSignatures.has(signature)) break;
    pageSignatures.add(signature);
    let added = 0;
    chunk.forEach((row) => {
      if (!rowsById.has(row.id)) added += 1;
      rowsById.set(row.id, row);
    });
    if (chunk.length < listChunkSize || added === 0) break;
    offset += listChunkSize;
  }
  return [...rowsById.values()];
}

async function loadProducts(query = null) {
  const revision = ++state.productRequestRevision;
  const searchValue = query === null ? document.querySelector("#products-search").value.trim() : query.trim();
  if (query !== null) state.productPage = 1;
  const params = new URLSearchParams();
  if (searchValue) params.set("q", searchValue);
  const products = await fetchAllListRows(
    "/api/products",
    params,
    () => state.productRequestRevision === revision,
  );
  if (products === null) return;
  state.products = products;
  renderProducts();
  refreshOfferProductOptions();
}

function renderProducts() {
  const tbody = document.querySelector("#products-tbody");
  const totalPages = Math.max(1, Math.ceil(state.products.length / tablePageSize));
  state.productPage = Math.min(Math.max(1, state.productPage), totalPages);
  const start = (state.productPage - 1) * tablePageSize;
  const visibleProducts = state.products.slice(start, start + tablePageSize);
  if (!state.products.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="table-empty"><strong>尚未建立商品主数据</strong>新增单个商品，或通过模板批量导入。</td></tr>';
  } else {
    tbody.innerHTML = visibleProducts.map((product) => `
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
  const visibleStart = state.products.length ? start + 1 : 0;
  const visibleEnd = state.products.length ? start + visibleProducts.length : 0;
  document.querySelector("#products-count").textContent = `显示 ${visibleStart}–${visibleEnd} / 共 ${state.products.length} 条`;
  document.querySelector("#products-page").textContent = `第 ${state.productPage} / ${totalPages} 页`;
  document.querySelector("#products-prev-page").disabled = state.productPage === 1;
  document.querySelector("#products-next-page").disabled = state.productPage === totalPages;
}

async function loadOfferBrands(expectedRouteRevision = state.offerRouteRevision) {
  const revision = ++state.offerBrandRequestRevision;
  const select = document.querySelector("#offers-brand");
  let offerBrands;
  try {
    offerBrands = await Matrix.api("/api/offers/brands");
  } catch (error) {
    if (
      revision !== state.offerBrandRequestRevision
      || expectedRouteRevision !== state.offerRouteRevision
    ) return false;
    throw error;
  }
  if (
    revision !== state.offerBrandRequestRevision
    || expectedRouteRevision !== state.offerRouteRevision
  ) return false;
  const selected = select.value;
  state.offerBrands = offerBrands;
  select.innerHTML = '<option value="">全部品牌</option>' + state.offerBrands.map((brand) => `
    <option value="${Matrix.escapeHtml(brand)}">${Matrix.escapeHtml(brand)}</option>
  `).join("");
  if (state.offerBrands.includes(selected)) select.value = selected;
  return true;
}

async function loadOffers(query = null, brand = null) {
  if (query !== null || brand !== null) state.offerRouteRevision += 1;
  const revision = ++state.offerRequestRevision;
  const params = new URLSearchParams();
  const searchValue = query === null ? document.querySelector("#offers-search").value.trim() : query.trim();
  const brandValue = brand === null ? document.querySelector("#offers-brand").value : brand;
  if (query !== null || brand !== null) state.offerPage = 1;
  if (searchValue) params.set("q", searchValue);
  if (brandValue) params.set("brand", brandValue);
  const offers = await fetchAllListRows(
    "/api/offers",
    params,
    () => state.offerRequestRevision === revision,
  );
  if (offers === null) return;
  state.offers = offers;
  renderOffers();
}

function renderOffers() {
  const tbody = document.querySelector("#offers-tbody");
  const totalPages = Math.max(1, Math.ceil(state.offers.length / tablePageSize));
  state.offerPage = Math.min(Math.max(1, state.offerPage), totalPages);
  const start = (state.offerPage - 1) * tablePageSize;
  const visibleOffers = state.offers.slice(start, start + tablePageSize);
  if (!state.offers.length) {
    tbody.innerHTML = '<tr><td colspan="10" class="table-empty"><strong>暂无供应报价</strong>报价必须包含价格、MOQ、库存和交期。</td></tr>';
  } else {
    tbody.innerHTML = visibleOffers.map((offer) => `
      <tr>
        <td><div class="table-primary">${Matrix.escapeHtml(offer.product_name)}</div><div class="table-secondary">${Matrix.escapeHtml(offer.brand || "—")} · ${Matrix.escapeHtml(offer.model || "—")}</div></td>
        <td><div class="table-primary">${Matrix.escapeHtml(offer.supplier_sku_code)}</div><div class="table-secondary">ID ${Matrix.escapeHtml(offer.supplier_sku_id)}</div></td>
        <td><div class="table-primary">${Matrix.formatMoney(offer.price, offer.currency)}</div><div class="table-secondary">${offerPriceLabel(offer.commercial_mode)}</div></td>
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
  const visibleStart = state.offers.length ? start + 1 : 0;
  const visibleEnd = state.offers.length ? start + visibleOffers.length : 0;
  document.querySelector("#offers-count").textContent = `显示 ${visibleStart}–${visibleEnd} / 共 ${state.offers.length} 条`;
  document.querySelector("#offers-page").textContent = `第 ${state.offerPage} / ${totalPages} 页`;
  document.querySelector("#offers-prev-page").disabled = state.offerPage === 1;
  document.querySelector("#offers-next-page").disabled = state.offerPage === totalPages;
}

function fulfillmentLabel(value) {
  const labels = { PURCHASE: "采购", DROPSHIP: "一件代发", CONSIGNMENT: "寄售", JOINT_OPERATION: "联营" };
  return labels[value] || value || "—";
}

function cooperationModeLabel(value) {
  const labels = {
    SELF_PURCHASE: "A 模式（自营采购）",
    JOINT_OPERATION: "B 模式（联营）",
    B2B: "C 模式（B2B）",
  };
  return labels[value] || "未确认模式";
}

function offerPriceLabel(commercialMode) {
  return commercialMode === "SELF_PURCHASE" ? "成本价" : "供货价";
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

async function loadBrandCooperations() {
  const revision = ++state.brandCooperationRequestRevision;
  let cooperations;
  try {
    cooperations = await Matrix.api("/api/supplier-catalog/brand-cooperations");
  } catch (error) {
    if (revision !== state.brandCooperationRequestRevision) return null;
    throw error;
  }
  if (revision !== state.brandCooperationRequestRevision) return null;
  state.brandCooperations = cooperations.filter((item) => item.status === "ACTIVE");
  return state.brandCooperations;
}

function refreshProductBrandOptions() {
  const select = document.querySelector("#product-brand");
  select.innerHTML = '<option value="">请选择已分配品牌</option>' + state.brandCooperations.map((cooperation) => `
    <option value="${Matrix.escapeHtml(cooperation.brand_name)}">${Matrix.escapeHtml(cooperation.brand_name)} · ${cooperationModeLabel(cooperation.commercial_mode)}</option>
  `).join("");
}

function refreshOfferPriceLabel(productId, commercialMode = null) {
  const product = state.products.find((item) => item.id === productId);
  const cooperation = product
    ? state.brandCooperations.find((item) => item.brand_id === product.brand_id)
    : null;
  document.querySelector("#offer-price-label").textContent = offerPriceLabel(
    commercialMode || cooperation?.commercial_mode,
  );
}

async function openProductDialog() {
  document.querySelector("#product-form").reset();
  const cooperations = await loadBrandCooperations();
  if (cooperations === null) return;
  refreshProductBrandOptions();
  document.querySelector("#product-dialog").showModal();
}

async function openOfferDialog(productId = "", offer = null) {
  if (!state.products.length) await loadProducts();
  const cooperations = await loadBrandCooperations();
  if (cooperations === null) return;
  state.editingOfferId = offer?.id || null;
  const form = document.querySelector("#offer-form");
  form.reset();
  refreshOfferProductOptions(productId || offer?.product_id || "");
  form.elements.product_id.disabled = Boolean(offer);
  form.elements.supplier_sku_code.disabled = Boolean(offer);
  document.querySelector("#offer-supplier-sku-id").textContent = offer
    ? `稳定 ID：${offer.supplier_sku_id}`
    : "稳定 ID 将在创建后生成";
  refreshOfferPriceLabel(productId || offer?.product_id || "", offer?.commercial_mode);
  document.querySelector("#offer-dialog-title").textContent = offer ? "编辑供应报价" : "新增供应报价";
  document.querySelector("#offer-dialog-submit").textContent = offer ? "保存修改" : "创建报价";
  if (offer) {
    ["supplier_sku_code", "price", "currency", "moq", "stock_qty", "lead_time_days", "fulfillment_mode", "status", "notes"].forEach((name) => {
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
      body.supplier_sku_code = data.supplier_sku_code;
    }
    await Matrix.api(isEdit ? `/api/offers/${state.editingOfferId}` : "/api/offers", {
      method: isEdit ? "PATCH" : "POST",
      body,
    });
    document.querySelector("#offer-dialog").close();
    Matrix.toast(isEdit ? "报价已更新" : "报价已创建", "库存快照与审计事件已同步写入。", "success");
    if (await loadOfferBrands()) await loadOffers();
  } catch (error) {
    Matrix.toast("保存失败", error.message, "error");
  } finally {
    button.disabled = false;
  }
}

function isExcelImport(file) {
  return /\.xlsx?$/i.test(file?.name || "");
}

function advanceImportWorkflow() {
  state.importWorkflowRevision += 1;
  return state.importWorkflowRevision;
}

function isCurrentImportWorkflow(revision) {
  return state.importWorkflowRevision === revision;
}

function invalidateWorkbookPreview() {
  advanceImportWorkflow();
  state.importPreview = null;
  if (state.importWorkbook) {
    state.importWorkbook.rows = [];
    state.importWorkbook.page = 1;
    state.importWorkbook.lastExcludedCorrections = [];
  }
  document.querySelector("#import-preview").classList.add("hidden");
  const button = document.querySelector("#preview-selected-sheets");
  button.disabled = !state.importWorkbook?.selectedSheets.length;
  button.textContent = "生成合并预览";
}

function resetImportInterface() {
  state.importPreview = null;
  state.importWorkbook = null;
  document.querySelector("#import-workbook-config").classList.add("hidden");
  document.querySelector("#import-preview").classList.add("hidden");
  document.querySelector("#import-sheet-list").innerHTML = "";
  document.querySelector("#import-sheet-configs").innerHTML = "";
  document.querySelector("#import-mapping-grid").innerHTML = "";
  document.querySelector("#import-sheet-filter").innerHTML = '<option value="">全部工作表</option>';
  document.querySelector("#import-conflict-only").checked = false;
  document.querySelector("#preview-selected-sheets").textContent = "生成合并预览";
  document.querySelector("#refresh-import-preview").disabled = false;
  document.querySelector("#refresh-import-preview").textContent = "更新预览";
  document.querySelector("#confirm-import").disabled = true;
  document.querySelector("#confirm-import").textContent = "确认导入";
  document.querySelector("#analyze-import").textContent = "智能识别并预览";
}

async function selectImportFile(file) {
  if (!file) return;
  const workflowRevision = advanceImportWorkflow();
  resetImportInterface();
  state.importFile = null;
  if (!/\.(csv|tsv|txt|xlsx|xls|pdf)$/i.test(file.name)) {
    document.querySelector("#selected-import-file").textContent = "支持 CSV、XLSX、XLS、PDF，单文件最大 10MB。";
    document.querySelector("#csv-dropzone").classList.remove("has-file");
    document.querySelector("#analyze-import").classList.remove("hidden");
    document.querySelector("#analyze-import").disabled = true;
    Matrix.toast("文件格式错误", "支持 CSV、XLSX、XLS 和 PDF 格式。", "error");
    return;
  }
  state.importFile = file;
  document.querySelector("#selected-import-file").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
  document.querySelector("#csv-dropzone").classList.add("has-file");
  const analyzeButton = document.querySelector("#analyze-import");
  const excel = isExcelImport(file);
  analyzeButton.classList.toggle("hidden", excel);
  analyzeButton.disabled = excel;
  if (!excel) return;

  document.querySelector("#selected-import-file").textContent = `${file.name} · 正在扫描工作表…`;
  const body = new FormData();
  body.append("file", file);
  try {
    const inspection = await Matrix.api("/api/imports/product-offers/workbook/inspect", {
      method: "POST",
      body,
    });
    if (!isCurrentImportWorkflow(workflowRevision) || state.importFile !== file) return;
    state.importWorkbook = ImportWorkbook.createWorkbookState(inspection);
    renderWorkbookConfiguration();
    document.querySelector("#import-workbook-config").classList.remove("hidden");
    document.querySelector("#selected-import-file").textContent = `${file.name} · ${(file.size / 1024).toFixed(1)} KB`;
  } catch (error) {
    if (isCurrentImportWorkflow(workflowRevision) && state.importFile === file) {
      Matrix.toast("工作簿扫描失败", error.message, "error");
      document.querySelector("#selected-import-file").textContent = `${file.name} · 扫描失败，请重新选择文件`;
    }
  }
}

function selectedSheetSet() {
  return new Set(state.importWorkbook?.selectedSheets || []);
}

function renderWorkbookConfiguration() {
  const workbook = state.importWorkbook;
  if (!workbook?.inspection) return;
  const selected = selectedSheetSet();
  document.querySelector("#import-workbook-summary").textContent = `${workbook.inspection.file_name} · ${workbook.inspection.sheets.length} 个工作表 · 已选择 ${selected.size} 个`;
  document.querySelector("#import-sheet-list").innerHTML = workbook.inspection.sheets.map((sheet, index) => `
    <label class="import-sheet-chip ${selected.has(sheet.name) ? "selected" : ""}">
      <input type="checkbox" data-sheet-name="${Matrix.escapeHtml(sheet.name)}" ${selected.has(sheet.name) ? "checked" : ""}>
      <span><strong>${Matrix.escapeHtml(sheet.name)}</strong><small>约 ${Number(sheet.estimated_rows || 0)} 行</small></span>
    </label>
  `).join("");
  document.querySelector("#select-all-sheets").textContent = selected.size === workbook.inspection.sheets.length ? "取消全选" : "全选";
  renderSheetConfigurations();
  document.querySelector("#preview-selected-sheets").disabled = selected.size === 0;
}

function columnOptions(sheet, selectedColumn) {
  return [
    '<option value="">不映射 / 使用默认值</option>',
    ...(sheet.columns || []).map((column) => `
      <option value="${Matrix.escapeHtml(column.key)}" ${column.key === selectedColumn ? "selected" : ""}>${Matrix.escapeHtml(column.label)}</option>
    `),
  ].join("");
}

function renderSheetConfigurations() {
  const workbook = state.importWorkbook;
  const selected = selectedSheetSet();
  const cards = workbook.inspection.sheets.filter((sheet) => selected.has(sheet.name)).map((sheet) => {
    const config = workbook.configs[sheet.name];
    const sample = (sheet.sample_rows || []).slice(0, 2).map((row) => `
      <div class="import-sheet-sample-row">${(sheet.columns || []).map((column) => `<span><strong>${Matrix.escapeHtml(column.key)}</strong> ${Matrix.escapeHtml(row[column.key] || "—")}</span>`).join("")}</div>
    `).join("");
    const mappings = importFields.map(([field, label, required]) => `
      <div class="import-mapping-item">
        <div class="import-mapping-title"><strong>${Matrix.escapeHtml(label)}${required ? '<span class="required-mark"> *</span>' : ""}</strong></div>
        <div class="import-mapping-controls">
          <select class="select" data-sheet-mapping-field="${field}" aria-label="${Matrix.escapeHtml(sheet.name)} ${Matrix.escapeHtml(label)}来源列">${columnOptions(sheet, config.mapping[field] || "")}</select>
          <input class="input" data-sheet-default-field="${field}" value="${Matrix.escapeHtml(config.defaults[field] || "")}" placeholder="空值默认" aria-label="${Matrix.escapeHtml(sheet.name)} ${Matrix.escapeHtml(label)}默认值">
        </div>
      </div>
    `).join("");
    return `
      <article class="import-sheet-card" data-sheet-config="${Matrix.escapeHtml(sheet.name)}">
        <header class="import-sheet-card-head">
          <div><h3>${Matrix.escapeHtml(sheet.name)}</h3><p>约 ${Number(sheet.estimated_rows || 0)} 条数据 · ${Number(sheet.column_count || 0)} 列</p></div>
          <label class="import-header-row"><span>表头行</span><input class="input" type="number" min="1" step="1" value="${Number(config.header_row)}" data-sheet-header-row aria-label="${Matrix.escapeHtml(sheet.name)} 表头行"></label>
        </header>
        ${sample ? `<div class="import-sheet-sample"><span>原始样例</span>${sample}</div>` : ""}
        <div class="import-sheet-mappings">${mappings}</div>
      </article>
    `;
  });
  document.querySelector("#import-sheet-configs").innerHTML = cards.length
    ? cards.join("")
    : '<div class="table-empty"><strong>尚未选择工作表</strong>请选择至少一个工作表后配置字段。</div>';
}

function selectedSheetConfigs() {
  const workbook = state.importWorkbook;
  return workbook.inspection.sheets
    .filter((sheet) => workbook.selectedSheets.includes(sheet.name))
    .map((sheet) => {
      const config = workbook.configs[sheet.name];
      return {
        sheet_name: config.sheet_name,
        header_row: config.header_row,
        mapping: { ...config.mapping },
        defaults: { ...config.defaults },
      };
    });
}

async function previewSelectedSheets() {
  const workbook = state.importWorkbook;
  if (!state.importFile || !workbook?.selectedSheets.length) return;
  const workflowRevision = advanceImportWorkflow();
  const button = document.querySelector("#preview-selected-sheets");
  button.disabled = true;
  button.textContent = "正在合并…";
  const body = new FormData();
  body.append("file", state.importFile);
  body.append("description", document.querySelector("#import-description").value.trim());
  body.append("sheet_configs_json", JSON.stringify(selectedSheetConfigs()));
  try {
    const result = await Matrix.api("/api/imports/product-offers/preview", { method: "POST", body });
    if (!isCurrentImportWorkflow(workflowRevision)) return;
    renderImportPreview(result, true);
    document.querySelector("#import-preview").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (!isCurrentImportWorkflow(workflowRevision)) return;
    Matrix.toast("预览失败", error.message, "error");
  } finally {
    if (isCurrentImportWorkflow(workflowRevision)) {
      button.disabled = !state.importWorkbook?.selectedSheets.length;
      button.textContent = "生成合并预览";
    }
  }
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
  return (state.importWorkbook?.rows || []).map((row) => ({
    source_sheet: row.source_sheet,
    source_row: row.source_row,
    included: row.included,
    values: { ...row.values },
  }));
}

function importFormData(includeOptions = false, includeRows = false) {
  const body = new FormData();
  body.append("file", state.importFile);
  body.append("description", document.querySelector("#import-description").value.trim());
  if (includeOptions && !state.importWorkbook?.inspection) {
    const { mapping, defaults } = collectImportOptions();
    body.append("mapping_json", JSON.stringify(mapping));
    body.append("defaults_json", JSON.stringify(defaults));
  }
  if (includeRows) {
    body.append("rows_json", JSON.stringify(collectPreviewRows()));
    if (state.importWorkbook?.inspection) {
      body.append("sheet_configs_json", JSON.stringify(selectedSheetConfigs()));
    }
  }
  return body;
}

function importRowInput(rowIndex, field, value, label) {
  return `<input class="input import-cell-input" data-row-index="${rowIndex}" data-row-field="${field}" value="${Matrix.escapeHtml(value || "")}" aria-label="${label}">`;
}

function blankImportValues(values = {}) {
  const defaults = state.importPreview?.defaults || {};
  return {
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
}

function rowSourceLabel(row) {
  if (row.source_sheet) return `${row.source_sheet} · 第${row.source_row}行`;
  if (row.source_row) return `原表第 ${row.source_row} 行`;
  return "新增";
}

function rowValidation(row) {
  if (!row.included) return '<span class="muted">已排除</span>';
  if (row.conflict_group) return `<span class="import-row-errors">SKU 重复：${Matrix.escapeHtml(row.conflict_group)}</span>`;
  if (row.errors?.length) return `<span class="import-row-errors">${row.errors.map(Matrix.escapeHtml).join("；")}</span>`;
  return '<span class="text-success">可导入</span>';
}

function rowClassName(row) {
  return [
    row.errors?.length ? "row-invalid" : "",
    row.conflict_group && row.included ? "row-conflict" : "",
    !row.included ? "row-excluded" : "",
  ].filter(Boolean).join(" ");
}

function filteredImportRows() {
  const workbook = state.importWorkbook;
  return (workbook?.rows || []).filter((row) => {
    if (workbook.sheetFilter && row.source_sheet !== workbook.sheetFilter) return false;
    if (workbook.conflictOnly && !row.conflict_group) return false;
    if (workbook.correctionOnly && !ImportWorkbook.needsCorrection(row)) return false;
    return true;
  });
}

function renderImportWarnings(workbook, correctionCount) {
  const warnings = [...(workbook.previewWarnings || [])];
  if (correctionCount) warnings.unshift(`检测到 ${correctionCount} 行数据需要修正`);
  document.querySelector("#import-preview-warnings").innerHTML = warnings.length
    ? `<div class="import-warning">${warnings.map(Matrix.escapeHtml).join("；")}</div>`
    : "";
}

function updateImportControls() {
  const workbook = state.importWorkbook;
  if (!workbook) return;
  const filtered = filteredImportRows();
  const totalPages = Math.max(1, Math.ceil(filtered.length / workbook.pageSize));
  workbook.page = Math.min(Math.max(1, workbook.page), totalPages);
  const included = workbook.rows.filter((row) => row.included);
  const corrections = ImportWorkbook.correctionCount(workbook.rows);
  const conflicts = new Set(included.map((row) => row.conflict_group).filter(Boolean));
  const currentRows = new Set(workbook.rows);
  const canRestoreCorrections = (workbook.lastExcludedCorrections || []).some(
    (row) => currentRows.has(row) && !row.included,
  );
  document.querySelector("#import-preview-count").textContent = `目标列表 ${workbook.rows.length} 行 · 保留 ${included.length} 行 · 需修正 ${corrections} 行 · 冲突 ${conflicts.size} 组`;
  renderImportWarnings(workbook, corrections);
  document.querySelector("#exclude-correction-rows").disabled = corrections === 0;
  document.querySelector("#restore-correction-rows").classList.toggle("hidden", !canRestoreCorrections);
  document.querySelector("#confirm-import").disabled = !ImportWorkbook.canImport(workbook.rows);
  document.querySelector("#import-prev-page").disabled = workbook.page <= 1;
  document.querySelector("#import-next-page").disabled = workbook.page >= totalPages;
  document.querySelector("#import-page-status").textContent = `第 ${workbook.page} / ${totalPages} 页 · 当前筛选 ${filtered.length} 行`;
}

function renderImportRows() {
  const workbook = state.importWorkbook;
  if (!workbook) return;
  updateImportControls();
  const multiSheet = Boolean(workbook.inspection);
  document.querySelector("#import-preview-tbody").innerHTML = ImportWorkbook.pageRows(workbook, workbook.page).map((row) => {
    const rowIndex = workbook.rows.indexOf(row);
    const values = blankImportValues(row.values);
    const action = multiSheet
      ? `<button class="btn btn-secondary btn-sm import-row-delete" type="button" data-toggle-import-row="${rowIndex}">${row.included ? "排除" : "恢复"}</button>`
      : `<button class="btn btn-secondary btn-sm import-row-delete" type="button" data-delete-import-row="${rowIndex}">删除</button>`;
    return `
      <tr data-import-row="${rowIndex}" class="${rowClassName(row)}">
        <td><span class="import-row-source">${Matrix.escapeHtml(rowSourceLabel(row))}</span></td>
        <td>${importRowInput(rowIndex, "product_name", values.product_name, "商品名称")}</td>
        <td>${importRowInput(rowIndex, "brand", values.brand, "品牌")}</td>
        <td>${importRowInput(rowIndex, "model", values.model, "型号")}</td>
        <td>${importRowInput(rowIndex, "category", values.category, "类目")}</td>
        <td>${importRowInput(rowIndex, "supplier_sku", values.supplier_sku, "供应商 SKU")}</td>
        <td>${importRowInput(rowIndex, "price", values.price, "采购价")}</td>
        <td>${importRowInput(rowIndex, "currency", values.currency, "币种")}</td>
        <td>${importRowInput(rowIndex, "moq", values.moq, "MOQ")}</td>
        <td>${importRowInput(rowIndex, "stock_qty", values.stock_qty, "库存")}</td>
        <td>${importRowInput(rowIndex, "lead_time_days", values.lead_time_days, "交期")}</td>
        <td>${importRowInput(rowIndex, "fulfillment_mode", values.fulfillment_mode, "履约模式")}</td>
        <td>${importRowInput(rowIndex, "status", values.status, "状态")}</td>
        <td data-row-validation>${rowValidation(row)}</td>
        <td>${action}</td>
      </tr>
    `;
  }).join("");
}

function refreshRenderedRowStates() {
  document.querySelectorAll("#import-preview-tbody [data-import-row]").forEach((tableRow) => {
    const row = state.importWorkbook.rows[Number(tableRow.dataset.importRow)];
    if (!row) return;
    tableRow.className = rowClassName(row);
    tableRow.querySelector("[data-row-validation]").innerHTML = rowValidation(row);
  });
  updateImportControls();
}

function renderImportPreview(result, multiSheet = false) {
  state.importPreview = result;
  if (!multiSheet) {
    state.importWorkbook = {
      inspection: null,
      selectedSheets: [],
      configs: {},
      rows: [],
      page: 1,
      pageSize: 50,
      sheetFilter: "",
      conflictOnly: false,
      correctionOnly: false,
      lastExcludedCorrections: [],
    };
  }
  const workbook = state.importWorkbook;
  workbook.rows = result.preview_rows.map((item, index) => ({
    source_sheet: item.source_sheet ?? result.sheet_name ?? null,
    source_row: item.source_row ?? item.row ?? index + 1,
    included: item.included !== false,
    conflict_group: item.conflict_group || null,
    values: blankImportValues(item.values),
    errors: [...(item.errors || [])],
  }));
  ImportWorkbook.resolveRows(workbook.rows);
  workbook.page = 1;
  workbook.sheetFilter = "";
  workbook.conflictOnly = false;
  workbook.correctionOnly = false;
  workbook.lastExcludedCorrections = [];
  workbook.previewWarnings = (result.warnings || []).filter(
    (warning) => !/^检测到 \d+ 行数据需要修正$/.test(warning),
  );

  const sheet = result.sheet_name ? ` · 工作表「${result.sheet_name}」` : "";
  document.querySelector("#import-preview-summary").textContent = multiSheet
    ? `${result.file_name} · 已合并 ${workbook.selectedSheets.length} 个工作表 · 共 ${result.total_rows} 行`
    : `${result.file_name}${sheet} · 第 ${result.header_row} 行为表头 · 共 ${result.total_rows} 行`;
  document.querySelector("#import-legacy-mapping").classList.toggle("hidden", multiSheet);
  document.querySelector("#refresh-import-preview").classList.toggle("hidden", multiSheet);
  document.querySelector("#add-import-row").classList.toggle("hidden", multiSheet);
  document.querySelector("#import-preview-filters").classList.toggle("hidden", !multiSheet);
  document.querySelector("#import-mapping-grid").innerHTML = (result.mapping || []).map((item) => {
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
  document.querySelector("#import-sheet-filter").innerHTML = '<option value="">全部工作表</option>' + (multiSheet
    ? workbook.selectedSheets.map((name) => `<option value="${Matrix.escapeHtml(name)}">${Matrix.escapeHtml(name)}</option>`).join("")
    : "");
  document.querySelector("#import-conflict-only").checked = false;
  document.querySelector("#import-correction-only").checked = false;
  renderImportRows();
  document.querySelector("#import-preview").classList.remove("hidden");
}

async function previewImport(includeOptions = false) {
  if (!state.importFile) return;
  const workflowRevision = advanceImportWorkflow();
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
    if (!isCurrentImportWorkflow(workflowRevision)) return;
    renderImportPreview(result);
    document.querySelector("#import-preview").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (!isCurrentImportWorkflow(workflowRevision)) return;
    Matrix.toast("识别失败", error.message, "error");
  } finally {
    if (isCurrentImportWorkflow(workflowRevision)) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function confirmSmartImport() {
  if (!state.importFile || !state.importPreview) return;
  if (!ImportWorkbook.canImport(state.importWorkbook?.rows || [])) {
    Matrix.toast("无法导入", "请至少保留一条完整记录，并先解决重复 SKU。", "error");
    return;
  }
  const workflowRevision = advanceImportWorkflow();
  const button = document.querySelector("#confirm-import");
  button.disabled = true;
  button.textContent = "正在导入…";
  try {
    const result = await Matrix.api("/api/imports/product-offers", {
      method: "POST",
      body: importFormData(true, true),
    });
    if (!isCurrentImportWorkflow(workflowRevision)) return;
    Matrix.toast("导入完成", `成功 ${result.success_rows} 条，失败 ${result.error_rows} 条。`, result.error_rows ? "default" : "success");
    state.importFile = null;
    resetImportInterface();
    document.querySelector("#csv-file").value = "";
    document.querySelector("#import-description").value = "";
    document.querySelector("#selected-import-file").textContent = "支持 CSV、XLSX、XLS、PDF，单文件最大 10MB。";
    document.querySelector("#csv-dropzone").classList.remove("has-file");
    document.querySelector("#analyze-import").classList.remove("hidden");
    document.querySelector("#analyze-import").disabled = true;
    await Promise.all([loadImports(), loadProducts()]);
    if (await loadOfferBrands()) await loadOffers();
  } catch (error) {
    if (!isCurrentImportWorkflow(workflowRevision)) return;
    Matrix.toast("导入失败", error.message, "error");
  } finally {
    if (isCurrentImportWorkflow(workflowRevision)) {
      button.disabled = !ImportWorkbook.canImport(state.importWorkbook?.rows || []);
      button.textContent = "确认导入";
    }
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
  document.querySelector("#offer-product-id").addEventListener("change", (event) => {
    refreshOfferPriceLabel(event.target.value);
  });
  document.querySelector("#product-form").addEventListener("submit", submitProduct);
  document.querySelector("#offer-form").addEventListener("submit", submitOffer);
  document.querySelector("#profile-form").addEventListener("submit", saveProfile);
  document.querySelectorAll("[data-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => button.closest("dialog").close());
  });

  document.querySelector("#products-search").addEventListener("input", debounce((event) => loadProducts(event.target.value)));
  document.querySelector("#offers-search").addEventListener("input", debounce((event) => loadOffers(event.target.value)));
  document.querySelector("#offers-brand").addEventListener("change", (event) => loadOffers(null, event.target.value));
  document.querySelector("#products-prev-page").addEventListener("click", () => {
    state.productPage = Math.max(1, state.productPage - 1);
    renderProducts();
  });
  document.querySelector("#products-next-page").addEventListener("click", () => {
    state.productPage += 1;
    renderProducts();
  });
  document.querySelector("#offers-prev-page").addEventListener("click", () => {
    state.offerPage = Math.max(1, state.offerPage - 1);
    renderOffers();
  });
  document.querySelector("#offers-next-page").addEventListener("click", () => {
    state.offerPage += 1;
    renderOffers();
  });

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
  document.querySelector("#preview-selected-sheets").addEventListener("click", previewSelectedSheets);
  document.querySelector("#select-all-sheets").addEventListener("click", () => {
    const workbook = state.importWorkbook;
    if (!workbook?.inspection) return;
    const allNames = workbook.inspection.sheets.map((sheet) => sheet.name);
    workbook.selectedSheets = workbook.selectedSheets.length === allNames.length ? [] : allNames;
    invalidateWorkbookPreview();
    renderWorkbookConfiguration();
  });
  document.querySelector("#import-sheet-list").addEventListener("change", (event) => {
    const checkbox = event.target.closest("[data-sheet-name]");
    if (!checkbox || !state.importWorkbook) return;
    ImportWorkbook.toggleSheet(state.importWorkbook, checkbox.dataset.sheetName, checkbox.checked);
    invalidateWorkbookPreview();
    renderWorkbookConfiguration();
  });
  const sheetConfigs = document.querySelector("#import-sheet-configs");
  sheetConfigs.addEventListener("input", (event) => {
    const card = event.target.closest("[data-sheet-config]");
    if (!card || !state.importWorkbook) return;
    const config = state.importWorkbook.configs[card.dataset.sheetConfig];
    if (event.target.matches("[data-sheet-header-row]")) {
      config.header_row = Number(event.target.value);
    } else if (event.target.matches("[data-sheet-default-field]")) {
      const field = event.target.dataset.sheetDefaultField;
      const value = event.target.value.trim();
      if (value) config.defaults[field] = value;
      else delete config.defaults[field];
    } else {
      return;
    }
    invalidateWorkbookPreview();
  });
  sheetConfigs.addEventListener("change", (event) => {
    if (!event.target.matches("[data-sheet-mapping-field]")) return;
    const card = event.target.closest("[data-sheet-config]");
    const config = state.importWorkbook?.configs[card?.dataset.sheetConfig];
    if (!config) return;
    const field = event.target.dataset.sheetMappingField;
    if (event.target.value) config.mapping[field] = event.target.value;
    else delete config.mapping[field];
    invalidateWorkbookPreview();
  });
  document.querySelector("#refresh-import-preview").addEventListener("click", () => previewImport(true));
  document.querySelector("#add-import-row").addEventListener("click", () => {
    if (!state.importWorkbook || state.importWorkbook.inspection) return;
    const nextSourceRow = state.importWorkbook.rows.reduce((maximum, row) => Math.max(maximum, Number(row.source_row) || 0), 0) + 1;
    state.importWorkbook.rows.push({
      source_sheet: null,
      source_row: nextSourceRow,
      included: true,
      conflict_group: null,
      values: blankImportValues(),
      errors: [],
    });
    state.importWorkbook.page = Math.max(1, Math.ceil(state.importWorkbook.rows.length / state.importWorkbook.pageSize));
    renderImportRows();
  });
  document.querySelector("#confirm-import").addEventListener("click", confirmSmartImport);
  document.querySelector("#import-preview-tbody").addEventListener("click", (event) => {
    const toggleButton = event.target.closest("[data-toggle-import-row]");
    const deleteButton = event.target.closest("[data-delete-import-row]");
    if (!state.importWorkbook || (!toggleButton && !deleteButton)) return;
    const rowIndex = Number((toggleButton || deleteButton).dataset.toggleImportRow ?? deleteButton?.dataset.deleteImportRow);
    if (toggleButton) {
      const row = state.importWorkbook.rows[rowIndex];
      if (!row) return;
      row.included = !row.included;
      ImportWorkbook.resolveRows(state.importWorkbook.rows);
    } else {
      state.importWorkbook.rows.splice(rowIndex, 1);
      ImportWorkbook.resolveRows(state.importWorkbook.rows);
    }
    renderImportRows();
  });
  document.querySelector("#import-preview-tbody").addEventListener("input", (event) => {
    if (!event.target.matches("[data-row-field]") || !state.importWorkbook) return;
    const rowIndex = Number(event.target.dataset.rowIndex);
    const row = state.importWorkbook.rows[rowIndex];
    if (!row) return;
    row.errors = [];
    ImportWorkbook.updateRow(state.importWorkbook, rowIndex, event.target.dataset.rowField, event.target.value.trim());
    if (
      state.importWorkbook.correctionOnly
      || (state.importWorkbook.conflictOnly && event.target.dataset.rowField === "supplier_sku")
    ) {
      renderImportRows();
    } else {
      refreshRenderedRowStates();
    }
  });
  document.querySelector("#import-sheet-filter").addEventListener("change", (event) => {
    if (!state.importWorkbook) return;
    state.importWorkbook.sheetFilter = event.target.value;
    state.importWorkbook.page = 1;
    renderImportRows();
  });
  document.querySelector("#import-conflict-only").addEventListener("change", (event) => {
    if (!state.importWorkbook) return;
    state.importWorkbook.conflictOnly = event.target.checked;
    state.importWorkbook.page = 1;
    renderImportRows();
  });
  document.querySelector("#import-correction-only").addEventListener("change", (event) => {
    if (!state.importWorkbook) return;
    state.importWorkbook.correctionOnly = event.target.checked;
    state.importWorkbook.page = 1;
    renderImportRows();
  });
  document.querySelector("#exclude-correction-rows").addEventListener("click", () => {
    if (!state.importWorkbook) return;
    ImportWorkbook.excludeCorrectionRows(state.importWorkbook);
    state.importWorkbook.page = 1;
    renderImportRows();
  });
  document.querySelector("#restore-correction-rows").addEventListener("click", () => {
    if (!state.importWorkbook) return;
    ImportWorkbook.restoreExcludedCorrections(state.importWorkbook);
    state.importWorkbook.page = 1;
    renderImportRows();
  });
  document.querySelector("#import-prev-page").addEventListener("click", () => {
    if (!state.importWorkbook) return;
    state.importWorkbook.page = Math.max(1, state.importWorkbook.page - 1);
    renderImportRows();
  });
  document.querySelector("#import-next-page").addEventListener("click", () => {
    if (!state.importWorkbook) return;
    state.importWorkbook.page += 1;
    renderImportRows();
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

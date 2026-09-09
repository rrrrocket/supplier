(() => {
  let page = 1;
  let pageSize = 50;

  const value = (selector) => document.querySelector(selector).value.trim();
  const chips = (items) => (items || []).map(
    (item) => `<span class="chip">${Matrix.escapeHtml(item)}</span>`,
  ).join("");

  function queryString() {
    const params = new URLSearchParams({ page, page_size: pageSize });
    const filters = {
      keyword: value("#operator-directory-keyword"),
      category: value("#operator-directory-category"),
      region: value("#operator-directory-region"),
      operator_type: value("#operator-directory-type"),
      erp_name: value("#operator-directory-erp"),
    };
    Object.entries(filters).forEach(([key, item]) => item && params.set(key, item));
    return params.toString();
  }

  async function showContact(operatorId) {
    try {
      const item = await Matrix.api(`/api/public/operators/${operatorId}`);
      document.querySelector("#operator-contact-title").textContent = item.operator_name;
      document.querySelector("#operator-contact-content").innerHTML = `
        <div class="info-list">
          <div class="info-row"><span>联系人</span><strong>${Matrix.escapeHtml(item.contact_name || "—")}</strong></div>
          <div class="info-row"><span>电话</span><strong>${Matrix.escapeHtml(item.contact_phone || "—")}</strong></div>
          <div class="info-row"><span>邮箱</span><strong>${Matrix.escapeHtml(item.contact_email || "—")}</strong></div>
          <div class="info-row"><span>网站</span><strong>${Matrix.escapeHtml(item.website || "—")}</strong></div>
        </div>`;
      document.querySelector("#operator-contact-dialog").showModal();
    } catch (error) {
      Matrix.toast("无法查看联系方式", error.message, "error");
    }
  }

  async function loadOperators() {
    const root = document.querySelector("#operator-directory");
    root.innerHTML = '<div class="table-empty">正在加载运营商…</div>';
    try {
      const data = await Matrix.api(`/api/public/operators?${queryString()}`);
      root.innerHTML = data.items.length ? data.items.map((item) => `
        <article class="panel directory-card operator-directory-card">
          <div class="panel-body">
            <div class="directory-card-top"><span class="badge badge-approved">${Matrix.escapeHtml(item.operator_type || "运营服务商")}</span><span>${Matrix.escapeHtml(item.erp_name || "ERP 待补充")}</span></div>
            <h2>${Matrix.escapeHtml(item.operator_name)}</h2>
            <p>${Matrix.escapeHtml([item.province, item.city].filter(Boolean).join(" · ") || "地区待补充")}</p>
            <div class="directory-group"><span>服务类目</span><div class="chip-row">${chips(item.categories) || '<span class="table-secondary">待补充</span>'}</div></div>
            <div class="directory-group"><span>销售渠道</span><div class="chip-row">${chips(item.sales_channels) || '<span class="table-secondary">待补充</span>'}</div></div>
            <div class="directory-group"><span>目标市场</span><div class="chip-row">${chips(item.target_markets) || '<span class="table-secondary">待补充</span>'}</div></div>
            <button class="btn btn-secondary directory-contact-button" type="button" data-operator-contact="${item.operator_id}">查看联系方式</button>
          </div>
        </article>`).join("") : '<div class="table-empty">没有符合条件的运营商</div>';
      root.querySelectorAll("[data-operator-contact]").forEach(
        (button) => button.addEventListener("click", () => showContact(button.dataset.operatorContact)),
      );
      MatrixPagination.render(document.querySelector("#operator-directory-pagination"), {
        total: data.total,
        page: data.page,
        pageSize: data.page_size,
        onChange(nextPage, nextSize) {
          page = nextPage;
          pageSize = nextSize;
          loadOperators();
        },
      });
    } catch (error) {
      root.innerHTML = `<div class="table-empty">${Matrix.escapeHtml(error.message)}</div>`;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelector("#operator-directory-search").addEventListener("click", () => {
      page = 1;
      loadOperators();
    });
    document.querySelectorAll("[data-close-operator-contact]").forEach(
      (button) => button.addEventListener("click", () => document.querySelector("#operator-contact-dialog").close()),
    );
    loadOperators();
  });
})();

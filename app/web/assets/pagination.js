(function initPagination(window) {
  function model(total, requestedSize, requestedPage) {
    const pageSize = [20, 50, 100, 200].includes(Number(requestedSize)) ? Number(requestedSize) : 50;
    const pages = Math.max(1, Math.ceil(Math.max(0, Number(total) || 0) / pageSize));
    const page = Math.min(pages, Math.max(1, Number(requestedPage) || 1));
    const start = total ? (page - 1) * pageSize + 1 : 0;
    const end = total ? Math.min(page * pageSize, total) : 0;
    const visible = new Set([1, pages]);
    if (pages <= 7) {
      for (let value = 1; value <= pages; value += 1) visible.add(value);
    } else if (page <= 4) {
      for (let value = 2; value <= 6; value += 1) visible.add(value);
    } else if (page >= pages - 3) {
      for (let value = pages - 5; value < pages; value += 1) visible.add(value);
    } else {
      for (let value = page - 2; value <= page + 2; value += 1) visible.add(value);
    }
    const ordered = [...visible].filter((value) => value > 0).sort((left, right) => left - right);
    const labels = [];
    ordered.forEach((value, index) => {
      if (index && value - ordered[index - 1] > 1) labels.push("…");
      labels.push(value);
    });
    return { total: Math.max(0, Number(total) || 0), page, pageSize, pages, start, end, labels };
  }

  function formatNumber(value) {
    return String(Number(value));
  }

  function markup(pageModel) {
    const sizes = [20, 50, 100, 200];
    const pageButtons = pageModel.labels.map((label) => label === "…"
      ? '<span class="pager-ellipsis" aria-hidden="true">…</span>'
      : `<button class="pager-page${label === pageModel.page ? " active" : ""}" type="button" data-page="${label}"${label === pageModel.page ? ' aria-current="page"' : ""}>${label}</button>`).join("");
    return `<label class="pager-size"><span>页面行数：</span><select data-page-size aria-label="页面行数">${sizes.map((size) => `<option value="${size}"${size === pageModel.pageSize ? " selected" : ""}>${size}</option>`).join("")}</select></label><nav class="pager-pages" aria-label="分页"><button class="pager-arrow" type="button" data-page="${pageModel.page - 1}" aria-label="上一页"${pageModel.page === 1 ? " disabled" : ""}>‹</button>${pageButtons}<button class="pager-arrow" type="button" data-page="${pageModel.page + 1}" aria-label="下一页"${pageModel.page === pageModel.pages ? " disabled" : ""}>›</button></nav><span class="pager-range">${formatNumber(pageModel.start)}–${formatNumber(pageModel.end)} / ${formatNumber(pageModel.total)}</span>`;
  }

  function render(container, options) {
    const pageModel = model(options.total, options.pageSize, options.page);
    container.innerHTML = markup(pageModel);
    container.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => options.onChange(Number(button.dataset.page), pageModel.pageSize)));
    container.querySelector("[data-page-size]").addEventListener("change", (event) => options.onChange(1, Number(event.target.value)));
    return pageModel;
  }

  window.MatrixPagination = { markup, model, render };
}(window));

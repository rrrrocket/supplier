(() => {
  const state = {
    initialized: false,
    items: [],
    page: 1,
    pageSize: 50,
    requestRevision: 0,
  };

  function tokenValue() {
    return document.querySelector("#supplier-token-value");
  }

  function clearSupplierToken() {
    const value = tokenValue();
    if (value) value.textContent = "";
  }

  function showSupplierToken(token) {
    clearSupplierToken();
    tokenValue().textContent = String(token || "");
    document.querySelector("#supplier-token-dialog").showModal();
  }

  function visibleClient(client) {
    const { token: _plaintextToken, ...visible } = client;
    return visible;
  }

  function renderSupplierClients() {
    const tbody = document.querySelector("#supplier-clients-tbody");
    tbody.innerHTML = state.items.length ? state.items.map((item) => {
      const expired = item.expires_at && new Date(item.expires_at).getTime() <= Date.now();
      const usable = item.is_active && !expired;
      return `<tr>
        <td><div class="table-primary">${Matrix.escapeHtml(item.name)}</div></td>
        <td><code>${Matrix.escapeHtml(item.token_prefix)}</code></td>
        <td><div class="tag-list">${(item.scopes || []).map((scope) => `<span class="tag">${Matrix.escapeHtml(scope)}</span>`).join("")}</div></td>
        <td>${item.expires_at ? Matrix.formatDate(item.expires_at, true) : "永不过期"}</td>
        <td>${item.last_used_at ? Matrix.formatDate(item.last_used_at, true) : "尚未使用"}</td>
        <td>${Matrix.statusBadge(expired ? "EXPIRED" : (item.is_active ? "ACTIVE" : "INACTIVE"))}</td>
        <td class="text-right"><div class="row">
          <button class="btn btn-secondary btn-sm" type="button" data-rotate="${Matrix.escapeHtml(item.id)}"${usable ? "" : " disabled"}>轮换</button>
          <button class="btn btn-danger btn-sm" type="button" data-revoke="${Matrix.escapeHtml(item.id)}"${item.is_active ? "" : " disabled"}>撤销</button>
        </div></td>
      </tr>`;
    }).join("") : '<tr><td colspan="7" class="table-empty"><strong>还没有只读 API 凭证</strong>创建后，明文 token 只展示一次。</td></tr>';

    MatrixPagination.render(document.querySelector("#supplier-client-pagination"), {
      total: state.total,
      page: state.page,
      pageSize: state.pageSize,
      onChange(nextPage, nextPageSize) {
        state.page = nextPage;
        state.pageSize = nextPageSize;
        return loadSupplierClients();
      },
    });
  }

  async function loadSupplierClients() {
    const revision = ++state.requestRevision;
    try {
      const data = await Matrix.api(`/api/supplier/integration-clients?page=${state.page}&page_size=${state.pageSize}`);
      if (revision !== state.requestRevision) return false;
      state.items = (data.items || []).map(visibleClient);
      state.total = data.total;
      state.page = data.page;
      state.pageSize = data.page_size;
      renderSupplierClients();
      return true;
    } catch (error) {
      if (revision === state.requestRevision) {
        Matrix.toast("凭证加载失败", error.message, "error");
      }
      return false;
    }
  }

  async function submitSupplierClient(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const scopes = [...form.querySelectorAll('[name="scopes"]:checked')].map((input) => input.value);
    if (!scopes.length) {
      Matrix.toast("请选择权限", "至少选择一个只读权限。", "error");
      return;
    }
    const expiresInput = form.elements.expires_at;
    const expiresAt = expiresInput?.value ? new Date(expiresInput.value).toISOString() : null;
    clearSupplierToken();
    try {
      const result = await Matrix.api("/api/supplier/integration-clients", {
        method: "POST",
        body: {
          name: form.elements.name.value,
          scopes,
          expires_at: expiresAt,
        },
      });
      showSupplierToken(result.token);
      form.reset();
      await loadSupplierClients();
    } catch (error) {
      Matrix.toast("凭证创建失败", error.message, "error");
    }
  }

  async function rotateSupplierClient(clientId) {
    clearSupplierToken();
    try {
      const result = await Matrix.api(`/api/supplier/integration-clients/${clientId}/rotate`, {
        method: "POST",
      });
      showSupplierToken(result.token);
      await loadSupplierClients();
    } catch (error) {
      Matrix.toast("凭证轮换失败", error.message, "error");
    }
  }

  async function revokeSupplierClient(clientId) {
    if (!confirm("确认撤销这个只读 API 凭证？撤销后无法恢复。")) return;
    try {
      await Matrix.api(`/api/supplier/integration-clients/${clientId}/revoke`, {
        method: "POST",
      });
      Matrix.toast("凭证已撤销", "该凭证已无法继续访问 ERP API。", "success");
      await loadSupplierClients();
    } catch (error) {
      Matrix.toast("凭证撤销失败", error.message, "error");
    }
  }

  function handleClientAction(event) {
    const button = event.target.closest("[data-rotate], [data-revoke]");
    if (!button) return undefined;
    if (button.dataset.rotate) return rotateSupplierClient(button.dataset.rotate);
    if (button.dataset.revoke) return revokeSupplierClient(button.dataset.revoke);
    return undefined;
  }

  function init() {
    if (state.initialized || !document.querySelector("#supplier-client-form")) return;
    state.initialized = true;
    document.querySelector("#supplier-client-form").addEventListener("submit", submitSupplierClient);
    document.querySelector("#supplier-clients-tbody").addEventListener("click", handleClientAction);
    const dialog = document.querySelector("#supplier-token-dialog");
    dialog.addEventListener("close", clearSupplierToken);
    dialog.addEventListener("cancel", clearSupplierToken);
    document.querySelectorAll("[data-close-supplier-token]").forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    document.querySelector("#copy-supplier-token").addEventListener("click", () => {
      navigator.clipboard.writeText(tokenValue().textContent);
    });
    window.addEventListener("hashchange", () => {
      if (window.location.hash !== "#erp-integration") clearSupplierToken();
    });
    window.addEventListener("pagehide", clearSupplierToken);
  }

  window.SupplierIntegration = {
    clearSupplierToken,
    init,
    loadSupplierClients,
    renderSupplierClients,
    showSupplierToken,
  };

  document.addEventListener("DOMContentLoaded", init);
})();

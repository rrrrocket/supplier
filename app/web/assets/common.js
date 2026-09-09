(() => {
  const statusLabels = {
    ACTIVE: "有效",
    APPROVED: "已通过",
    COMPLETED: "已完成",
    DRAFT: "草稿",
    PENDING: "待审核",
    PAUSED: "已暂停",
    PARTIAL: "部分成功",
    ARCHIVED: "已归档",
    EXPIRED: "已过期",
    FAILED: "失败",
    REJECTED: "已驳回",
    SUSPENDED: "已停用",
  };

  const eventLabels = {
    BRAND_CREATED: ["新建品牌", "平台品牌目录已更新"],
    INTEGRATION_SKU_COSTS_QUERIED: ["查询 SKU 成本", "集成调用方已查询当前成本"],
    OFFER_CREATED: ["新建报价", "报价已进入供应网络"],
    OFFER_UPDATED: ["更新报价", "价格、库存或交期发生更新"],
    PRODUCT_CREATED: ["新建商品", "商品主数据已创建"],
    PRODUCT_OFFERS_IMPORTED: ["批量导入", "商品与报价数据已处理"],
    SUPPLIER_APPROVED: ["供应商审核通过", "供应能力档案已激活"],
    SUPPLIER_APPLICATION_APPROVED: ["入驻申请通过", "供应商组织与供应商账号已创建"],
    SUPPLIER_APPLICATION_REJECTED: ["入驻申请驳回", "平台已保存审核意见"],
    SUPPLIER_BRAND_COOPERATION_CHANGED: ["更新品牌合作", "供应商当前品牌合作模式已更新"],
    SUPPLIER_PROFILE_UPDATED: ["更新企业资料", "供应商能力档案已更新"],
    USER_LOGGED_IN: ["账号登录", "供应商工作台登录成功"],
    USER_LOGGED_OUT: ["账号退出", "已安全退出工作台"],
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  async function api(path, options = {}) {
    const request = { credentials: "same-origin", ...options };
    request.headers = { Accept: "application/json", ...(options.headers || {}) };

    if (request.body && !(request.body instanceof FormData) && typeof request.body !== "string") {
      request.headers["Content-Type"] = "application/json";
      request.body = JSON.stringify(request.body);
    }

    const response = await fetch(path, request);
    if (response.status === 204) return null;

    const contentType = response.headers.get("content-type") || "";
    const data = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      const message = typeof data === "object" && data?.detail
        ? (Array.isArray(data.detail) ? data.detail.map((item) => item.msg).join("；") : data.detail)
        : "请求失败，请稍后重试";
      const error = new Error(message);
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function toast(title, message = "", type = "default") {
    let region = document.querySelector(".toast-region");
    if (!region) {
      region = document.createElement("div");
      region.className = "toast-region";
      document.body.appendChild(region);
    }
    const item = document.createElement("div");
    item.className = `toast ${type}`;
    item.innerHTML = `
      <div class="toast-icon">${type === "success" ? "✓" : type === "error" ? "!" : "i"}</div>
      <div><strong>${escapeHtml(title)}</strong>${message ? `<span>${escapeHtml(message)}</span>` : ""}</div>
    `;
    region.appendChild(item);
    window.setTimeout(() => item.remove(), 4200);
  }

  function formatDate(value, includeTime = false) {
    if (!value) return "—";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      ...(includeTime ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
    }).format(date);
  }

  function formatMoney(value, currency = "CNY") {
    const amount = Number(value);
    if (!Number.isFinite(amount)) return "—";
    try {
      return new Intl.NumberFormat("zh-CN", {
        style: "currency",
        currency,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      return `${currency} ${amount.toFixed(2)}`;
    }
  }

  function statusBadge(status) {
    const key = String(status || "DRAFT").toUpperCase();
    return `<span class="badge badge-${key.toLowerCase()}">${escapeHtml(statusLabels[key] || key)}</span>`;
  }

  function eventInfo(eventType) {
    return eventLabels[eventType] || [eventType || "系统事件", "业务数据已更新"];
  }

  function publicAuthView(user) {
    const isPlatformAdmin = user?.role === "PLATFORM_ADMIN"
      && user?.organization_type === "PLATFORM";
    const isSupplier = user?.role === "SUPPLIER"
      && user?.organization_type === "SUPPLIER";
    const isOperator = user?.role === "OPERATOR"
      && user?.organization_type === "OPERATOR";
    if (!isPlatformAdmin && !isSupplier && !isOperator) {
      return {
        authenticated: false,
        identityLabel: "",
        workspaceHref: "",
        workspaceLabel: "",
      };
    }
    return {
      authenticated: true,
      identityLabel: user.organization_name || user.name,
      workspaceHref: isPlatformAdmin ? "/admin" : isOperator ? "/operator" : "/app",
      workspaceLabel: isPlatformAdmin ? "进入管理端" : "进入工作台",
    };
  }

  function renderPublicAuth(user) {
    const view = publicAuthView(user);
    document.querySelectorAll("[data-auth-guest]").forEach((node) => {
      node.hidden = view.authenticated;
    });
    document.querySelectorAll("[data-auth-member]").forEach((node) => {
      node.hidden = !view.authenticated;
    });
    document.querySelectorAll("[data-auth-identity]").forEach((node) => {
      node.textContent = view.identityLabel;
      node.title = view.identityLabel;
      node.href = view.workspaceHref;
    });
    document.querySelectorAll("[data-auth-workspace]").forEach((node) => {
      node.textContent = view.workspaceLabel;
      node.href = view.workspaceHref;
    });
  }

  async function syncPublicAuth() {
    try {
      const user = await api("/api/auth/me", { cache: "no-store" });
      const view = publicAuthView(user);
      if (document.body.dataset.authRedirect === "workspace" && view.authenticated) {
        window.location.replace(view.workspaceHref);
        return user;
      }
      renderPublicAuth(user);
      return user;
    } catch {
      renderPublicAuth(null);
      return null;
    }
  }

  function setYear() {
    document.querySelectorAll("[data-current-year]").forEach((node) => {
      node.textContent = new Date().getFullYear();
    });
  }

  function userRoleLabel(user) {
    if (user?.role === "PLATFORM_ADMIN") return "平台管理员";
    if (user?.role === "SUPPLIER") return "供应商";
    if (user?.role === "OPERATOR") return "运营商";
    return "";
  }

  window.Matrix = {
    api,
    escapeHtml,
    eventInfo,
    formatDate,
    formatMoney,
    publicAuthView,
    setYear,
    statusBadge,
    statusLabels,
    syncPublicAuth,
    toast,
    userRoleLabel,
  };

  document.addEventListener("DOMContentLoaded", () => {
    setYear();
    const usesPublicAuth = document.body.dataset.authRedirect === "workspace"
      || document.querySelector("[data-auth-guest], [data-auth-member]");
    if (usesPublicAuth) syncPublicAuth();
  });
})();

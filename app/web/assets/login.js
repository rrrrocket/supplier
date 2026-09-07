document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#login-form");
  const submit = document.querySelector("#login-submit");
  const message = document.querySelector("#login-message");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    message.textContent = "";
    submit.disabled = true;
    submit.textContent = "正在登录…";

    const data = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await Matrix.api("/api/auth/login", { method: "POST", body: data });
      const view = Matrix.publicAuthView(result.user);
      if (!view.authenticated) {
        await Matrix.api("/api/auth/logout", { method: "POST" });
        throw new Error("账号角色或组织类型无效，请联系平台管理员");
      }
      window.location.href = view.workspaceHref;
    } catch (error) {
      message.textContent = error.message;
    } finally {
      submit.disabled = false;
      submit.textContent = "登录工作台";
    }
  });
});

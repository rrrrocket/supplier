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
      window.location.href = result.user.role === "PLATFORM_ADMIN" ? "/admin" : "/app";
    } catch (error) {
      message.textContent = error.message;
    } finally {
      submit.disabled = false;
      submit.textContent = "登录工作台";
    }
  });
});

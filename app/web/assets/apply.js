document.addEventListener("DOMContentLoaded", () => {
  const form = document.querySelector("#supplier-application-form");
  const steps = [...document.querySelectorAll(".apply-step")];
  const indicators = [...document.querySelectorAll(".step-item")];
  const backButton = document.querySelector("#step-back");
  const nextButton = document.querySelector("#step-next");
  const submitButton = document.querySelector("#application-submit");
  const actions = document.querySelector("#application-actions");
  const message = document.querySelector("#application-message");
  let currentStep = 0;

  function updateStep() {
    steps.forEach((step, index) => step.classList.toggle("active", index === currentStep));
    indicators.forEach((item, index) => {
      item.classList.toggle("active", index === currentStep);
      item.classList.toggle("done", index < currentStep);
      const bullet = item.querySelector(".step-bullet");
      bullet.textContent = index < currentStep ? "✓" : String(index + 1);
    });
    backButton.classList.toggle("hidden", currentStep === 0);
    nextButton.classList.toggle("hidden", currentStep === steps.length - 1);
    submitButton.classList.toggle("hidden", currentStep !== steps.length - 1);
    message.textContent = "";
    if (currentStep === steps.length - 1) buildReview();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function validateCurrentStep() {
    const fields = [...steps[currentStep].querySelectorAll("input, select, textarea")];
    let valid = true;
    const checkboxGroups = new Set();

    for (const field of fields) {
      field.removeAttribute("aria-invalid");
      if (field.type === "checkbox" && field.required) {
        checkboxGroups.add(field.name);
        continue;
      }
      if (!field.checkValidity()) {
        field.setAttribute("aria-invalid", "true");
        valid = false;
      }
    }

    for (const name of checkboxGroups) {
      const checked = form.querySelectorAll(`input[name="${name}"]:checked`).length > 0;
      if (!checked) valid = false;
    }

    if (currentStep === 1 && !form.querySelector('input[name="categories"]:checked')) {
      valid = false;
    }
    if (currentStep === 2 && !form.querySelector('input[name="cooperation_modes"]:checked')) {
      valid = false;
    }

    if (!valid) message.textContent = "请完整填写当前步骤中的必填信息。";
    return valid;
  }

  function selectedLabels(name) {
    return [...form.querySelectorAll(`input[name="${name}"]:checked`)]
      .map((input) => input.value)
      .join("、") || "—";
  }

  function yesNo(name) {
    return form.elements[name]?.checked ? "是" : "否";
  }

  function buildReview() {
    const data = new FormData(form);
    const rows = [
      ["企业名称", data.get("company_name")],
      ["企业类型", data.get("company_type")],
      ["所在地", `${data.get("province") || ""} ${data.get("city") || ""}`],
      ["联系人", `${data.get("contact_name") || ""} / ${data.get("phone") || ""}`],
      ["邮箱", data.get("email")],
      ["主营类目", selectedLabels("categories")],
      ["合作方式", selectedLabels("cooperation_modes")],
      ["一件代发", yesNo("supports_dropshipping")],
      ["OEM/定制", yesNo("supports_oem")],
      ["出口经验", yesNo("has_export_experience")],
    ];
    document.querySelector("#review-grid").innerHTML = rows
      .map(([label, value]) => `<div class="review-item"><span>${Matrix.escapeHtml(label)}</span><strong>${Matrix.escapeHtml(value || "—")}</strong></div>`)
      .join("");
  }

  function payloadFromForm() {
    const data = new FormData(form);
    return {
      company_name: data.get("company_name"),
      unified_social_credit_code: data.get("unified_social_credit_code") || null,
      company_type: data.get("company_type"),
      province: data.get("province"),
      city: data.get("city"),
      contact_name: data.get("contact_name"),
      phone: data.get("phone"),
      email: data.get("email"),
      categories: [...form.querySelectorAll('input[name="categories"]:checked')].map((item) => item.value),
      cooperation_modes: [...form.querySelectorAll('input[name="cooperation_modes"]:checked')].map((item) => item.value),
      annual_revenue_range: data.get("annual_revenue_range") || null,
      supports_dropshipping: form.elements.supports_dropshipping.checked,
      supports_oem: form.elements.supports_oem.checked,
      has_export_experience: form.elements.has_export_experience.checked,
      message: data.get("message") || null,
    };
  }

  nextButton.addEventListener("click", () => {
    if (!validateCurrentStep()) return;
    currentStep += 1;
    updateStep();
  });
  backButton.addEventListener("click", () => {
    currentStep = Math.max(0, currentStep - 1);
    updateStep();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!validateCurrentStep()) return;
    submitButton.disabled = true;
    submitButton.textContent = "正在提交…";
    try {
      const result = await Matrix.api("/api/public/applications", {
        method: "POST",
        body: payloadFromForm(),
      });
      actions.classList.add("hidden");
      form.querySelectorAll(".apply-step").forEach((item) => item.classList.remove("active"));
      const success = document.querySelector("#application-success");
      success.classList.remove("hidden");
      document.querySelector("#application-no").textContent = result.application_no;
      indicators.forEach((item) => {
        item.classList.remove("active");
        item.classList.add("done");
        item.querySelector(".step-bullet").textContent = "✓";
      });
    } catch (error) {
      message.textContent = error.message;
      Matrix.toast("提交失败", error.message, "error");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "提交入驻申请";
    }
  });

  updateStep();
});

const itemForm = document.querySelector("[data-item-form]");
if (itemForm) {
  const flow = itemForm.elements.namedItem("flow_type");
  const amountFields = itemForm.querySelectorAll("[data-amount-for]");

  function syncAmountFields() {
    for (const field of amountFields) {
      const input = field.querySelector("input");
      const visible = field.dataset.amountFor === flow.value;
      field.hidden = !visible;
      input.disabled = !visible;
      input.required = visible;
    }
  }

  flow.addEventListener("change", syncAmountFields);
  syncAmountFields();
}

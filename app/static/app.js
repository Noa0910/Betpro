function createAmountRow(value, options = {}) {
  const { amountName = "amount", locked = false, onRemove = null } = options;

  const row = document.createElement("div");
  row.className = "amount-row" + (locked ? " amount-row-locked" : "");

  const input = document.createElement("input");
  input.type = "number";
  input.step = "0.01";
  input.min = "0";
  input.name = amountName;
  input.placeholder = "0.00";
  input.className = "amount-input";
  input.value = value ?? "";
  input.dataset.field = "amount";
  if (locked) input.readOnly = true;
  row.appendChild(input);

  if (!locked) {
    const removeBtn = document.createElement("button");
    removeBtn.type = "button";
    removeBtn.className = "btn-remove";
    removeBtn.innerHTML = "&times;";
    removeBtn.title = "Eliminar";
    removeBtn.addEventListener("click", () => {
      row.remove();
      if (onRemove) onRemove();
    });
    row.appendChild(removeBtn);
  }

  return row;
}

function initAmountList(container, options = {}) {
  const { amountName = "amount", initialItems = [], locked = false } = options;

  const list = container.querySelector("[data-amount-list]");
  const addBtn = container.querySelector("[data-add-btn]");
  const totalEl = container.querySelector("[data-list-total]");

  function updateTotal() {
    if (!totalEl) return;
    let sum = 0;
    list.querySelectorAll('[data-field="amount"]').forEach((input) => {
      const val = parseFloat(input.value);
      if (!isNaN(val)) sum += val;
    });
    totalEl.textContent =
      "$" +
      sum.toLocaleString("es-MX", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      });
  }

  function addRow(value = "") {
    const row = createAmountRow(value, { amountName, locked, onRemove: updateTotal });
    row.querySelector('[data-field="amount"]')?.addEventListener("input", updateTotal);
    list.appendChild(row);
    updateTotal();
    if (!locked) row.querySelector('[data-field="amount"]')?.focus();
  }

  initialItems.forEach((item) => addRow(item.amount ?? item));
  if (!locked) addBtn?.addEventListener("click", () => addRow(""));
  updateTotal();
}

function initDiscountList(container) {
  const locked = container.dataset.locked === "true";
  const list = container.querySelector("[data-discount-list]");
  const addBtn = container.querySelector("[data-add-discount]");

  function addRow(desc = "", amount = "") {
    const row = document.createElement("div");
    row.className = "discount-row";
    row.innerHTML = `
      <input type="text" name="discount_desc" placeholder="Ej: Cuenta, Código" class="input-field" value="${desc}" ${locked ? "readonly" : ""}>
      <input type="number" step="0.01" min="0" name="discount_amount" placeholder="0.00" class="input-field" value="${amount}" ${locked ? "readonly" : ""}>
      ${locked ? "" : '<button type="button" class="btn-remove" title="Eliminar">&times;</button>'}
    `;
    if (!locked) {
      row.querySelector(".btn-remove")?.addEventListener("click", () => row.remove());
    }
    list.appendChild(row);
  }

  if (!locked) addBtn?.addEventListener("click", () => addRow());

  let initial = [];
  try {
    initial = JSON.parse(container.dataset.initial || "[]");
  } catch (_) {}
  initial.forEach((d) => addRow(d.description, d.amount));
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-amount-widget]").forEach((widget) => {
    let initial = [];
    try {
      initial = JSON.parse(widget.dataset.initial || "[]");
    } catch (_) {}

    initAmountList(widget, {
      amountName: widget.dataset.amountName,
      initialItems: initial,
      locked: widget.dataset.locked === "true",
    });
  });

  document.querySelectorAll("[data-discount-widget]").forEach((widget) => {
    initDiscountList(widget);
  });
});

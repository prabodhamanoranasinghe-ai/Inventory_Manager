function toNumber(value) {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function getCurrencySymbol() {
  return document.body?.dataset?.currencySymbol || "$";
}

function renderSalesChart() {
  const canvas = document.getElementById("salesChart");
  if (!canvas || typeof Chart === "undefined") return;

  const labels = JSON.parse(canvas.dataset.labels || "[]");
  const values = JSON.parse(canvas.dataset.values || "[]");

  // Global Chart object is loaded from CDN in base template.
  new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Revenue",
          data: values,
          borderColor: "#0d6efd",
          backgroundColor: "rgba(13, 110, 253, 0.15)",
          fill: true,
          tension: 0.25,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          ticks: {
            callback(value) {
              return `${getCurrencySymbol()}${value}`;
            },
          },
        },
      },
    },
  });
}

function recalculateInvoice() {
  const table = document.getElementById("lineItemsTable");
  if (!table) return;

  let subtotal = 0;
  table.querySelectorAll("tbody tr.invoice-row").forEach((row) => {
    const productSelect = row.querySelector(".line-product");
    const qtyInput = row.querySelector(".line-qty");
    const stockInput = row.querySelector(".line-stock");
    const priceInput = row.querySelector(".line-price");
    const totalInput = row.querySelector(".line-total");

    const selectedOption = productSelect.options[productSelect.selectedIndex];
    const unitPrice = toNumber(selectedOption?.dataset?.price);
    const stock = toNumber(selectedOption?.dataset?.stock);
    const qty = Math.max(toNumber(qtyInput.value), 0);
    const lineTotal = unitPrice * qty;

    stockInput.value = stock;
    priceInput.value = unitPrice.toFixed(2);
    totalInput.value = lineTotal.toFixed(2);
    subtotal += lineTotal;

    if (stock > 0 && qty > stock) {
      qtyInput.setCustomValidity(`Only ${stock} units available.`);
    } else {
      qtyInput.setCustomValidity("");
    }
  });

  const taxRate = toNumber(document.getElementById("taxRate")?.value);
  const discount = toNumber(document.getElementById("discount")?.value);
  const tax = subtotal * (taxRate / 100);
  const grandTotal = Math.max(subtotal + tax - discount, 0);

  const subtotalNode = document.getElementById("subtotalValue");
  const taxNode = document.getElementById("taxValue");
  const grandTotalNode = document.getElementById("grandTotalValue");
  if (subtotalNode) subtotalNode.textContent = subtotal.toFixed(2);
  if (taxNode) taxNode.textContent = tax.toFixed(2);
  if (grandTotalNode) grandTotalNode.textContent = grandTotal.toFixed(2);
}

function bindInvoiceRow(row) {
  row.querySelector(".line-product")?.addEventListener("change", recalculateInvoice);
  row.querySelector(".line-qty")?.addEventListener("input", recalculateInvoice);
  row.querySelector(".remove-line-btn")?.addEventListener("click", () => {
    const tbody = row.closest("tbody");
    if (tbody.querySelectorAll("tr.invoice-row").length > 1) {
      row.remove();
    } else {
      row.querySelector(".line-product").selectedIndex = 0;
      row.querySelector(".line-qty").value = 1;
    }
    recalculateInvoice();
  });
}

function initializeInvoiceForm() {
  const form = document.getElementById("invoiceForm");
  if (!form) return;

  const tbody = document.querySelector("#lineItemsTable tbody");
  const addLineButton = document.getElementById("addLineBtn");
  const productSearch = document.getElementById("billProductSearch");
  const taxRate = document.getElementById("taxRate");
  const discount = document.getElementById("discount");

  function filterProductOptions() {
    const term = (productSearch?.value || "").trim().toLowerCase();
    tbody.querySelectorAll(".line-product").forEach((select) => {
      select.querySelectorAll("option").forEach((option, index) => {
        if (index === 0) return;
        const text = option.textContent.toLowerCase();
        option.hidden = term.length > 0 && !text.includes(term);
      });
    });
  }

  tbody.querySelectorAll("tr.invoice-row").forEach(bindInvoiceRow);
  taxRate?.addEventListener("input", recalculateInvoice);
  discount?.addEventListener("input", recalculateInvoice);
  productSearch?.addEventListener("input", filterProductOptions);

  addLineButton?.addEventListener("click", () => {
    const templateRow = tbody.querySelector("tr.invoice-row");
    const cloned = templateRow.cloneNode(true);
    cloned.querySelector(".line-product").selectedIndex = 0;
    cloned.querySelector(".line-qty").value = 1;
    cloned.querySelector(".line-stock").value = "0";
    cloned.querySelector(".line-price").value = "0.00";
    cloned.querySelector(".line-total").value = "0.00";
    bindInvoiceRow(cloned);
    tbody.appendChild(cloned);
    filterProductOptions();
    recalculateInvoice();
  });

  filterProductOptions();
  recalculateInvoice();
}

function recalculatePurchaseOrder() {
  const table = document.getElementById("poLineItemsTable");
  if (!table) return;

  let subtotal = 0;
  table.querySelectorAll("tbody tr.po-row").forEach((row) => {
    const productSelect = row.querySelector(".po-product");
    const stockInput = row.querySelector(".po-stock");
    const qtyInput = row.querySelector(".po-qty");
    const costInput = row.querySelector(".po-cost");
    const totalInput = row.querySelector(".po-total");

    const selectedOption = productSelect.options[productSelect.selectedIndex];
    const stock = toNumber(selectedOption?.dataset?.stock);
    const qty = Math.max(toNumber(qtyInput.value), 0);
    const unitCost = Math.max(toNumber(costInput.value), 0);
    const lineTotal = qty * unitCost;

    stockInput.value = stock;
    totalInput.value = lineTotal.toFixed(2);
    subtotal += lineTotal;
  });

  const taxRate = toNumber(document.getElementById("poTaxRate")?.value);
  const tax = subtotal * (taxRate / 100);
  const grandTotal = subtotal + tax;

  const subtotalNode = document.getElementById("poSubtotalValue");
  const taxNode = document.getElementById("poTaxValue");
  const grandTotalNode = document.getElementById("poGrandTotalValue");
  if (subtotalNode) subtotalNode.textContent = subtotal.toFixed(2);
  if (taxNode) taxNode.textContent = tax.toFixed(2);
  if (grandTotalNode) grandTotalNode.textContent = grandTotal.toFixed(2);
}

function bindPurchaseOrderRow(row) {
  row.querySelector(".po-product")?.addEventListener("change", recalculatePurchaseOrder);
  row.querySelector(".po-qty")?.addEventListener("input", recalculatePurchaseOrder);
  row.querySelector(".po-cost")?.addEventListener("input", recalculatePurchaseOrder);
  row.querySelector(".remove-po-line-btn")?.addEventListener("click", () => {
    const tbody = row.closest("tbody");
    if (tbody.querySelectorAll("tr.po-row").length > 1) {
      row.remove();
    } else {
      row.querySelector(".po-product").selectedIndex = 0;
      row.querySelector(".po-qty").value = 1;
      row.querySelector(".po-cost").value = "1.00";
    }
    recalculatePurchaseOrder();
  });
}

function initializePurchaseOrderForm() {
  const form = document.getElementById("purchaseOrderForm");
  if (!form) return;

  const tbody = document.querySelector("#poLineItemsTable tbody");
  const addLineButton = document.getElementById("addPoLineBtn");
  const taxRate = document.getElementById("poTaxRate");

  tbody.querySelectorAll("tr.po-row").forEach(bindPurchaseOrderRow);
  taxRate?.addEventListener("input", recalculatePurchaseOrder);

  addLineButton?.addEventListener("click", () => {
    const templateRow = tbody.querySelector("tr.po-row");
    const cloned = templateRow.cloneNode(true);
    cloned.querySelector(".po-product").selectedIndex = 0;
    cloned.querySelector(".po-stock").value = "0";
    cloned.querySelector(".po-qty").value = 1;
    cloned.querySelector(".po-cost").value = "1.00";
    cloned.querySelector(".po-total").value = "1.00";
    bindPurchaseOrderRow(cloned);
    tbody.appendChild(cloned);
    recalculatePurchaseOrder();
  });

  recalculatePurchaseOrder();
}

document.addEventListener("DOMContentLoaded", () => {
  renderSalesChart();
  initializeInvoiceForm();
  initializePurchaseOrderForm();
});

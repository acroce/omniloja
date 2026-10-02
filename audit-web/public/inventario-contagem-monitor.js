const intQty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

let currentData = null;
let currentView = "sem";

function $(id) {
  return document.getElementById(id);
}

async function api(path) {
  const response = await fetch(path);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Erro na requisicao.");
  return data;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function formatNumber(value) {
  return intQty.format(Number(value || 0));
}

function formatQty(value) {
  return qty.format(Number(value || 0));
}

function formatDateTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusClass(status) {
  const normalized = String(status || "sem_contagem").toLowerCase().replaceAll("_", "-");
  if (normalized === "com-contagem") return "business-concluido";
  if (normalized === "somente-cancelado") return "business-aguardando";
  return "business-erro";
}

function statusLabel(status) {
  if (status === "COM_CONTAGEM") return "Com contagem";
  if (status === "SOMENTE_CANCELADO") return "Somente cancelado";
  return "Sem contagem";
}

function kpi(label, value, sub, cls = "") {
  return `<div class="kpi"><span>${label}</span><strong class="${cls}">${value}</strong><small>${sub || ""}</small></div>`;
}

function table(headers, rows) {
  return `
    <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
    <tbody>${rows.length ? rows.join("") : `<tr><td colspan="${headers.length}">Nenhum registro para este filtro.</td></tr>`}</tbody>
  `;
}

function renderStoreRows(rows) {
  const headers = ["Status", "Loja", "Nome", "Inventarios", "Fechados", "Cancelados", "Itens", "Primeira", "Ultima", "Dif. qtd"];
  return table(headers, rows.map((row) => `
    <tr>
      <td><span class="pill ${statusClass(row.status)}">${statusLabel(row.status)}</span></td>
      <td><strong>${row.loja}</strong></td>
      <td>${row.nome_loja || ""}</td>
      <td class="num">${formatNumber(row.inventarios)}</td>
      <td class="num">${formatNumber(row.inventariosFechados)}</td>
      <td class="num">${formatNumber(row.inventariosCancelados)}</td>
      <td class="num">${formatNumber(row.itens)}</td>
      <td>${row.primeiraContagem || "-"}</td>
      <td>${row.ultimaContagem || "-"}</td>
      <td class="num">${formatQty(row.diferencaQtd)}</td>
    </tr>
  `));
}

function renderInventoryRows(rows) {
  const headers = ["Loja", "Nome", "Inventario", "Data", "Inicio", "Fim", "Fechado", "Cancelado", "Itens", "Sistema", "Contagem", "Dif. qtd", "Descricao"];
  return table(headers, rows.map((row) => `
    <tr>
      <td><strong>${row.loja}</strong></td>
      <td>${row.nome_loja || ""}</td>
      <td>${row.inventario_id}</td>
      <td>${row.data_contagem || "-"}</td>
      <td>${formatDateTime(row.inicio)}</td>
      <td>${formatDateTime(row.fim)}</td>
      <td>${Number(row.fechado || 0) === 1 ? "Sim" : "Nao"}</td>
      <td>${Number(row.cancelado || 0) === 1 ? "Sim" : "Nao"}</td>
      <td class="num">${formatNumber(row.itens)}</td>
      <td class="num">${formatQty(row.qtd_sistema)}</td>
      <td class="num">${formatQty(row.qtd_contagem)}</td>
      <td class="num">${formatQty(row.diferenca_qtd)}</td>
      <td class="command-cell">${row.descricao || ""}</td>
    </tr>
  `));
}

function renderTable() {
  if (!currentData) return;
  const tabs = [
    ["sem", "Sem contagem", currentData.missingStores || []],
    ["com", "Com contagem", currentData.countedStores || []],
    ["cancelado", "Somente cancelado", currentData.canceledOnlyStores || []],
    ["inventarios", "Inventarios", currentData.inventories || []],
  ];
  $("inventoryTabs").innerHTML = tabs.map(([id, label, rows]) => `
    <button class="${id === currentView ? "active" : ""}" type="button" data-view="${id}">
      ${label} (${formatNumber(rows.length)})
    </button>
  `).join("");

  const selected = tabs.find(([id]) => id === currentView) || tabs[0];
  $("tableTitle").textContent = selected[1];
  $("inventoryTable").innerHTML = currentView === "inventarios"
    ? renderInventoryRows(selected[2])
    : renderStoreRows(selected[2]);
  $("inventoryStatus").textContent = `Periodo ${currentData.startDate} ate ${currentData.endDate}.`;
}

function render(data) {
  currentData = data;
  const totals = data.totals || {};
  $("pageSubtitle").textContent = `Periodo ${data.startDate} ate ${data.endDate} · consulta direta no Pleno`;
  $("inventoryUpdatedAt").textContent = `Atualizado ${formatDateTime(data.updatedAt)}`;
  $("inventoryKpis").innerHTML = [
    kpi("Lojas", formatNumber(totals.lojas), data.onlyActive ? "ativas" : "todas"),
    kpi("Com contagem", formatNumber(totals.comContagem), `${formatQty(totals.doneRate)}% das lojas`, totals.comContagem ? "positive" : ""),
    kpi("Sem contagem", formatNumber(totals.semContagem), "sem inventario valido", totals.semContagem ? "negative" : ""),
    kpi("Somente cancelado", formatNumber(totals.somenteCancelado), "inventario cancelado no periodo", totals.somenteCancelado ? "negative" : ""),
    kpi("Inventarios", formatNumber(totals.inventarios), `${formatNumber(totals.itens)} itens`),
  ].join("");

  $("storeSummary").innerHTML = `
    <div class="inventory-bar">
      <span class="inventory-ok" style="width:${Math.max(0, Math.min(100, Number(totals.doneRate || 0)))}%"></span>
      <span class="inventory-canceled" style="width:${totals.lojas ? (Number(totals.somenteCancelado || 0) / Number(totals.lojas || 1)) * 100 : 0}%"></span>
    </div>
    <div class="inventory-legend">
      <span><strong>${formatNumber(totals.comContagem)}</strong> com contagem</span>
      <span><strong>${formatNumber(totals.semContagem)}</strong> sem contagem</span>
      <span><strong>${formatNumber(totals.somenteCancelado)}</strong> somente cancelado</span>
    </div>
  `;
  renderTable();
}

async function loadMonitor() {
  $("inventoryStatus").textContent = "Consultando inventarios no Pleno...";
  const params = new URLSearchParams();
  params.set("startDate", $("startDate").value || todayIso());
  params.set("endDate", $("endDate").value || $("startDate").value || todayIso());
  const lojas = $("storeList").value.trim();
  if (lojas) params.set("lojas", lojas);
  if (!$("activeOnly").checked) params.set("active", "0");
  render(await api(`/api/business-monitor/inventario-contagem?${params.toString()}`));
}

$("startDate").value = todayIso();
$("endDate").value = todayIso();

$("filterForm").addEventListener("submit", (event) => {
  event.preventDefault();
  loadMonitor().catch((error) => {
    $("pageSubtitle").textContent = error.message;
    $("inventoryStatus").textContent = error.message;
  });
});

$("inventoryTabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  currentView = button.dataset.view;
  renderTable();
});

loadMonitor().catch((error) => {
  $("pageSubtitle").textContent = error.message;
  $("inventoryStatus").textContent = error.message;
});

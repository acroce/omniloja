const $ = (id) => document.getElementById(id);
let loading = false;
let availableOpenDates = [];
let selectedDetailDate = "";

function formatDate(value) {
  return value ? String(value).split("-").reverse().join("/") : "-";
}

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function render(data) {
  const totals = data.totals;
  $("kpis").innerHTML = [
    ["Lojas ativas", totals.stores, "neutral"], ["Transferências em aberto", totals.openTransfers, "warn"],
    ["Lojas com falha", totals.failures, totals.failures ? "warn" : "ok"], ["Comprovantes com falha", totals.ocrFailures, totals.ocrFailures ? "warn" : "ok"],
  ].map(([label, value, tone]) => `<article class="tesouraria-kpi ${tone}"><span>${label}</span><strong>${value}</strong></article>`).join("");
  const ranking = data.problemRanking || {};
  const problemCards = [
    ["Mais falhas", ranking.topFailures, "failures"],
    ["Mais foto / OCR", ranking.topPhotoErrors, "photoErrors"],
    ["Mais digitação", ranking.topTypingErrors, "typingErrors"],
  ];
  $("problemRanking").innerHTML = problemCards.map(([label, store, field]) => `<article class="tesouraria-problem-card">
    <span>${label}</span><strong>${store ? `${escapeHtml(store.storeCode)} - ${escapeHtml(store.storeName)}` : "Sem ocorrência"}</strong><b>${store ? store[field] : 0}</b>
  </article>`).join("");
  const periodDates = ranking.periodDates || [];
  $("problemPeriod").textContent = periodDates.length ? `${periodDates.length} data(s) com pendência` : "Sem pendências";
  if (!availableOpenDates.length) availableOpenDates = data.openDates || [];
  const dates = availableOpenDates;
  const activeDate = selectedDetailDate || data.plannedDate;
  $("openDates").innerHTML = dates.length ? dates.map((date) => `<button class="tesouraria-date-item ${date.plannedDate === activeDate ? "active" : ""}" type="button" data-date="${date.plannedDate}">
    <strong>${date.plannedDate.split("-").reverse().join("/")}</strong><span>${date.openTransfers} aberta(s) · ${date.openStores} loja(s)</span></button>`).join("") : `<p class="tesouraria-empty">Não há transferências em aberto.</p>`;
  $("openDates").querySelectorAll("[data-date]").forEach((button) => button.addEventListener("click", () => {
    selectedDetailDate = button.dataset.date;
    load(selectedDetailDate).catch(showError);
  }));
  const selectedStatus = $("viewFilter").value;
  const statusLabels = {
    em_aberto: "Em aberto",
    sem_transferencia: "Sem transferência",
    falha: "Falha",
    duplicada: "Duplicada",
    concluida: "Concluída",
    ja_liquidada: "Já liquidada",
  };
  const stores = selectedStatus === "all" ? data.stores : data.stores.filter((store) => store.dailyStatus === statusLabels[selectedStatus]);
  $("records").innerHTML = stores.length ? stores.map((store) => {
    const failed = store.dailyStatus === "Falha";
    const done = store.dailyStatus === "Concluída";
    return `<article class="tesouraria-record-card ${failed ? "danger" : done ? "ok" : ""}"><header><div><span>Loja ${escapeHtml(store.storeCode)}</span><h3>${escapeHtml(store.storeName)}</h3></div><b class="tesouraria-card-symbol">${failed ? "!" : done ? "OK" : "..."}</b></header><div class="tesouraria-card-data"><div><span>Em aberto</span><strong>${store.openTransfers}</strong></div><div><span>Concluídas</span><strong>${store.completed}</strong></div><div><span>Falhas</span><strong>${store.failures}</strong></div><div><span>OCR / foto</span><strong>${store.ocrFailures}</strong></div></div><footer><div><span>Status</span><b class="tesouraria-status ${failed ? "danger" : done ? "ok" : store.dailyStatus === "Sem transferência" ? "neutral" : "warn"}">${escapeHtml(store.dailyStatus)}</b></div><div><span>Duplicadas</span><b>${store.duplicates}</b></div></footer></article>`;
  }).join("") : `<div class="tesouraria-empty">Nenhuma loja requer atenção nesta data.</div>`;
  $("tableMeta").textContent = `${formatDate(activeDate)} · ${stores.length} de ${data.stores.length} loja(s)`;
}

async function load(detailDate = "") {
  if (loading) return;
  loading = true;
  if (!detailDate) availableOpenDates = [];
  setQueryStatus("Consultando indicadores do período...", true);
  try {
    const startDate = detailDate || $("startDate").value;
    const endDate = detailDate || $("endDate").value || startDate;
    const response = await fetch(`/api/tesouraria/cofre-inteligente/indicadores?${new URLSearchParams({ plannedDate: endDate, startDate, endDate })}`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Não foi possível carregar os indicadores.");
    if (!detailDate) {
      $("startDate").value = data.startDate || data.plannedDate;
      $("endDate").value = data.endDate || data.plannedDate;
      selectedDetailDate = data.plannedDate || "";
    }
    render(data);
    setQueryStatus("Consulta concluída");
  } finally {
    loading = false;
    if ($("runQueryButton").disabled) setQueryStatus($("queryStatus").textContent === "Consultando indicadores do período..." ? "Consulta não concluída" : $("queryStatus").textContent);
  }
}

function setQueryStatus(text, busy = false) {
  $("queryStatus").textContent = text;
  $("runQueryButton").disabled = busy;
  $("runQueryButton").textContent = busy ? "Consultando..." : "Consultar";
}

function markQueryDirty() { setQueryStatus("Filtros alterados. Consulta pendente"); }

$("startDate").addEventListener("change", markQueryDirty);
$("endDate").addEventListener("change", markQueryDirty);
$("viewFilter").addEventListener("change", markQueryDirty);
$("runQueryButton").addEventListener("click", () => load().catch(showError));
$("refreshButton").addEventListener("click", () => load().catch(showError));
function showError(error) { $("tableMeta").textContent = error.message; setQueryStatus("Consulta não concluída"); }
load().catch(showError);

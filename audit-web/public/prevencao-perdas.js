const $ = (id) => document.getElementById(id);
let latest = null;
let loading = false;
let runStarting = false;

function escapeHtml(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }
function formatDateTime(value) { if (!value) return "-"; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }); }
function statusInfo(status) { return status === "concluido" ? { label: "OK", tone: "ok" } : status === "erro" ? { label: "Erro", tone: "danger" } : status === "pendente_reconsulta" ? { label: "Aguardando retorno SAP", tone: "warn" } : status === "pendente_revalidacao_pleno" ? { label: "Revalidar link Pleno", tone: "warn" } : { label: "Em processamento", tone: "warn" }; }

function renderExecution(run) {
  const running = run?.status === "executando";
  const starting = runStarting && !running;
  const hasExecutionError = run?.status === "erro" && Boolean(run.message);
  const executionErrorTitle = hasExecutionError ? ` title="${escapeHtml(run.message)}" aria-label="Detalhe do erro da execução: ${escapeHtml(run.message)}" tabindex="0"` : "";
  $("runStatus").textContent = starting ? "Iniciando" : running ? "Executando" : run?.status === "finalizado" ? "Finalizado" : run?.status === "erro" ? "Erro" : "Sem informacao";
  $("runStatus").className = `tesouraria-status ${starting || running ? "warn" : run?.status === "finalizado" ? "ok" : run?.status === "erro" ? "danger" : "neutral"}`;
  $("runStatus").title = hasExecutionError ? run.message : "";
  $("runStatus").setAttribute("aria-label", hasExecutionError ? `Erro na execução: ${run.message}` : $("runStatus").textContent);
  $("executionMeta").innerHTML = run ? `<span>${escapeHtml(run.currentFilial || "Aguardando filial")}</span><span>NF ${escapeHtml(run.currentNota || "-")}</span><span><b>${run.processed || 0}</b> tratadas</span><span class="ok-dot"><b>${run.completed || 0}</b> OK</span><span><b>${run.pendingReview || 0}</b> revalidação</span><span class="error-dot"${executionErrorTitle}><b>${run.failed || 0}</b> erros</span><span>Atualizado ${formatDateTime(run.updatedAt)}</span>` : "";
  $("executeButton").disabled = running || runStarting;
  $("executeButton").textContent = running || runStarting ? "Execucao em andamento" : "Executar agora";
}

function renderKpis(totals) {
  const items = [["Processadas", totals.processed || 0, "neutral"], ["Concluidas", totals.completed || 0, "ok"], ["Erros", totals.errors || 0, "danger"], ["Pendentes", totals.pending || 0, "warn"]];
  $("kpis").innerHTML = items.map(([label, value, tone]) => `<article class="tesouraria-kpi ${tone}"><span>${label}</span><strong>${value}</strong><i></i></article>`).join("");
}

function renderHistory(records) {
  const rows = records.slice(0, 12);
  $("history").innerHTML = `<h2>Ultimas tratativas <small>${records.length}</small></h2><div class="tesouraria-history-list">${rows.length ? rows.map((row) => { const state = statusInfo(row.status); return `<div class="tesouraria-history-row"><b class="tesouraria-status ${state.tone}">${state.label}</b><span><strong>${escapeHtml(row.filial || "Filial nao informada")}</strong><small>NF ${escapeHtml(row.nro_nf || row.nota_id || "-")} · ${formatDateTime(row.updated_at)}</small>${escapeHtml(row.message || row.situacao_final || "")}</span></div>`; }).join("") : "<span>Sem historico ainda.</span>"}</div>`;
}

function renderRows(records) {
  $("records").innerHTML = records.length ? records.map((row) => {
    const state = statusInfo(row.status);
    const screenshot = row.screenshot_file ? `<a href="/api/prevencao-perdas/anexo?file=${encodeURIComponent(row.screenshot_file)}" target="_blank" rel="noopener">Abrir imagem</a>` : "-";
    return `<article class="tesouraria-record-card ${state.tone}"><header><div><span>${escapeHtml(row.filial || "Filial")}</span><h3>NF ${escapeHtml(row.nro_nf || row.nota_id || "-")}</h3></div><b class="tesouraria-card-symbol">${state.tone === "ok" ? "OK" : state.tone === "danger" ? "!" : "..."}</b></header><div class="tesouraria-card-data"><div><span>Albaran</span><strong>${escapeHtml(row.albaran || "-")}</strong></div><div><span>Tipo</span><strong>${escapeHtml(row.tipo_operacao || "-")}</strong></div><div><span>Situacao inicial</span><strong>${escapeHtml(row.situacao_inicial || "-")}</strong></div><div><span>Erro</span><strong>${screenshot}</strong></div></div><footer><div><span>Status</span><b class="tesouraria-status ${state.tone}">${state.label}</b></div><div><span>Atualizacao</span><b class="tesouraria-check ${state.tone}">${formatDateTime(row.updated_at)}</b></div>${row.message ? `<p title="${escapeHtml(row.message)}">${escapeHtml(row.message)}</p>` : ""}</footer></article>`;
  }).join("") : `<div class="tesouraria-empty">Nenhuma nota encontrada para os filtros.</div>`;
}

function syncFiliais(filiais) {
  const selected = $("filialFilter").value || "all";
  $("filialFilter").innerHTML = `<option value="all">Todas as filiais</option>${filiais.map((filial) => `<option value="${escapeHtml(String(filial).match(/^\d+/)?.[0] || filial)}">${escapeHtml(filial)}</option>`).join("")}`;
  $("filialFilter").value = [...$("filialFilter").options].some((option) => option.value === selected) ? selected : "all";
}

async function load() {
  if (loading) return;
  loading = true;
  $("queryStatus").textContent = "Consultando dados";
  try {
    const params = new URLSearchParams({ filial: $("filialFilter").value || "all", status: $("statusFilter").value || "all" });
    const response = await fetch(`/api/prevencao-perdas?${params}`);
    latest = await response.json();
    if (!response.ok) throw new Error(latest.error || "Nao foi possivel carregar os dados.");
    syncFiliais(latest.filiais || []);
    renderExecution(latest.execution);
    renderKpis(latest.totals || {});
    renderHistory(latest.records || []);
    renderRows(latest.records || []);
    $("tableMeta").textContent = `Exibindo ${latest.records.length} nota(s)`;
    $("queryStatus").textContent = "Consulta concluida";
  } catch (error) {
    $("tableMeta").textContent = error.message;
    $("queryStatus").textContent = "Consulta nao concluida";
  } finally {
    loading = false;
  }
}

async function startRun() {
  if (runStarting) return;
  runStarting = true;
  renderExecution(latest?.execution);
  try {
    const response = await fetch("/api/prevencao-perdas/run", { method: "POST" });
    const result = await response.json();
    if (!response.ok) throw new Error(result.message || "Nao foi possivel iniciar.");
    renderExecution(result.execution);
    await load();
  } catch (error) {
    alert(error.message);
  } finally {
    runStarting = false;
  }
}

function exportCsv() {
  const rows = latest?.records || [];
  const header = ["Filial", "NF", "Albaran", "Tipo", "Status", "Situacao inicial", "Situacao final", "Mensagem"];
  const body = rows.map((row) => [row.filial || "", row.nro_nf || row.nota_id || "", row.albaran || "", row.tipo_operacao || "", row.status || "", row.situacao_inicial || "", row.situacao_final || "", row.message || ""]);
  const csv = [header, ...body].map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(";")).join("\n");
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  link.download = "prevencao-perdas.csv";
  link.click();
  URL.revokeObjectURL(link.href);
}

$("filialFilter").addEventListener("change", load);
$("statusFilter").addEventListener("change", load);
$("runQueryButton").addEventListener("click", load);
$("refreshButton").addEventListener("click", load);
$("executeButton").addEventListener("click", startRun);
$("exportButton").addEventListener("click", exportCsv);
load();
window.setInterval(() => fetch("/api/prevencao-perdas/execution").then((response) => response.json()).then(renderExecution).catch(() => {}), 5000);

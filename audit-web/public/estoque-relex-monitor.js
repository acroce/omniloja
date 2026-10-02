const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

function $(id) {
  return document.getElementById(id);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Erro na requisicao.");
  return data;
}

function formatNumber(value) {
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
  return `business-${String(status || "sem_coleta").replaceAll("_", "-")}`;
}

function kpi(label, value, sub, cls = "") {
  return `<div class="kpi"><span>${label}</span><strong class="${cls}">${value}</strong><small>${sub || ""}</small></div>`;
}

function renderMonitor(data) {
  const counts = data.counts || {};
  const okCount = (counts.concluido || 0) + (counts.concluido_atrasado || 0);
  const lateCount = counts.atrasado || 0;
  const waitingCount = counts.aguardando || 0;
  const missingCount = (counts.sem_coleta || 0) + (counts.configurar || 0);

  $("pageSubtitle").textContent = `Agora ${formatDateTime(data.now)} · integracao estoque RELEX`;
  $("businessUpdatedAt").textContent = data.statusFileExists
    ? `Coleta ${formatDateTime(data.updatedAt)}`
    : "Sem arquivo de coleta";

  $("businessKpis").innerHTML = [
    kpi("Etapas OK", formatNumber(okCount), "concluidas na timeline", okCount ? "positive" : ""),
    kpi("Atrasadas", formatNumber(lateCount), "precisam de alerta", lateCount ? "negative" : ""),
    kpi("Aguardando", formatNumber(waitingCount), "ainda dentro do horario", waitingCount ? "" : ""),
    kpi("Sem coleta", formatNumber(missingCount), "sem evidencia ou horario", missingCount ? "negative" : ""),
    kpi("Total etapas", formatNumber((data.stages || []).length), "estoque RELEX"),
  ].join("");

  $("businessTimeline").innerHTML = (data.stages || []).map((stage, index) => `
    <article class="business-step ${statusClass(stage.status)}">
      <div class="business-marker">${index + 1}</div>
      <div class="business-step-body">
        <div class="business-step-head">
          <strong>${stage.label}</strong>
          <span class="pill ${statusClass(stage.status)}">${stage.statusLabel}</span>
        </div>
        <div class="business-time">Prazo ${stage.targetTime || "configurar"} · ${stage.phase}</div>
        <p>${stage.description || ""}</p>
        <small>Realizado: ${formatDateTime(stage.actualAt)}${stage.count !== "" ? ` · ${formatNumber(stage.count)} linha(s)` : ""}</small>
      </div>
    </article>
  `).join("");

  const headers = ["Status", "Etapa", "Fase", "Prazo", "Realizado", "Linhas", "Fonte", "Detalhe"];
  const rows = (data.stages || []).map((stage) => [
    `<span class="pill ${statusClass(stage.status)}">${stage.statusLabel}</span>`,
    `<strong>${stage.label}</strong>`,
    stage.phase,
    stage.targetTime || "configurar",
    formatDateTime(stage.actualAt),
    stage.count !== "" ? formatNumber(stage.count) : "",
    stage.source || "",
    stage.details || stage.description || "",
  ]);

  $("businessTable").innerHTML = `
    <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((value, index) => `<td class="${index === 7 ? "command-cell" : ""}">${value}</td>`).join("")}</tr>`).join("")}</tbody>
  `;

  $("businessStatus").textContent = data.notice
    ? data.notice
    : data.statusFileExists
    ? `Lendo ${data.statusFile}.`
    : `Crie/atualize ${data.statusFile} para alimentar esta timeline.`;
}

async function loadMonitor() {
  $("businessStatus").textContent = "Carregando monitor...";
  const data = await api("/api/business-monitor/estoque-relex");
  renderMonitor(data);
}

$("refreshButton").addEventListener("click", loadMonitor);

loadMonitor().catch((error) => {
  $("pageSubtitle").textContent = error.message;
  $("businessStatus").textContent = error.message;
});

setInterval(() => {
  loadMonitor().catch((error) => {
    $("pageSubtitle").textContent = error.message;
    $("businessStatus").textContent = error.message;
  });
}, 5 * 60 * 1000);

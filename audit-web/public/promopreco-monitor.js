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
  if (value === "") return "";
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

function fileCounters(stage) {
  const pending = stage.pendingCount === "" ? "-" : formatNumber(stage.pendingCount);
  const imported = stage.importedCount === "" ? "-" : formatNumber(stage.importedCount);
  const timeRange = stage.firstFileTime || stage.lastFileTime
    ? `<span class="wide">Hora arquivo: <strong>${stage.firstFileTime || "-"} a ${stage.lastFileTime || "-"}</strong></span>`
    : "";
  const importedAt = stage.lastImportedAt
    ? `<span>Ultimo imp.: <strong>${stage.lastImportedAt}</strong></span>`
    : "";
  const process = stage.processRunning ? `<span>Processo: <strong>rodando</strong></span>` : "";
  const processStart = stage.processStartTime ? `<span>Inicio proc.: <strong>${stage.processStartTime}</strong></span>` : "";
  return `<div class="business-file-counts"><span>Sem imp.: <strong>${pending}</strong></span><span>Com imp.: <strong>${imported}</strong></span>${importedAt}${process}${processStart}${timeRange}</div>`;
}

function groupStages(stages) {
  const groups = [];
  for (const stage of stages || []) {
    const label = stage.batch || "Timeline";
    let group = groups.find((item) => item.label === label);
    if (!group) {
      group = { label, stages: [] };
      groups.push(group);
    }
    group.stages.push(stage);
  }
  return groups;
}

function renderMonitor(data) {
  const counts = data.counts || {};
  const okCount = (counts.concluido || 0) + (counts.concluido_atrasado || 0);
  const lateCount = counts.atrasado || 0;
  const waitingCount = counts.aguardando || 0;
  const issueCount = (counts.sem_coleta || 0) + (counts.configurar || 0) + (counts.erro || 0);

  $("pageSubtitle").textContent = `Agora ${formatDateTime(data.now)} · PROM e PROD`;
  $("businessUpdatedAt").textContent = data.statusFileExists
    ? `Coleta ${formatDateTime(data.updatedAt)}`
    : "Sem arquivo de coleta";

  $("businessKpis").innerHTML = [
    kpi("Etapas OK", formatNumber(okCount), "concluidas na timeline", okCount ? "positive" : ""),
    kpi("Atrasadas", formatNumber(lateCount), "precisam de alerta", lateCount ? "negative" : ""),
    kpi("Aguardando", formatNumber(waitingCount), "ainda dentro do horario"),
    kpi("Pendencias", formatNumber(issueCount), "sem coleta, erro ou configurar", issueCount ? "negative" : ""),
    kpi("Total etapas", formatNumber((data.stages || []).length), "promocao e precos"),
  ].join("");

  $("businessTimeline").innerHTML = groupStages(data.stages).map((group) => `
    <section class="business-round">
      <h3>${group.label}</h3>
      <div class="business-timeline business-timeline-nested">
        ${group.stages.map((stage, index) => `
          <article class="business-step ${statusClass(stage.status)}">
            <div class="business-marker">${index + 1}</div>
            <div class="business-step-body">
              <div class="business-step-head">
                <strong>${stage.label}</strong>
                <span class="pill ${statusClass(stage.status)}">${stage.statusLabel}</span>
              </div>
              <div class="business-time">Prazo ${stage.targetTime || "configurar"} · ${stage.phase}</div>
              ${fileCounters(stage)}
              <p>${stage.description || ""}</p>
              <small>Realizado: ${formatDateTime(stage.actualAt)}${stage.count !== "" ? ` · ${formatNumber(stage.count)} registro(s)` : ""}</small>
            </div>
          </article>
        `).join("")}
      </div>
    </section>
  `).join("");

  const headers = ["Status", "Etapa", "Fase", "Prazo", "Realizado", "Hora arquivos", "Ultimo imp.", "Inicio processo", "Processo", "Sem imp.", "Com imp.", "Quantidade", "Fonte", "Detalhe"];
  const rows = (data.stages || []).map((stage) => [
    `<span class="pill ${statusClass(stage.status)}">${stage.statusLabel}</span>`,
    `<strong>${stage.label}</strong>`,
    stage.phase,
    stage.targetTime || "configurar",
    formatDateTime(stage.actualAt),
    stage.firstFileTime || stage.lastFileTime ? `${stage.firstFileTime || "-"} a ${stage.lastFileTime || "-"}` : "",
    stage.lastImportedAt || "",
    stage.processStartTime || "",
    stage.processRunning ? "Rodando" : "",
    stage.pendingCount !== "" ? formatNumber(stage.pendingCount) : "",
    stage.importedCount !== "" ? formatNumber(stage.importedCount) : "",
    stage.count !== "" ? formatNumber(stage.count) : "",
    stage.source || "",
    stage.details || stage.description || "",
  ]);

  $("businessTable").innerHTML = `
    <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((value, index) => `<td class="${index === 13 ? "command-cell" : ""}">${value}</td>`).join("")}</tr>`).join("")}</tbody>
  `;

  $("businessStatus").textContent = data.statusFileExists
    ? `Lendo ${data.statusFile}.`
    : `Crie/atualize ${data.statusFile} para alimentar esta timeline.`;
}

async function loadMonitor() {
  $("businessStatus").textContent = "Carregando monitor...";
  const data = await api("/api/business-monitor/promopreco");
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

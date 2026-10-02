const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

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
  return `cron-${String(status || "sem_coleta").replaceAll("_", "-")}`;
}

function kpi(label, value, sub, cls = "") {
  return `<div class="kpi"><span>${label}</span><strong class="${cls}">${value}</strong><small>${sub || ""}</small></div>`;
}

function renderCronMonitor(data) {
  $("pageSubtitle").textContent = `Agora ${formatDateTime(data.now)} · ${data.statusFileExists ? `coleta atualizada em ${formatDateTime(data.updatedAt)}` : "ainda sem arquivo de coleta"}`;
  $("cronUpdatedAt").textContent = data.statusFileExists ? `Fonte: ${data.collector || "status.json"}` : "Sem coleta";

  const counts = data.counts || {};
  $("cronKpis").innerHTML = [
    kpi("Nao rodou", formatNumber(counts.nao_rodou || 0), "fora da janela esperada", counts.nao_rodou ? "negative" : ""),
    kpi("Erro", formatNumber(counts.erro || 0), "exit code diferente de zero", counts.erro ? "negative" : ""),
    kpi("Rodando", formatNumber(counts.rodando || 0), "processo em execucao", counts.rodando ? "positive" : ""),
    kpi("Rodou", formatNumber(counts.rodou || 0), "ultima agenda confirmada", "positive"),
    kpi("Sem coleta", formatNumber(counts.sem_coleta || 0), "aguardando integracao do coletor", counts.sem_coleta ? "negative" : ""),
  ].join("");

  const urgent = (data.jobs || []).filter((job) => job.severity >= 3);
  $("cronTimeline").innerHTML = urgent.length
    ? urgent.map((job) => `
      <div class="cron-alert ${statusClass(job.status)}">
        <strong>${job.label}</strong>
        <span>${job.statusLabel} · esperado ${formatDateTime(job.expectedAt)} · tolerancia ${job.graceMinutes} min</span>
      </div>
    `).join("")
    : "<div class=\"cron-alert cron-rodou\"><strong>Nenhum alerta critico</strong><span>As rotinas monitoradas estao dentro da janela ou aguardando a proxima execucao.</span></div>";

  const headers = ["Status", "Processo", "Agenda", "Esperado", "Ultima execucao", "Grupo", "Comando"];
  const rows = (data.jobs || []).map((job) => [
    `<span class="pill ${statusClass(job.status)}">${job.statusLabel}</span>`,
    `<strong>${job.label}</strong>`,
    job.schedule,
    formatDateTime(job.expectedAt),
    `${formatDateTime(job.lastFinishedAt || job.lastStartedAt)}${job.exitCode !== "" ? ` · exit ${job.exitCode}` : ""}`,
    job.group,
    job.command,
  ]);

  $("cronTable").innerHTML = `
    <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((value, index) => `<td class="${index === 6 ? "command-cell" : ""}">${value}</td>`).join("")}</tr>`).join("")}</tbody>
  `;

  $("cronStatus").textContent = data.statusFileExists
    ? `Lendo ${data.statusFile}. ${data.jobs.length} processo(s) configurado(s).`
    : `Crie/atualize ${data.statusFile} para alimentar o monitor com execucoes reais.`;
}

async function loadCronMonitor() {
  $("cronStatus").textContent = "Carregando monitor...";
  const data = await api("/api/cron-monitor");
  renderCronMonitor(data);
}

$("refreshCronButton").addEventListener("click", loadCronMonitor);

loadCronMonitor().catch((error) => {
  $("pageSubtitle").textContent = error.message;
  $("cronStatus").textContent = error.message;
});

setInterval(() => {
  loadCronMonitor().catch((error) => {
    $("pageSubtitle").textContent = error.message;
    $("cronStatus").textContent = error.message;
  });
}, 5 * 60 * 1000);

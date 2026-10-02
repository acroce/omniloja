const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const intQty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

function $(id) {
  return document.getElementById(id);
}

async function api(path) {
  const response = await fetch(path);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Erro na requisicao.");
  return data;
}

function statusClass(status) {
  const value = status === "warning" ? "aguardando" : status;
  return `business-${String(value || "sem_coleta").replaceAll("_", "-")}`;
}

function statusLabel(status) {
  if (status === "ok") return "OK";
  if (status === "warning") return "Atencao";
  if (status === "error") return "Critico";
  return "Sem coleta";
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

function fmt(value, suffix = "") {
  if (value === "" || value === undefined || value === null) return "-";
  return `${qty.format(Number(value || 0))}${suffix}`;
}

function secondsText(seconds) {
  const total = Number(seconds || 0);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function kpi(label, value, sub, cls = "") {
  return `<div class="kpi"><span>${label}</span><strong class="${cls}">${value}</strong><small>${sub || ""}</small></div>`;
}

function render(data) {
  const servers = data.servers || [];
  const activeProcesses = servers.flatMap((server) => (server.processes || []).map((process) => ({ ...process, server })));
  const warningCount = (data.counts || {}).warning || 0;
  const errorCount = (data.counts || {}).error || 0;
  const maxCpu = activeProcesses.reduce((max, proc) => Math.max(max, Number(proc.cpuPct || 0)), 0);
  const totalCpu = activeProcesses.reduce((sum, proc) => sum + Number(proc.cpuPct || 0), 0);

  $("pageSubtitle").textContent = `Agora ${formatDateTime(data.now)} · processos /retag`;
  $("resourceUpdatedAt").textContent = data.statusFileExists ? `Coleta ${formatDateTime(data.updatedAt)}` : "Sem coleta";
  $("resourceKpis").innerHTML = [
    kpi("Servidores OK", intQty.format((data.counts || {}).ok || 0), "sem pressao"),
    kpi("Atencao", intQty.format(warningCount), "revisar folga", warningCount ? "negative" : ""),
    kpi("Critico", intQty.format(errorCount), "acao imediata", errorCount ? "negative" : ""),
    kpi("Processos ativos", intQty.format(activeProcesses.length), "cargas/importa/gerabd"),
    kpi("CPU processos", fmt(totalCpu, "%"), `maior ${fmt(maxCpu, "%")}`, totalCpu > 120 ? "negative" : ""),
  ].join("");

  $("serverCards").innerHTML = servers.map((server) => {
    const metrics = server.metrics || {};
    const memAvailGb = Number(metrics.memAvailableMb || 0) / 1024;
    const memTotalGb = Number(metrics.memTotalMb || 0) / 1024;
    return `
      <article class="resource-card ${statusClass(server.status)}">
        <div class="business-step-head">
          <strong>${server.label}</strong>
          <span class="pill ${statusClass(server.status)}">${statusLabel(server.status)}</span>
        </div>
        <div class="resource-metrics">
          <span>Load <strong>${fmt(metrics.load1)}</strong> / ${fmt(metrics.cores)} cores</span>
          <span>CPU idle <strong>${fmt(metrics.idlePct, "%")}</strong></span>
          <span>I/O wait <strong>${fmt(metrics.iowaitPct, "%")}</strong></span>
          <span>Mem disponivel <strong>${fmt(memAvailGb, " GiB")}</strong> / ${fmt(memTotalGb, " GiB")}</span>
          <span>Disco / <strong>${fmt(metrics.rootUsedPct, "%")}</strong></span>
          <span>Processos <strong>${intQty.format((server.processes || []).length)}</strong></span>
        </div>
        <p>${server.details || ""}</p>
        <small>${server.source || ""} · ${server.remoteDate || ""}</small>
      </article>
    `;
  }).join("");

  const headers = ["Servidor", "PID", "Tempo", "CPU", "Mem", "RSS", "Comando"];
  const rows = activeProcesses.map((proc) => [
    proc.server.label,
    proc.pid,
    secondsText(proc.elapsedSeconds),
    fmt(proc.cpuPct, "%"),
    fmt(proc.memPct, "%"),
    fmt(proc.rssMb, " MB"),
    proc.command,
  ]);
  $("processTable").innerHTML = `
    <thead><tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row) => `<tr>${row.map((value, index) => `<td class="${index === 6 ? "command-cell" : ""}">${value}</td>`).join("")}</tr>`).join("")}</tbody>
  `;
  $("resourceStatus").textContent = data.statusFileExists ? `Lendo ${data.statusFile}.` : "Sem arquivo de coleta.";
}

async function loadMonitor() {
  $("resourceStatus").textContent = "Carregando monitor...";
  render(await api("/api/business-monitor/process-resources"));
}

$("refreshButton").addEventListener("click", loadMonitor);
loadMonitor().catch((error) => {
  $("pageSubtitle").textContent = error.message;
  $("resourceStatus").textContent = error.message;
});
setInterval(() => loadMonitor().catch(() => {}), 5 * 60 * 1000);

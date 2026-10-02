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
  const stage = (data.stages || [])[0] || {};
  const files = stage.files || [];
  const limit = Number(stage.maxFiles || 3);
  const count = Number(stage.count || 0);
  const overLimit = count > limit;

  $("pageSubtitle").textContent = `Agora ${formatDateTime(data.now)} · /servpleno/importacao`;
  $("businessUpdatedAt").textContent = data.statusFileExists
    ? `Coleta ${formatDateTime(data.updatedAt)}`
    : "Sem arquivo de coleta";

  $("businessKpis").innerHTML = [
    kpi("Arquivos", formatNumber(count), "RETIFICACAO_RET_*.*", overLimit ? "negative" : "positive"),
    kpi("Limite", formatNumber(limit), "acima disso alerta"),
    kpi("Status", stage.statusLabel || "-", stage.phase || "Importacao", overLimit ? "negative" : ""),
    kpi("Total etapas", formatNumber((data.stages || []).length), "retificacao RET"),
  ].join("");

  $("businessTimeline").innerHTML = (data.stages || []).map((item, index) => `
    <article class="business-step ${statusClass(item.status)}">
      <div class="business-marker">${index + 1}</div>
      <div class="business-step-body">
        <div class="business-step-head">
          <strong>${item.label}</strong>
          <span class="pill ${statusClass(item.status)}">${item.statusLabel}</span>
        </div>
        <div class="business-time">Verificacao horaria · ${item.phase}</div>
        <p>${item.description || ""}</p>
        <small>Realizado: ${formatDateTime(item.actualAt)} · ${formatNumber(item.count || 0)} arquivo(s)</small>
      </div>
    </article>
  `).join("");

  const fileRows = files.length
    ? files.map((file) => `
      <tr>
        <td><strong>${file.name}</strong></td>
        <td>${formatNumber(file.bytes)}</td>
        <td>${file.mtime || ""}</td>
      </tr>
    `).join("")
    : '<tr><td colspan="3">Nenhum arquivo RETIFICACAO_RET pendente.</td></tr>';

  $("businessTable").innerHTML = `
    <thead><tr><th>Arquivo</th><th>Bytes</th><th>Modificado</th></tr></thead>
    <tbody>${fileRows}</tbody>
  `;

  $("businessStatus").textContent = data.notice
    ? data.notice
    : stage.details || `Lendo ${data.statusFile}.`;
}

async function loadMonitor() {
  $("businessStatus").textContent = "Carregando monitor...";
  const data = await api("/api/business-monitor/retificacao-ret");
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

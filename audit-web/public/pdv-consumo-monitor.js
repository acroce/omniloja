let monitor = { fileRows: [], areas: [] };
let fileFilter = "imported";

function $(id) { return document.getElementById(id); }
function escapeHtml(value) { return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;"); }

async function api(path, options = {}) {
  const response = await fetch(path, { cache: "no-store", ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Não foi possível carregar o relatório.");
  return data;
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "-" : date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "America/Sao_Paulo" });
}

function renderAreas(data) {
  const areas = Array.isArray(data.areas) ? data.areas : [];
  $("areaRows").innerHTML = areas.length ? areas.map((area) => `<tr><td>${escapeHtml(area.name)}</td><td>${escapeHtml(area.equalToSource ?? "-")}</td><td>${escapeHtml(area.impConfirmed ?? "-")}</td><td>${escapeHtml(area.originalName ?? "-")}</td></tr>`).join("") : `<tr><td colspan="4" class="pdv-import-empty">Aguardando a classificação das áreas nos ARIUS.</td></tr>`;
}

function renderFiles() {
  const query = $("storeFilter").value.trim();
  const normalizedQuery = /^\d+$/.test(query) ? String(Number(query)) : query;
  const rows = (Array.isArray(monitor.fileRows) ? monitor.fileRows : []).filter((row) =>
    !row.stale && row.status === fileFilter && (!query || (row.store != null && String(Number(row.store)) === normalizedQuery)));
  $("filesList").innerHTML = rows.length ? rows.map((row) => `<article><strong>${escapeHtml(row.originalName || row.importedName || `Loja ${row.store || "-"}`)}</strong><span>${escapeHtml(row.environment || "-")} · ${escapeHtml(row.area || "-")} · Loja ${escapeHtml(row.store ?? "Global")} · ${row.status === "imported" ? "Marcador imp. registrado" : "Aguardando"}</span></article>`).join("") : "<p>Nenhum arquivo nesta seleção.</p>";
}

function render(data) {
  monitor = data;
  const starts = [...new Set((data.rounds || []).map((round) => round.start).filter(Boolean))];
  $("roundMeta").textContent = data.generatedAt
    ? `Janela de importação ${starts.length ? starts.map(formatTime).join(" / ") : "não iniciada"} até ${formatTime(data.generatedAt)} Brasília`
    : "Aguardando coleta dos servidores ARIUS.";
  $("reportNotice").textContent = [data.message, data.notice].filter(Boolean).join(" ") || "Conferência direta nos servidores ARIUS.";
  renderAreas(data);
  renderFiles();
}

async function load() { render(await api("/api/business-monitor/pdv-consumo")); }
async function refresh() { $("refreshButton").disabled = true; try { render(await api("/api/business-monitor/pdv-consumo/refresh", { method: "POST" })); } finally { $("refreshButton").disabled = false; } }
function closeFiles() { $("filesModal").hidden = true; }

$("refreshButton").addEventListener("click", () => refresh().catch((error) => { $("reportNotice").textContent = error.message; }));
$("filesButton").addEventListener("click", () => { $("filesModal").hidden = false; renderFiles(); });
$("filesClose").addEventListener("click", closeFiles);
document.querySelector("[data-close-files]").addEventListener("click", closeFiles);
$("storeFilter").addEventListener("input", renderFiles);
document.querySelectorAll("[data-file-filter]").forEach((button) => button.addEventListener("click", () => { fileFilter = button.dataset.fileFilter; document.querySelectorAll("[data-file-filter]").forEach((item) => item.classList.toggle("is-active", item === button)); renderFiles(); }));
load().catch((error) => { $("reportNotice").textContent = error.message; });
setInterval(() => load().catch(() => {}), 2 * 60 * 1000);

const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const refreshIntervalMs = 60 * 1000;
let nextRefreshAt = Date.now() + refreshIntervalMs;
let refreshTimer = null;
let selectedTransaction = null;
let selectedDetailPayload = null;
let transactionDetailsLoading = false;
let currentMonitorData = null;
let manualErrorPayload = null;
let manualErrorLoading = false;
let activeSapTab = "monitoramento";
let triageRoutingRules = [];
let triageReasonCatalog = [];
let triageOccurrences = [];
let triageChatChannels = [];
let triageReasonCounts = new Map();
let triageDepartmentCatalog = [
  "Cadastro SAP",
  "SAP Logistica / Fiscal",
  "Operacao da loja",
  "TI Pleno / Integracoes",
  "SAP Funcional",
  "Triagem TI / Integracoes",
];

function $(id) {
  return document.getElementById(id);
}

function setActiveSapTab(tab) {
  activeSapTab = ["monitoramento", "estatisticas", "encaminhamento"].includes(tab) ? tab : "monitoramento";
  document.querySelectorAll("[data-sap-tab]").forEach((section) => {
    section.hidden = section.dataset.sapTab !== activeSapTab;
  });
  document.querySelectorAll("[data-sap-tab-button]").forEach((button) => {
    const active = button.dataset.sapTabButton === activeSapTab;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Erro na requisicao.");
  return data;
}

function formatNumber(value) {
  return qty.format(Number(value || 0));
}

function formatDecimal(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return decimal.format(Number(value));
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

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(11, 16);
  return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
}

function formatPeriod(start, end) {
  return `${formatDateTime(start)} ate ${formatDateTime(end)}`;
}

function minutesBetween(start, end, fallback = 10) {
  const startMs = new Date(start).getTime();
  const endMs = new Date(end).getTime();
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs) || endMs <= startMs) return fallback;
  return Math.max(1, Math.round((endMs - startMs) / 60000));
}

function formatClock(value = new Date()) {
  return value.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function lastHours(items, hours) {
  const cutoff = Date.now() - hours * 60 * 60 * 1000;
  return (items || []).filter((item) => {
    const collectedAt = new Date(item.collectedAt).getTime();
    return Number.isFinite(collectedAt) && collectedAt >= cutoff;
  });
}

function kpi(label, value, sub, cls = "") {
  return `<div class="kpi"><span>${label}</span><strong class="${cls}">${value}</strong><small>${sub || ""}</small></div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function shortLabel(label) {
  return String(label || "")
    .replace("Enviar Dados Nota Devolução Para Backoffice Loja", "Nota devolucao")
    .replace("Movimento de Estoque - ", "")
    .replace("Portaria 4Tax", "Portaria 4Tax");
}

function isRetryInProgress(reason) {
  return /^tentativa sap em andamento\s*\(\d+\/5\)/i.test(String(reason || "").trim());
}

function isSapProblem(reason) {
  const value = String(reason || "").trim();
  return value !== "Sucesso" && value !== "Outro/sem classificacao" && !isRetryInProgress(value);
}

function displayProblemReasons(tx) {
  return [
    ...(tx?.errorReasons || []).map((item) => ({ ...item, classification: "real" })),
    ...(tx?.unclassifiedReasons || []).map((item) => ({ ...item, classification: "pending" })),
  ];
}

function seriesFor(history, metric, transactionId = "") {
  return (history || []).map((snapshot) => {
    const tx = transactionId
      ? (snapshot.transactions || []).find((item) => item.id === transactionId)
      : null;
    const source = transactionId ? tx : snapshot.totals;
    return {
      label: formatTime(snapshot.collectedAt),
      value: Number(source?.[metric] || 0),
    };
  }).filter((point) => Number.isFinite(point.value));
}

function lineChart(points, { suffix = "", color = "#0f5f9f" } = {}) {
  if (!points.length) return `<div class="empty-chart">Sem historico suficiente.</div>`;
  const width = 720;
  const height = 220;
  const pad = 34;
  const max = Math.max(...points.map((point) => point.value), 1);
  const min = Math.min(...points.map((point) => point.value), 0);
  const span = Math.max(max - min, 1);
  const x = (index) => pad + (points.length === 1 ? 0 : index * (width - pad * 2) / (points.length - 1));
  const y = (value) => height - pad - ((value - min) / span) * (height - pad * 2);
  const path = points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
  const area = `${path} L${x(points.length - 1).toFixed(1)},${height - pad} L${pad},${height - pad} Z`;
  const last = points[points.length - 1];
  const ticks = points.filter((_, index) => index === 0 || index === points.length - 1 || index === Math.floor(points.length / 2));
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="chart-axis"></line>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="chart-axis"></line>
      <path d="${area}" fill="${color}" opacity="0.12"></path>
      <path d="${path}" fill="none" stroke="${color}" stroke-width="3"></path>
      ${points.map((point, index) => `<circle cx="${x(index).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="3" fill="${color}"><title>${point.label}: ${formatDecimal(point.value)}${suffix}</title></circle>`).join("")}
      <text x="${pad}" y="22" class="chart-label">${formatDecimal(max)}${suffix}</text>
      <text x="${width - pad}" y="22" class="chart-label chart-label-end">Atual: ${formatDecimal(last.value)}${suffix}</text>
      ${ticks.map((point, index) => `<text x="${x(points.indexOf(point)).toFixed(1)}" y="${height - 8}" class="chart-label ${index === ticks.length - 1 ? "chart-label-end" : ""}">${point.label}</text>`).join("")}
    </svg>
  `;
}

function stackedStatusChart(items) {
  const data = (items || []).map((item) => ({
    label: shortLabel(item.label),
    success: Number(item.success || 0),
    errors: Number(item.errors || 0),
    ignored: Number(item.ignored || 0),
    total: Number(item.monitoredEvents ?? ((item.success || 0) + (item.errors || 0) + (item.other || 0))),
  })).filter((item) => item.total > 0 || item.success > 0 || item.errors > 0);
  if (!data.length) return `<div class="empty-chart">Sem dados para exibir.</div>`;
  const max = Math.max(...data.map((item) => item.total), 1);
  return `<div class="bar-list">
    <div class="bar-legend">
      <span><i class="legend-dot success-dot"></i>Sucessos</span>
      <span><i class="legend-dot error-dot"></i>Erros</span>
    </div>
    ${data.map((item) => {
      const successWidth = item.total ? (item.success / item.total * 100) : 0;
      const errorWidth = item.total ? (item.errors / item.total * 100) : 0;
      const trackWidth = (item.total / max * 100).toFixed(1);
      const title = `${item.label}: ${formatNumber(item.total)} monitoradas, ${formatNumber(item.success)} sucessos, ${formatNumber(item.errors)} erros, ${formatNumber(item.ignored)} ignorados`;
      return `
    <div class="bar-row">
      <span>${item.label}</span>
      <div class="bar-track" title="${escapeHtml(title)}">
        <div class="stacked-bar" style="width:${trackWidth}%">
          <div class="bar-fill bar-fill-success" style="width:${successWidth.toFixed(1)}%"></div>
          <div class="bar-fill bar-fill-error" style="width:${errorWidth.toFixed(1)}%"></div>
        </div>
      </div>
      <strong>${formatNumber(item.total)}</strong>
    </div>
  `;
    }).join("")}</div>`;
}

function apiErrorReasonChart(buckets) {
  const txMap = new Map();
  for (const bucket of buckets || []) {
    for (const tx of bucket.transactions || []) {
      const current = txMap.get(tx.id) || {
        id: tx.id,
        label: shortLabel(tx.label),
        totalErrors: 0,
        reasons: new Map(),
      };
      for (const reason of displayProblemReasons(tx)) {
        const count = Number(reason.count || 0);
        if (!count) continue;
        current.totalErrors += count;
        current.reasons.set(reason.reason, (current.reasons.get(reason.reason) || 0) + count);
      }
      txMap.set(tx.id, current);
    }
  }
  const rows = [...txMap.values()]
    .filter((item) => item.totalErrors > 0 || [...item.reasons.values()].some(Boolean))
    .sort((a, b) => b.totalErrors - a.totalErrors);
  if (!rows.length) return `<div class="empty-chart">Sem erro SAP real nesse zoom.</div>`;
  const colors = ["#d92d20", "#0f5f9f", "#9a6700", "#7c3aed", "#047857", "#c2410c", "#7c8597"];
  const max = Math.max(...rows.map((row) => row.totalErrors), 1);
  // A barra e uma referencia visual. A escala comprimida preserva leitura de
  // causas pequenas, enquanto o numero ao lado continua sendo o valor real.
  const visualWidth = (count) => {
    const value = Number(count || 0);
    if (!value) return 0;
    return Math.max(2.5, Math.sqrt(value / max) * 100);
  };
  return `<div class="bar-list api-error-chart api-error-tree">
    ${rows.map((row) => {
      const reasons = [...row.reasons.entries()]
        .filter(([, count]) => Number(count || 0) > 0)
        .sort((a, b) => b[1] - a[1]);
      return `
        <div class="api-error-parent">
          <div class="bar-row api-error-row api-error-summary">
            <span title="${escapeHtml(row.id)}">${escapeHtml(row.label)}</span>
            <div class="bar-track" title="${escapeHtml(`${row.label}: ${formatNumber(row.totalErrors)} problema(s) SAP`)}">
              <div class="bar-fill api-error-summary-fill" style="width:${visualWidth(row.totalErrors).toFixed(1)}%"></div>
            </div>
            <strong>${formatNumber(row.totalErrors)}</strong>
          </div>
          <div class="api-error-children">
            ${reasons.map(([reason, count], index) => `
              <div class="bar-row api-error-row api-error-child">
                <span title="${escapeHtml(reason)}">${escapeHtml(reason)}</span>
                <div class="bar-track" title="${escapeHtml(`${reason}: ${formatNumber(count)} ocorrencia(s)`)}">
                  <div class="bar-fill" style="width:${visualWidth(count).toFixed(1)}%; background:${colors[index % colors.length]}"></div>
                </div>
                <strong>${formatNumber(count)}</strong>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }).join("")}
  </div>`;
}

function historyBucketLabel(bucket) {
  return bucket?.label || formatTime(bucket?.bucketStart);
}

function selectedHistoryBuckets(buckets) {
  const startValue = $("historyStart")?.value || "";
  const endValue = $("historyEnd")?.value || "";
  const start = startValue ? new Date(startValue).getTime() : Number.NEGATIVE_INFINITY;
  const end = endValue ? new Date(endValue).getTime() : Number.POSITIVE_INFINITY;
  return (buckets || []).filter((bucket) => {
    const bucketStart = new Date(bucket.bucketStart).getTime();
    const bucketEnd = new Date(bucket.bucketEnd).getTime();
    return Number.isFinite(bucketStart) && Number.isFinite(bucketEnd) && bucketEnd >= start && bucketStart <= end;
  });
}

function classifyHistoryBuckets(buckets, grouping) {
  if (grouping === "period") return buckets;
  const weekdays = ["Domingo", "Segunda", "Terca", "Quarta", "Quinta", "Sexta", "Sabado"];
  const groups = new Map();
  for (const bucket of buckets) {
    const date = new Date(bucket.bucketStart);
    if (Number.isNaN(date.getTime())) continue;
    let key;
    let label;
    let order;
    if (grouping === "hourOfDay") {
      order = date.getHours();
      key = `hour-${order}`;
      label = `${String(order).padStart(2, "0")}:00`;
    } else if (grouping === "weekday") {
      order = date.getDay();
      key = `weekday-${order}`;
      label = weekdays[order];
    } else {
      order = date.getDate();
      key = `month-day-${order}`;
      label = `Dia ${String(order).padStart(2, "0")}`;
    }
    const current = groups.get(key) || {
      bucketStart: bucket.bucketStart,
      bucketEnd: bucket.bucketEnd,
      label,
      order,
      transactions: new Map(),
    };
    if (new Date(bucket.bucketStart).getTime() < new Date(current.bucketStart).getTime()) current.bucketStart = bucket.bucketStart;
    if (new Date(bucket.bucketEnd).getTime() > new Date(current.bucketEnd).getTime()) current.bucketEnd = bucket.bucketEnd;
    for (const tx of bucket.transactions || []) {
      const target = current.transactions.get(tx.id) || { id: tx.id, label: tx.label, errorReasons: new Map(), unclassifiedReasons: new Map(), errors: 0 };
      target.errors += Number(tx.errors || 0);
      for (const reason of tx.errorReasons || []) {
        target.errorReasons.set(reason.reason, (target.errorReasons.get(reason.reason) || 0) + Number(reason.count || 0));
      }
      for (const reason of tx.unclassifiedReasons || []) {
        target.unclassifiedReasons.set(reason.reason, (target.unclassifiedReasons.get(reason.reason) || 0) + Number(reason.count || 0));
      }
      current.transactions.set(tx.id, target);
    }
    groups.set(key, current);
  }
  return [...groups.values()]
    .sort((a, b) => a.order - b.order)
    .map((group) => ({
      bucketStart: group.bucketStart,
      bucketEnd: group.bucketEnd,
      label: group.label,
      transactions: [...group.transactions.values()].map((tx) => ({
        id: tx.id,
        label: tx.label,
        errors: tx.errors,
        errorReasons: [...tx.errorReasons.entries()].map(([reason, count]) => ({ reason, count })),
        unclassifiedReasons: [...tx.unclassifiedReasons.entries()].map(([reason, count]) => ({ reason, count })),
      })),
    }));
}

function transactionErrorLineChart(buckets) {
  const sourceBuckets = buckets || [];
  if (!sourceBuckets.length) return `<div class="empty-chart">Aguardando historico agregado.</div>`;
  const txTotals = new Map();
  for (const bucket of sourceBuckets) {
    for (const tx of bucket.transactions || []) {
      const current = txTotals.get(tx.id) || { id: tx.id, label: shortLabel(tx.label), errors: 0 };
      current.errors += displayProblemReasons(tx)
        .reduce((sum, item) => sum + Number(item.count || 0), 0);
      txTotals.set(tx.id, current);
    }
  }
  const topTransactions = [...txTotals.values()]
    .filter((item) => item.errors > 0)
    .sort((a, b) => b.errors - a.errors)
    .slice(0, 6);
  if (!topTransactions.length) return `<div class="empty-chart">Sem problema SAP para comparar nesse zoom.</div>`;

  const colors = ["#d92d20", "#0f5f9f", "#9a6700", "#7c3aed", "#047857", "#c2410c"];
  const width = 720;
  const height = 220;
  const pad = 34;
  const pointsByTx = topTransactions.map((tx, txIndex) => ({
    ...tx,
    color: colors[txIndex % colors.length],
    points: sourceBuckets.map((bucket) => {
      const bucketTx = (bucket.transactions || []).find((item) => item.id === tx.id);
      const value = displayProblemReasons(bucketTx)
        .reduce((sum, item) => sum + Number(item.count || 0), 0);
      return {
        label: historyBucketLabel(bucket),
        value,
      };
    }),
  }));
  const max = Math.max(...pointsByTx.flatMap((tx) => tx.points.map((point) => point.value)), 1);
  const x = (index) => pad + (sourceBuckets.length === 1 ? (width - pad * 2) / 2 : index * (width - pad * 2) / (sourceBuckets.length - 1));
  const y = (value) => height - pad - (value / max) * (height - pad * 2);
  const ticks = sourceBuckets.filter((_, index) => index === 0 || index === sourceBuckets.length - 1 || index === Math.floor(sourceBuckets.length / 2));
  return `
    <div class="line-legend chart-legend">
      ${pointsByTx.map((tx) => `<span title="${escapeHtml(tx.id)}"><i class="legend-dot" style="background:${tx.color}"></i>${escapeHtml(tx.label)}</span>`).join("")}
    </div>
    <svg viewBox="0 0 ${width} ${height}" role="img">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="chart-axis"></line>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="chart-axis"></line>
      ${pointsByTx.map((tx) => {
        const path = tx.points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point.value).toFixed(1)}`).join(" ");
        return `
          <path d="${path}" fill="none" stroke="${tx.color}" stroke-width="3"></path>
          ${tx.points.map((point, index) => `<circle cx="${x(index).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="3" fill="${tx.color}"><title>${tx.label} ${point.label}: ${formatNumber(point.value)} problema(s) SAP</title></circle>`).join("")}
        `;
      }).join("")}
      <text x="${pad}" y="22" class="chart-label">Max: ${formatNumber(max)} problema(s)</text>
      ${ticks.map((bucket, index) => {
        const pointIndex = sourceBuckets.indexOf(bucket);
        return `<text x="${x(pointIndex).toFixed(1)}" y="${height - 8}" class="chart-label ${index === ticks.length - 1 ? "chart-label-end" : ""}">${historyBucketLabel(bucket)}</text>`;
      }).join("")}
    </svg>
  `;
}

function normalizedReason(value) {
  return String(value || "").trim().toLocaleLowerCase("pt-BR");
}

function isIgnoredAggregateReason(reason, tx, data) {
  const normalized = normalizedReason(reason);
  if (!normalized) return true;
  const ignored = new Set((tx?.ignoredReasons || []).map((item) => normalizedReason(item.reason)));
  if (ignored.has(normalized)) return true;
  return (data?.latest?.ignorePatterns || []).some((item) => {
    const pattern = normalizedReason(item.pattern || item.reason || item);
    return pattern && normalized.includes(pattern);
  });
}

function aggregateProblemReasons(tx, data) {
  const explicit = displayProblemReasons(tx).filter((item) => Number(item.count || 0) > 0);
  if (explicit.length) return explicit;
  return (tx?.reasons || [])
    .filter((item) => Number(item.count || 0) > 0)
    .filter((item) => String(item.reason || "") !== "Sucesso")
    .filter((item) => !isRetryInProgress(item.reason))
    .filter((item) => !isIgnoredAggregateReason(item.reason, tx, data));
}

function departmentForAggregateReason(reason) {
  const normalized = normalizedReason(reason);
  const rule = [...triageRoutingRules]
    .reverse()
    .find((item) => item.enabled !== false && normalized && normalized.includes(normalizedReason(item.pattern)));
  return rule?.department || "Sem area definida";
}

function render24HourErrorTreatment(data) {
  const now = new Date(data.now || data.updatedAt || Date.now()).getTime();
  const cutoff = now - 24 * 60 * 60 * 1000;
  const hourly = data.aggregates?.hour || [];
  const allReasons = new Map();
  const recentReasons = new Map();

  for (const bucket of hourly) {
    const bucketAt = new Date(bucket.bucketEnd || bucket.bucketStart).getTime();
    if (!Number.isFinite(bucketAt)) continue;
    for (const tx of bucket.transactions || []) {
      for (const item of aggregateProblemReasons(tx, data)) {
        const count = Number(item.count || 0);
        if (!count) continue;
        const reason = String(item.reason || "Sem classificacao");
        const key = `${tx.id || tx.label}\u0000${reason}`;
        const target = allReasons.get(key) || {
          id: tx.id || "",
          label: tx.label || tx.id || "API sem nome",
          reason,
          department: departmentForAggregateReason(reason),
          total: 0,
          total24h: 0,
          windows24h: 0,
          lastAt: "",
        };
        target.total += count;
        if (!target.lastAt || bucketAt > new Date(target.lastAt).getTime()) target.lastAt = bucket.bucketEnd || bucket.bucketStart;
        if (bucketAt >= cutoff) {
          target.total24h += count;
          target.windows24h += 1;
          recentReasons.set(key, target);
        }
        allReasons.set(key, target);
      }
    }
  }

  const recent = [...recentReasons.values()].filter((item) => item.total24h > 0);
  const departments = new Map();
  for (const item of recent) {
    const current = departments.get(item.department) || { department: item.department, total: 0, reasons: new Set() };
    current.total += item.total24h;
    current.reasons.add(item.reason);
    departments.set(item.department, current);
  }
  const departmentRows = [...departments.values()].sort((a, b) => b.total - a.total || a.department.localeCompare(b.department, "pt-BR"));
  const total24h = departmentRows.reduce((sum, item) => sum + item.total, 0);
  $("statisticsDepartment24hTable").innerHTML = `
    <thead><tr><th>Departamento</th><th>Erros diferentes</th><th>Qtde 24h</th></tr></thead>
    <tbody>${departmentRows.map((item) => `<tr>
      <td><strong>${escapeHtml(item.department)}</strong></td>
      <td>${formatNumber(item.reasons.size)}</td>
      <td class="negative"><strong>${formatNumber(item.total)}</strong></td>
    </tr>`).join("") || '<tr><td colspan="3">Sem erros SAP nas ultimas 24 horas.</td></tr>'}
    ${departmentRows.length ? `<tr class="statistics-total-row"><td><strong>Total</strong></td><td>${formatNumber(new Set(recent.map((item) => item.reason)).size)}</td><td class="negative"><strong>${formatNumber(total24h)}</strong></td></tr>` : ""}
    </tbody>`;
  $("statisticsDepartment24hStatus").textContent = `Janela fixa: ultimas 24 horas ate ${formatDateTime(data.updatedAt || data.now)}. ${formatNumber(total24h)} ocorrencia(s) distribuida(s) em ${formatNumber(departmentRows.length)} area(s).`;

  const recurring = recent
    .filter((item) => item.windows24h >= 2)
    .sort((a, b) => b.total24h - a.total24h)
    .slice(0, 8);
  const inactive = [...allReasons.values()]
    .filter((item) => item.total24h === 0)
    .sort((a, b) => new Date(b.lastAt).getTime() - new Date(a.lastAt).getTime())
    .slice(0, 8);
  const errorRow = (item, status) => `<tr title="${escapeHtml(`${item.label} | ${item.reason}`)}"><td><strong>${escapeHtml(shortLabel(item.label))}</strong><small>${escapeHtml(item.reason)}</small></td><td>${formatNumber(status === "active" ? item.total24h : item.total)}</td><td>${status === "active" ? `${formatNumber(item.windows24h)} janela(s)` : `ultima: ${formatDateTime(item.lastAt)}`}</td></tr>`;
  $("statisticsRecurrence24h").innerHTML = `
    <div class="statistics-recurrence-section">
      <h3>Recorrentes e ativos</h3>
      <table><thead><tr><th>API / erro</th><th>Qtde 24h</th><th>Reincidencia</th></tr></thead><tbody>${recurring.map((item) => errorRow(item, "active")).join("") || '<tr><td colspan="3">Nenhum erro reincidente nas ultimas 24 horas.</td></tr>'}</tbody></table>
    </div>
    <div class="statistics-recurrence-section">
      <h3>Sem ocorrencia recente</h3>
      <table><thead><tr><th>API / erro</th><th>Historico</th><th>Ultima ocorrencia</th></tr></thead><tbody>${inactive.map((item) => errorRow(item, "inactive")).join("") || '<tr><td colspan="3">Nenhum erro anterior fora da janela atual.</td></tr>'}</tbody></table>
    </div>`;
  $("statisticsRecurrenceStatus").textContent = "Recorrentes: apareceram em duas ou mais janelas na ultimas 24 horas. Sem ocorrencia recente: existem no historico, mas nao voltaram a ocorrer na janela atual.";
}

function renderAggregateHistory(data) {
  const grain = $("historyGrain")?.value || "hour";
  const grouping = $("historyGrouping")?.value || "period";
  const baseBuckets = grouping === "period"
    ? (data.aggregates?.[grain] || [])
    : (data.aggregates?.hour || []);
  const filteredBuckets = selectedHistoryBuckets(baseBuckets);
  const buckets = classifyHistoryBuckets(filteredBuckets, grouping);
  $("historyReasonChart").innerHTML = apiErrorReasonChart(buckets);
  $("historyTransactionLineChart").innerHTML = transactionErrorLineChart(buckets);
  const grouped = new Map();
  for (const bucket of buckets) {
    for (const tx of bucket.transactions || []) {
      const errorReasons = displayProblemReasons(tx).filter((item) => Number(item.count || 0) > 0);
      for (const reason of errorReasons) {
        const classification = grouping === "period" ? "" : historyBucketLabel(bucket);
        const key = `${classification}\u0000${tx.id || tx.label}\u0000${reason.reason}`;
        const current = grouped.get(key) || {
          start: bucket.bucketStart,
          end: bucket.bucketEnd,
          classification,
          tx,
          reason: reason.reason,
          count: 0,
        };
        current.count += Number(reason.count || 0);
        if (new Date(bucket.bucketStart).getTime() < new Date(current.start).getTime()) current.start = bucket.bucketStart;
        if (new Date(bucket.bucketEnd).getTime() > new Date(current.end).getTime()) current.end = bucket.bucketEnd;
        grouped.set(key, current);
      }
    }
  }
  const rows = [...grouped.values()].sort((a, b) => b.count - a.count || String(a.tx.label || "").localeCompare(String(b.tx.label || "")));
  const classificationHeader = grouping === "hourOfDay"
    ? "Hora do dia"
    : grouping === "weekday" ? "Dia da semana"
      : grouping === "dayOfMonth" ? "Dia do mes"
        : "";
  $("historyReasonTable").innerHTML = `
    <thead>
      <tr>
        ${classificationHeader ? `<th>${classificationHeader}</th>` : ""}
        <th>API</th>
        <th>Motivo</th>
        <th>Ocorrencias no periodo</th>
      </tr>
    </thead>
    <tbody>${rows.slice(0, 300).map((row, index) => `
      <tr class="clickable-row" data-history-index="${index}" title="Clique para abrir os detalhes desse motivo">
        ${classificationHeader ? `<td><strong>${escapeHtml(row.classification)}</strong></td>` : ""}
        <td><strong>${shortLabel(row.tx.label)}</strong><small>${row.tx.id || ""}</small></td>
        <td>${escapeHtml(row.reason)}</td>
        <td>${formatNumber(row.count)}</td>
      </tr>
    `).join("")}</tbody>
  `;
  $("historyReasonTable").querySelectorAll("[data-history-index]").forEach((row) => {
    row.addEventListener("click", () => {
      const item = rows[Number(row.dataset.historyIndex)];
      if (!item) return;
      openTransactionModal(item.tx, {
        start: item.start,
        end: item.end,
        status: `${item.classification ? `${item.classification} | ` : ""}${item.reason}: ${formatNumber(item.count)} ocorrencia(s) em ${formatPeriod(item.start, item.end)}`,
      });
      loadTransactionDetails({ start: item.start, end: item.end });
    });
  });
  const groupingLabel = grouping === "period"
    ? `zoom de ${grain === "hour" ? "hora" : grain === "day" ? "dia" : grain === "week" ? "semana" : "mes"}`
    : grouping === "hourOfDay" ? "hora do dia"
      : grouping === "weekday" ? "dia da semana"
        : "dia do mes";
  const selectedStart = $("historyStart")?.value || "";
  const selectedEnd = $("historyEnd")?.value || "";
  const scope = selectedStart || selectedEnd
    ? `${selectedStart ? formatDateTime(selectedStart) : "inicio do historico"} ate ${selectedEnd ? formatDateTime(selectedEnd) : "agora"}`
    : "todo o historico disponivel";
  $("statisticsAppliedScope").textContent = `Filtro aplicado a todas as barras, ao grafico de linha e ao ranking: ${scope}. Base: ${formatNumber(filteredBuckets.length)} ponto(s) de coleta.`;
  $("historyReasonStatus").textContent = buckets.length
    ? `Visao consolidada por ${groupingLabel}, classificada por quantidade. Clique em uma linha para abrir o detalhe da API no intervalo em que esse motivo ocorreu.`
    : "Sem historico agregado ainda; ele sera preenchido nas proximas coletas.";
}

function checkinTrendChart(history) {
  const points = (history || []).map((item) => ({
    label: formatTime(item.collectedAt),
    total: Number(item.total || 0),
    pending: Number(item.semCheckin || 0),
    done: Number(item.comCheckin || 0),
  })).filter((point) => Number.isFinite(point.total) && Number.isFinite(point.pending) && Number.isFinite(point.done));
  if (!points.length) return `<div class="empty-chart">Aguardando a primeira coleta de notas.</div>`;
  const width = 720;
  const height = 220;
  const pad = 34;
  const max = Math.max(...points.flatMap((point) => [point.total, point.pending, point.done]), 1);
  const x = (index) => points.length === 1 ? width / 2 : pad + index * (width - pad * 2) / (points.length - 1);
  const y = (value) => height - pad - (value / max) * (height - pad * 2);
  const pathFor = (metric) => points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)},${y(point[metric]).toFixed(1)}`).join(" ");
  const ticks = points.filter((_, index) => index === 0 || index === points.length - 1 || index === Math.floor(points.length / 2));
  const last = points[points.length - 1];
  return `
    <svg viewBox="0 0 ${width} ${height}" role="img">
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="chart-axis"></line>
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="chart-axis"></line>
      <path d="${pathFor("total")}" fill="none" stroke="#17324d" stroke-width="2" opacity="0.75"></path>
      <path d="${pathFor("pending")}" fill="none" stroke="#d92d20" stroke-width="3"></path>
      <path d="${pathFor("done")}" fill="none" stroke="#047857" stroke-width="3"></path>
      ${points.map((point, index) => `
        <circle cx="${x(index).toFixed(1)}" cy="${y(point.total).toFixed(1)}" r="2.5" fill="#17324d"><title>${point.label}: ${formatNumber(point.total)} total</title></circle>
        <circle cx="${x(index).toFixed(1)}" cy="${y(point.pending).toFixed(1)}" r="3" fill="#d92d20"><title>${point.label}: ${formatNumber(point.pending)} sem check-in</title></circle>
        <circle cx="${x(index).toFixed(1)}" cy="${y(point.done).toFixed(1)}" r="3" fill="#047857"><title>${point.label}: ${formatNumber(point.done)} feitas no total atual</title></circle>
      `).join("")}
      <text x="${pad}" y="22" class="chart-label">Total: ${formatNumber(last.total)} · Faltam: ${formatNumber(last.pending)}</text>
      <text x="${width - pad}" y="22" class="chart-label chart-label-end">Feitas: ${formatNumber(last.done)}</text>
      ${ticks.map((point, index) => `<text x="${x(points.indexOf(point)).toFixed(1)}" y="${height - 8}" class="chart-label ${index === ticks.length - 1 ? "chart-label-end" : ""}">${point.label}</text>`).join("")}
    </svg>
  `;
}

function renderReasons(transactions) {
  const rows = [];
  for (const tx of transactions || []) {
    for (const reason of displayProblemReasons(tx)) {
      rows.push([shortLabel(tx.label), reason.reason, reason.count]);
    }
  }
  rows.sort((a, b) => b[2] - a[2]);
  $("reasonTable").innerHTML = `
    <thead><tr><th>Transacao</th><th>Motivo</th><th>Qtde</th></tr></thead>
    <tbody>${rows.slice(0, 12).map((row) => `<tr><td>${row[0]}</td><td>${row[1]}</td><td>${formatNumber(row[2])}</td></tr>`).join("")}</tbody>
  `;
}

function triageReference(item) {
  return [
    item.store ? `Loja ${item.store}` : "",
    item.note ? `NF/doc ${item.note}` : "",
    item.accessKey ? `Chave ${item.accessKey}` : "",
    item.material ? `Produto ${item.material}` : "",
    item.center ? `Centro ${item.center}` : "",
  ].filter(Boolean).join(" · ") || "Sem referencia no log";
}

function toLocalInputValue(date) {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function occurrenceMatchesDepartment(item, department) {
  const context = [item.reason, item.sapCode, item.sapMessage, item.returnReason, item.transaction, item.transactionId, item.raw].join("\n").toLocaleLowerCase("pt-BR");
  const rules = triageRoutingRules.filter((rule) => String(rule.department || "") === department);
  return rules.some((rule) => context.includes(String(rule.pattern || "").toLocaleLowerCase("pt-BR")))
    || (!rules.length && String(item.department || "") === department);
}

function renderTriageMemoDepartments() {
  const select = $("triageMemoDepartment");
  const selected = select.value;
  const departments = [...new Set([
    ...triageRoutingRules.map((rule) => rule.department),
    ...triageOccurrences.map((item) => item.department),
  ].filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  select.innerHTML = `<option value="">Selecione</option>${departments.map((department) => `<option value="${escapeHtml(department)}">${escapeHtml(department)}</option>`).join("")}`;
  if (departments.includes(selected)) select.value = selected;
}

function renderTriageRoutingDepartments() {
  const select = $("triageRoutingDepartment");
  const selected = select.value;
  const departments = [...new Set(triageChatChannels.map((channel) => channel.department).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "pt-BR"));
  select.innerHTML = `<option value="">${departments.length ? "Selecione o departamento" : "Cadastre primeiro o departamento abaixo"}</option>${departments.map((department) => `<option value="${escapeHtml(department)}">${escapeHtml(department)}</option>`).join("")}`;
  if (departments.includes(selected)) select.value = selected;
}

function buildTriageMemo({ all = false } = {}) {
  const department = $("triageMemoDepartment").value;
  const start = new Date($("triageMemoStart").value);
  const end = new Date($("triageMemoEnd").value);
  if (!department || (!all && (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end < start))) throw new Error("Informe departamento e um periodo valido.");
  const items = triageOccurrences.filter((item) => {
    const at = new Date(item.occurrenceAt).getTime();
    return Number.isFinite(at) && occurrenceMatchesDepartment(item, department) && (all || (at >= start.getTime() && at <= end.getTime()));
  });
  const counts = new Map();
  items.forEach((item) => counts.set(item.reason || "Sem motivo", (counts.get(item.reason || "Sem motivo") || 0) + 1));
  const text = [
    `Monitor SAP - erros para ${department}`,
    `Periodo: ${all ? "todo o historico coletado" : `${formatDateTime(start)} ate ${formatDateTime(end)}`}`,
    `Ocorrencias: ${formatNumber(items.length)}`,
    "",
    "Resumo por erro:",
    ...[...counts.entries()].sort((a, b) => b[1] - a[1]).map(([reason, count]) => `- ${reason}: ${formatNumber(count)}`),
    "",
    "Referencias:",
    ...items.slice(0, 35).map((item) => `- ${formatDateTime(item.occurrenceAt)} | ${shortLabel(item.transaction)} | ${item.reason} | ${triageReference(item)}`),
  ].join("\n");
  return { text, count: items.length };
}

function generateTriageMemo() {
  try {
    const memo = buildTriageMemo();
    $("triageMemoBody").textContent = memo.text;
    $("copyTriageMemo").disabled = false;
    $("sendTriageMemo").disabled = false;
    $("triageMemoStatus").textContent = `${formatNumber(memo.count)} ocorrencia(s) no periodo selecionado.`;
  } catch (error) {
    $("triageMemoBody").textContent = "Selecione o departamento e o periodo.";
    $("copyTriageMemo").disabled = true;
    $("sendTriageMemo").disabled = true;
    $("triageMemoStatus").textContent = error.message;
  }
}

function renderTriage(data) {
  const triage = data.triage || {};
  const occurrences = triage.occurrences || [];
  triageOccurrences = occurrences;
  const departments = triage.departments || [];
  triageDepartmentCatalog = [...new Set([
    ...triageDepartmentCatalog,
    ...departments.map((item) => item.department),
  ].filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  const reasons = triage.reasons || [];
  triageReasonCounts = new Map();
  for (const item of occurrences) {
    const reason = String(item.reason || "").trim();
    if (reason) triageReasonCounts.set(reason, (triageReasonCounts.get(reason) || 0) + 1);
  }
  triageReasonCatalog = [...triageReasonCounts.keys()].sort((a, b) => a.localeCompare(b, "pt-BR"));
  const referenceAt = new Date(triage.updatedAt || data.updatedAt || Date.now()).getTime();
  const cutoff24h = referenceAt - 24 * 60 * 60 * 1000;
  const occurrences24h = occurrences.filter((item) => {
    const at = new Date(item.occurrenceAt).getTime();
    return Number.isFinite(at) && at >= cutoff24h && at <= referenceAt;
  });
  const queueByDepartment = new Map();
  for (const item of occurrences24h) {
    const department = item.department || "Sem area definida";
    const current = queueByDepartment.get(department) || { department, occurrences: 0, reasonOccurrences: new Map() };
    current.occurrences += 1;
    const reason = String(item.reason || "Sem motivo");
    current.reasonOccurrences.set(reason, (current.reasonOccurrences.get(reason) || 0) + 1);
    queueByDepartment.set(department, current);
  }
  const queueRows = [...queueByDepartment.values()]
    .map((item) => ({ ...item, recurring: [...item.reasonOccurrences.values()].filter((count) => count >= 2).length }))
    .sort((a, b) => b.occurrences - a.occurrences || a.department.localeCompare(b.department, "pt-BR"));
  const rankingByReason = new Map();
  for (const item of occurrences24h) {
    const department = item.department || "Sem area definida";
    const reason = String(item.reason || "Sem motivo");
    const key = `${department}\u0000${reason}`;
    const current = rankingByReason.get(key) || { department, reason, occurrences: 0 };
    current.occurrences += 1;
    rankingByReason.set(key, current);
  }
  const rankingRows = [...rankingByReason.values()]
    .sort((a, b) => b.occurrences - a.occurrences || a.department.localeCompare(b.department, "pt-BR") || a.reason.localeCompare(b.reason, "pt-BR"));
  $("triageUpdatedAt").textContent = triage.updatedAt
    ? `Ultimas 24 h · atualizado ${formatDateTime(triage.updatedAt)}`
    : "Aguardando primeira coleta";
  $("triageDepartmentTable").innerHTML = `
    <thead><tr><th>Departamento</th><th>Ocorrencias 24h</th><th>Erros reincidentes</th></tr></thead>
    <tbody>${queueRows.slice(0, 8).map((item) => `<tr><td><strong class="cell-ellipsis" title="${escapeHtml(item.department)}">${escapeHtml(item.department)}</strong></td><td>${formatNumber(item.occurrences)}</td><td>${formatNumber(item.recurring)}</td></tr>`).join("") || '<tr><td colspan="3">Nenhuma ocorrencia nas ultimas 24 horas.</td></tr>'}</tbody>`;
  $("triageReasonTable").innerHTML = `
    <colgroup><col class="reason-department-column"><col class="reason-error-column"><col class="reason-quantity-column"></colgroup>
    <thead><tr><th>Departamento</th><th>Erro</th><th>Qtde 24h</th></tr></thead>
    <tbody>${rankingRows.slice(0, 8).map((item) => `<tr title="${escapeHtml(item.reason)}"><td title="${escapeHtml(item.department)}"><strong class="cell-ellipsis">${escapeHtml(item.department)}</strong></td><td title="${escapeHtml(item.reason)}"><span class="cell-ellipsis">${escapeHtml(item.reason)}</span></td><td class="num">${formatNumber(item.occurrences)}</td></tr>`).join("") || '<tr><td colspan="3">Nenhum erro nas ultimas 24 horas.</td></tr>'}</tbody>`;
  $("triageOccurrenceTable").innerHTML = `
    <colgroup><col class="occurrence-date-column"><col class="occurrence-department-column"><col class="occurrence-api-column"><col class="occurrence-error-column"><col class="occurrence-reference-column"><col class="occurrence-return-column"></colgroup>
    <thead><tr><th>Data</th><th>Departamento</th><th>API</th><th>Erro</th><th>Loja / NF / produto</th><th>Retorno SAP</th></tr></thead>
    <tbody>${occurrences.map((item) => `<tr>
      <td>${formatDateTime(item.occurrenceAt)}</td>
      <td title="${escapeHtml(item.department)}"><strong class="cell-ellipsis">${escapeHtml(item.department)}</strong></td>
      <td title="${escapeHtml(shortLabel(item.transaction))}"><strong class="cell-ellipsis">${escapeHtml(shortLabel(item.transaction))}</strong></td>
      <td title="${escapeHtml(item.reason)}"><span class="cell-ellipsis">${escapeHtml(item.reason)}</span></td>
      <td title="${escapeHtml(triageReference(item))}"><span class="cell-ellipsis">${escapeHtml(triageReference(item))}</span></td>
      <td title="${escapeHtml(item.sapCode ? `${item.sapCode}${item.sapMessage ? ` - ${item.sapMessage}` : ""}` : item.returnReason || "-")}"><span class="cell-ellipsis">${escapeHtml(item.sapCode ? `${item.sapCode}${item.sapMessage ? ` - ${item.sapMessage}` : ""}` : item.returnReason || "-")}</span></td>
    </tr>`).join("")}</tbody>`;
  $("triageStatus").textContent = occurrences.length
    ? `${formatNumber(occurrences.length)} ocorrencia(s) coletada(s). Use a rolagem da tabela para consultar todas.`
    : "Nenhum erro novo foi coletado para encaminhamento.";
}

function renderTriageRouting(rules) {
  triageRoutingRules = rules || [];
  const errorSelect = $("triageRoutingPattern");
  const selected = errorSelect.value;
  const pendingReasons = triageReasonCatalog.filter((reason) => {
    const normalizedReason = reason.toLocaleLowerCase("pt-BR");
    return !triageRoutingRules.some((rule) => {
      const pattern = String(rule.pattern || "").trim().toLocaleLowerCase("pt-BR");
      return pattern && normalizedReason.includes(pattern);
    });
  });
  errorSelect.innerHTML = `<option value="">${pendingReasons.length ? "Selecione um erro sem area definida" : "Todos os erros possuem area definida"}</option>${pendingReasons.map((reason) => `<option value="${escapeHtml(reason)}">${escapeHtml(reason)} (${formatNumber(triageReasonCounts.get(reason))})</option>`).join("")}`;
  if (pendingReasons.includes(selected)) errorSelect.value = selected;
  renderTriageMemoDepartments();
  $("triageRoutingTable").innerHTML = `
    <colgroup><col class="routing-error-column"><col class="routing-department-column"><col class="routing-actions-column"></colgroup>
    <thead><tr><th>Erro encaminhado</th><th>Departamento</th><th>Acoes</th></tr></thead>
    <tbody>${triageRoutingRules.slice().reverse().map((rule) => `<tr>
      <td title="${escapeHtml(rule.pattern)}"><span class="cell-ellipsis">${escapeHtml(rule.pattern)}</span></td>
      <td title="${escapeHtml(rule.department)}"><strong class="cell-ellipsis">${escapeHtml(rule.department)}</strong></td>
      <td><div class="triage-rule-actions"><button type="button" class="button triage-add-department" data-triage-pattern="${escapeHtml(rule.pattern)}" title="Encaminhar o mesmo erro para outro departamento">+ Departamento</button><button type="button" class="button triage-delete-rule" data-triage-rule-id="${escapeHtml(rule.id)}">Remover</button></div></td>
    </tr>`).join("")}</tbody>`;
  $("triageRoutingStatus").textContent = triageRoutingRules.length
    ? `${formatNumber(pendingReasons.length)} erro(s) ainda sem area definida; ${formatNumber(triageRoutingRules.length)} encaminhamento(s) cadastrados. Use a rolagem para consultar todos.`
    : `${formatNumber(pendingReasons.length)} erro(s) aguardando definicao de area.`;
  $("triageRoutingTable").querySelectorAll("[data-triage-pattern]").forEach((button) => {
    button.addEventListener("click", () => {
      const pattern = button.dataset.triagePattern || "";
      if (![...errorSelect.options].some((option) => option.value === pattern)) errorSelect.add(new Option(pattern, pattern));
      errorSelect.value = pattern;
      $("triageRoutingDepartment").value = "";
      $("triageRoutingDepartment").focus();
      $("triageRoutingStatus").textContent = "Informe o outro departamento e adicione o encaminhamento.";
    });
  });
  $("triageRoutingTable").querySelectorAll("[data-triage-rule-id]").forEach((button) => {
    button.addEventListener("click", () => deleteTriageRouting(button.dataset.triageRuleId));
  });
}

function renderTriageChat(config) {
  triageChatChannels = config.channels || [];
  $("triageChatMeta").textContent = config.enabled
    ? `Envio automatico a cada ${config.intervalMinutes} min`
    : "Envio automatico desativado";
  $("triageChatTable").innerHTML = `
    <thead><tr><th>Departamento</th><th>Tem webhook?</th><th>Ultimo envio</th><th></th></tr></thead>
    <tbody>${triageChatChannels.map((channel) => `<tr><td class="cell-ellipsis" title="${escapeHtml(channel.department)}"><strong>${escapeHtml(channel.department)}</strong></td><td class="${channel.webhookConfigured ? "positive" : "negative"}">${channel.webhookConfigured ? "Configurado" : "Nao configurado"}</td><td>${channel.lastSentAt ? formatDateTime(channel.lastSentAt) : "Ainda nao enviado"}</td><td class="triage-rule-actions"><button class="button triage-edit-chat" type="button" data-triage-chat-id="${escapeHtml(channel.id)}">Editar</button><button class="button triage-delete-chat" type="button" data-triage-chat-id="${escapeHtml(channel.id)}">Remover</button></td></tr>`).join("")}</tbody>`;
  $("triageChatStatus").textContent = triageChatChannels.length ? `${formatNumber(triageChatChannels.length)} departamento(s) cadastrado(s). A tabela possui rolagem; o webhook aparece como configurado, sem exibir a URL com chave e token.` : "Nenhum departamento cadastrado.";
  const catalog = [...new Set([
    ...triageDepartmentCatalog,
    ...triageChatChannels.map((channel) => channel.department),
  ].filter(Boolean))].sort((a, b) => a.localeCompare(b, "pt-BR"));
  $("triageDepartmentOptions").innerHTML = catalog.map((department) => `<option value="${escapeHtml(department)}"></option>`).join("");
  const sendSelect = $("triageSendDepartment");
  const selectedSendDepartment = sendSelect.value;
  const sendDepartments = triageChatChannels.filter((channel) => channel.enabled !== false).map((channel) => channel.department);
  sendSelect.innerHTML = `<option value="">Selecione um departamento com webhook</option>${sendDepartments.map((department) => `<option value="${escapeHtml(department)}">${escapeHtml(department)}</option>`).join("")}`;
  if (sendDepartments.includes(selectedSendDepartment)) sendSelect.value = selectedSendDepartment;
  renderTriageRoutingDepartments();
  $("triageChatTable").querySelectorAll("[data-triage-chat-id].triage-edit-chat").forEach((button) => button.addEventListener("click", () => editTriageChat(button.dataset.triageChatId)));
  $("triageChatTable").querySelectorAll("[data-triage-chat-id].triage-delete-chat").forEach((button) => button.addEventListener("click", () => deleteTriageChat(button.dataset.triageChatId)));
}

function resetTriageChatForm() {
  $("triageChatForm").reset();
  $("triageChatId").value = "";
  $("saveTriageChatDepartment").textContent = "Cadastrar departamento";
  $("cancelTriageChatEdit").hidden = true;
  $("triageChatWebhook").required = true;
}

function editTriageChat(id) {
  const channel = triageChatChannels.find((item) => item.id === id);
  if (!channel) return;
  $("triageChatId").value = channel.id;
  $("triageChatDepartment").value = channel.department;
  $("triageChatWebhook").value = "";
  $("triageChatWebhook").required = false;
  $("triageChatWebhook").placeholder = "Deixe vazio para manter o webhook atual";
  $("saveTriageChatDepartment").textContent = "Salvar alteracao";
  $("cancelTriageChatEdit").hidden = false;
  $("triageChatDepartment").focus();
}

async function saveTriageChat(event) {
  event.preventDefault();
  const department = $("triageChatDepartment").value.trim();
  const webhook = $("triageChatWebhook").value.trim();
  const id = $("triageChatId").value;
  if (!department || (!webhook && !id)) return;
  try {
    const result = await api("/api/business-monitor/sap-api/google-chat", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "save", id, department, webhook }) });
    resetTriageChatForm();
    renderTriageChat(result);
  } catch (error) { $("triageChatStatus").textContent = error.message; }
}

async function deleteTriageChat(id) {
  try {
    const result = await api("/api/business-monitor/sap-api/google-chat", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "delete", id }) });
    renderTriageChat(result);
  } catch (error) { $("triageChatStatus").textContent = error.message; }
}

async function saveTriageRouting(event) {
  event.preventDefault();
  const pattern = $("triageRoutingPattern").value.trim();
  const department = $("triageRoutingDepartment").value.trim();
  if (!pattern || !department) return;
  $("triageRoutingStatus").textContent = "Salvando regra...";
  try {
    const result = await api("/api/business-monitor/sap-api/routing", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "save", pattern, department }),
    });
    $("triageRoutingForm").reset();
    renderTriageRouting(result.rules || []);
    await loadMonitor();
  } catch (error) {
    $("triageRoutingStatus").textContent = error.message;
  }
}

async function deleteTriageRouting(id) {
  if (!id) return;
  try {
    const result = await api("/api/business-monitor/sap-api/routing", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: "delete", id }),
    });
    renderTriageRouting(result.rules || []);
    await loadMonitor();
  } catch (error) {
    $("triageRoutingStatus").textContent = error.message;
  }
}

function transactionSummary(tx) {
  const change = tx?.changeFromPrevious || {};
  const details = [
    ...(tx?.errorDetails || []),
    ...(tx?.otherDetails || []).map((item) => ({ ...item, status: item.status || "other" })),
  ];
  const errorReasons = displayProblemReasons(tx)
    .filter((item) => Number(item.count || 0) > 0)
    .map((item) => `- ${item.reason}: ${formatNumber(item.count)}`);
  const lines = [
    `Transacao: ${shortLabel(tx?.label)} (${tx?.id || "-"})`,
    `Arquivo: ${tx?.file || "-"}`,
    `Periodo: ${tx?.firstEventAt || "-"} ate ${tx?.lastEventAt || "-"}`,
    `Erros reais no periodo: ${formatNumber(tx?.errors)} | Retornos sem classificacao: ${formatNumber(tx?.other)} | Eventos monitorados: ${formatNumber(tx?.monitoredEvents)}`,
    `Erro %: ${formatDecimal(tx?.errorRate)}% | Media resp.: ${formatDecimal(tx?.avgResponseGapSeconds)}s | P95: ${formatDecimal(tx?.p95ResponseGapSeconds)}s | Delta erros: ${Number(change.errors || 0)}`,
  ];
  const detailLine = (item, index) => {
    const payload = item.payload ? `\n  json envio: ${JSON.stringify(item.payload)}` : "";
    const responsePayload = item.responsePayload ? `\n  retorno SAP: ${JSON.stringify(item.responsePayload)}` : "";
    const reference = [
      item.note ? `NF ${item.note}` : "",
      item.accessKey ? `chave ${item.accessKey}` : "",
      item.store ? `loja ${item.store}` : "",
      item.center ? `centro ${item.center}` : "",
      item.material ? `material ${item.material}` : "",
      item.sapCode ? `codigo SAP ${item.sapCode}` : "",
      item.nfeDocumentStatus ? `status NFe SAP ${item.nfeDocumentStatus}` : "",
      item.requestEndpoint ? `endpoint ${item.requestEndpoint}` : "",
      item.storeErrorMaterials?.length ? `materiais erro loja ${item.storeErrorMaterials.join(", ")}` : "",
      item.attempt ? `tentativa ${item.attempt}/${item.maxAttempts || 5}` : "",
    ].filter(Boolean).join(" | ");
    const sapMessage = item.sapMessage ? `\n  mensagem SAP: ${item.sapMessage}` : "";
    const returnReason = item.returnReason ? `\n  motivo retornado: ${item.returnReason}` : "";
    const statusDescription = item.nfeDocumentStatusDescription ? `\n  interpretacao status NFe: ${item.nfeDocumentStatusDescription}` : "";
    const requestUrl = item.requestUrl ? `\n  chamada SAP: ${item.requestUrl}` : "";
    const missingSapReason = item.nfeDocumentStatus && !item.returnReason && !item.sapMessage
      ? "\n  retorno detalhado do SAP: nao registrado neste log do Pleno."
      : "";
    return `${index + 1}. ${item.at || "-"} | ${item.status || "-"} | ${item.reason || "-"}${reference ? ` | ${reference}` : ""}\n  referencia: ${reference || "-"}${statusDescription}${returnReason}${sapMessage}${missingSapReason}${requestUrl}\n  ${item.raw || ""}${payload}${responsePayload}`;
  };
  const references = details.filter(hasDetailReference).map(detailLine);
  const errorDetails = details.map(detailLine);
  const samples = (tx?.sampleErrors || []).map((item, index) => `${index + 1}. ${item}`);
  if (errorReasons.length) lines.push("", "Motivos de erro:", ...errorReasons);
  if (references.length) lines.push("", "Referencias dos erros (NF/chave/loja/material):", ...references);
  else if (details.length) lines.push("", "Referencias dos erros (NF/chave/loja/material):", "- Os erros encontrados nao trouxeram NF/chave/loja/material nas linhas analisadas.");
  if (errorDetails.length) lines.push("", "Detalhes de erros:", ...errorDetails);
  else if (samples.length) lines.push("", "Amostras de erros:", ...samples);
  else lines.push("", "Detalhes de erros:", "- Nenhum erro ou retorno SAP sem classificacao encontrado nesse periodo.");
  return lines.join("\n");
}

function hasDetailReference(item) {
  return Boolean(item?.note || item?.accessKey || item?.store || item?.center || item?.material || item?.storeErrorMaterials?.length);
}

function errorOnlyTransaction(tx) {
  if (!tx) return tx;
  const errorReasons = displayProblemReasons(tx);
  const details = [
    ...(tx.errorDetails || []),
    ...(tx.otherDetails || []),
  ];
  return {
    id: tx.id,
    label: tx.label,
    file: tx.file,
    firstEventAt: tx.firstEventAt,
    lastEventAt: tx.lastEventAt,
    monitoredEvents: tx.monitoredEvents,
    errors: tx.errors,
    other: tx.other,
    errorRate: tx.errorRate,
    avgResponseGapSeconds: tx.avgResponseGapSeconds,
    p95ResponseGapSeconds: tx.p95ResponseGapSeconds,
    topReasons: errorReasons,
    errorReasons: tx.errorReasons || [],
    unclassifiedReasons: tx.unclassifiedReasons || [],
    topNotes: tx.topNotes || [],
    referenceDetails: details.filter(hasDetailReference),
    sampleErrors: tx.sampleErrors || [],
    errorDetails: tx.errorDetails || [],
    otherDetails: tx.otherDetails || [],
    changeFromPrevious: tx.changeFromPrevious || {},
  };
}

function errorOnlyPayload(payload) {
  if (!payload?.snapshot) return payload;
  const snapshot = payload.snapshot || {};
  return {
    collector: payload.collector,
    updatedAt: payload.updatedAt,
    transactionId: payload.transactionId,
    windowMinutes: payload.windowMinutes,
    start: payload.start,
    end: payload.end,
    detailFile: payload.detailFile,
    snapshot: {
      collectedAt: snapshot.collectedAt,
      windowStart: snapshot.windowStart,
      windowEnd: snapshot.windowEnd,
      windowMinutes: snapshot.windowMinutes,
      host: snapshot.host,
      transactions: (snapshot.transactions || []).map(errorOnlyTransaction),
    },
  };
}

function transactionModalText(tx) {
  return `${transactionSummary(tx)}\n\nJSON da transacao:\n${JSON.stringify(errorOnlyTransaction(tx) || {}, null, 2)}`;
}

function detailPayloadText(payload) {
  const snapshot = payload?.snapshot || {};
  const tx = (snapshot.transactions || [])[0] || null;
  if (!tx) {
    return [
      `Consulta salva em: ${payload?.detailFile || "-"}`,
      `Periodo: ultimos ${payload?.windowMinutes || "-"} minutos`,
      "",
      "Nenhum evento encontrado para essa transacao nesse periodo.",
      "",
      `JSON da consulta:\n${JSON.stringify(errorOnlyPayload(payload) || {}, null, 2)}`,
    ].join("\n");
  }
  return [
    `Consulta salva em: ${payload.detailFile || "-"}`,
    `Periodo: ${formatDateTime(snapshot.windowStart)} ate ${formatDateTime(snapshot.windowEnd)} (${payload.windowMinutes} min)`,
    "",
    transactionSummary(tx),
    "",
    `JSON da consulta:\n${JSON.stringify(errorOnlyPayload(payload) || {}, null, 2)}`,
  ].join("\n");
}

function manualErrorPayloadText(payload) {
  const results = payload?.results || [];
  const period = payload?.start && payload?.end
    ? formatPeriod(payload.start, payload.end)
    : "-";
  const lines = [
    `Consulta salva em: ${payload?.detailFile || "-"}`,
    `Loja: ${payload?.store || "-"}`,
    `Motivo pesquisado: ${payload?.reason || "-"}`,
    `Periodo pesquisado: ${period} (${payload?.windowMinutes || "-"} min)`,
    `Ocorrencias encontradas: ${formatNumber(payload?.matched)}`,
  ];
  if (!results.length) {
    lines.push("", "Nenhum erro encontrado com esses filtros. Tente parte menor do texto do motivo ou aumente a faixa de busca.");
    return lines.join("\n");
  }
  for (const [index, item] of results.entries()) {
    const reference = [
      item.note ? `NF ${item.note}` : "",
      item.accessKey ? `chave ${item.accessKey}` : "",
      item.store ? `loja ${item.store}` : "",
      item.center ? `centro ${item.center}` : "",
      item.material ? `material ${item.material}` : "",
    ].filter(Boolean).join(" | ");
    lines.push(
      "",
      `${index + 1}. ${item.at || "-"} | ${shortLabel(item.transaction)} | ${item.reason || "Retorno SAP sem classificacao"}`,
      `Arquivo: ${item.file || "-"}`,
      `Referencia: ${reference || "-"}`,
      "",
      "JSON enviado ao SAP:",
      item.payload ? JSON.stringify(item.payload, null, 2) : "Nao localizado neste bloco do log.",
      "",
      "Retorno do SAP:",
      item.responsePayload ? JSON.stringify(item.responsePayload, null, 2) : "Nao estruturado; veja a linha original abaixo.",
      "",
      "Linha original do log:",
      item.raw || "-",
    );
  }
  return lines.join("\n");
}

async function copyText(text, successMessage) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
  } else {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand("copy");
    textarea.remove();
  }
  $("copyTransactionStatus").textContent = successMessage;
  setTimeout(() => {
    if ($("copyTransactionStatus")) $("copyTransactionStatus").textContent = "";
  }, 2400);
}

function closeTransactionModal() {
  selectedTransaction = null;
  selectedDetailPayload = null;
  transactionDetailsLoading = false;
  $("transactionModal").hidden = true;
}

function closeManualErrorModal() {
  manualErrorLoading = false;
  $("manualErrorModal").hidden = true;
}

function openManualErrorModal() {
  manualErrorPayload = null;
  manualErrorLoading = false;
  $("manualErrorStatus").textContent = "Sem horario, procura o erro mais recente nas ultimas 24 horas.";
  $("manualErrorModalBody").textContent = "Informe a loja e o motivo para consultar o log.";
  $("copyManualErrorSummary").disabled = true;
  $("copyManualErrorJson").disabled = true;
  $("runManualErrorSearch").disabled = false;
  $("manualErrorModal").hidden = false;
  $("manualErrorStore").focus();
}

async function runManualErrorSearch() {
  if (manualErrorLoading) return;
  const store = $("manualErrorStore").value.trim();
  const reason = $("manualErrorReason").value.trim();
  const approximateAt = $("manualErrorAt").value.trim();
  const minutes = $("manualErrorMinutes").value || "120";
  if (!store || !reason) {
    $("manualErrorStatus").textContent = "Informe a loja e o motivo.";
    return;
  }
  manualErrorLoading = true;
  $("runManualErrorSearch").disabled = true;
  $("manualErrorStatus").textContent = "Consultando log do Pleno...";
  $("manualErrorModalBody").textContent = "Buscando ocorrencias e o contexto do envio ao SAP...";
  try {
    const params = new URLSearchParams({ store, reason, minutes });
    if (approximateAt) params.set("approximateAt", approximateAt);
    const payload = await api(`/api/business-monitor/sap-api/manual-search?${params.toString()}`);
    manualErrorPayload = payload;
    $("manualErrorModalBody").textContent = manualErrorPayloadText(payload);
    $("manualErrorStatus").textContent = `${formatNumber(payload.matched)} ocorrencia(s) encontrada(s). Consulta salva em ${payload.detailFile || "arquivo local"}.`;
    $("copyManualErrorSummary").disabled = false;
    $("copyManualErrorJson").disabled = false;
  } catch (error) {
    $("manualErrorModalBody").textContent = "Nao foi possivel consultar o log.";
    $("manualErrorStatus").textContent = error.message;
  } finally {
    manualErrorLoading = false;
    $("runManualErrorSearch").disabled = false;
  }
}

function openTransactionModal(tx, options = {}) {
  selectedTransaction = tx;
  selectedDetailPayload = null;
  transactionDetailsLoading = false;
  $("transactionModalTitle").textContent = shortLabel(tx.label);
  $("transactionModalSubtitle").textContent = tx.id || "";
  $("transactionModalBody").textContent = transactionModalText(tx);
  $("copyTransactionStatus").textContent = "";
  $("transactionDetailStatus").textContent = options.status || "Pronto para consultar os ultimos 10 minutos.";
  $("transactionPeriod").value = String(options.minutes || "10");
  $("transactionModal").hidden = false;
}

async function loadTransactionDetails(options = {}) {
  if (!selectedTransaction?.id || transactionDetailsLoading) return;
  transactionDetailsLoading = true;
  const minutes = options.start && options.end
    ? String(minutesBetween(options.start, options.end))
    : ($("transactionPeriod").value || "10");
  $("transactionDetailStatus").textContent = "Consultando logs...";
  $("loadTransactionDetails").disabled = true;
  try {
    const params = new URLSearchParams({
      transactionId: selectedTransaction.id,
      minutes,
    });
    if (options.start && options.end) {
      params.set("start", options.start);
      params.set("end", options.end);
    }
    const payload = await api(`/api/business-monitor/sap-api/details?${params.toString()}`);
    selectedDetailPayload = payload;
    $("transactionModalBody").textContent = detailPayloadText(payload);
    $("transactionDetailStatus").textContent = `Consulta salva: ${formatDateTime(payload.updatedAt)}`;
  } catch (error) {
    $("transactionDetailStatus").textContent = error.message;
  } finally {
    $("loadTransactionDetails").disabled = false;
    transactionDetailsLoading = false;
  }
}

function renderCheckin(data) {
  const totals = data.totals || {};
  const originStore = data.originStore || 704;
  $("checkinUpdatedAt").textContent = data.statusFileExists
    ? `Coleta ${formatDateTime(data.updatedAt)}`
    : "Sem coleta";
  $("checkinKpis").innerHTML = [
    kpi("Total notas", formatNumber(totals.total), `CD ${originStore} - ${data.startDate || "-"} ate ${data.endDate || "-"}`),
    kpi("Com check-in", formatNumber(totals.comCheckin), `${formatDecimal(totals.doneRate)}%`, totals.comCheckin ? "positive" : ""),
    kpi("Faltam check-in", formatNumber(totals.semCheckin), `${formatDecimal(totals.pendingRate)}%`, totals.semCheckin ? "negative" : "positive"),
    kpi("Lojas pendentes", formatNumber((data.pendingStores || []).length), "com nota sem check-in"),
  ].join("");
  const recentHistory = lastHours(data.last12HoursHistory || data.history || [], 12);
  const chartHistory = recentHistory.length
    ? recentHistory
    : data.pendingStoreTotals
      ? [{ collectedAt: data.updatedAt, ...data.pendingStoreTotals }]
      : [];
  $("checkinTrendChart").innerHTML = checkinTrendChart(chartHistory);

  const pendingStores = data.pendingStores || [];
  const storeTotals = pendingStores.reduce((acc, row) => {
    acc.total += Number(row.total || 0);
    acc.pending += Number(row.sem_checkin || 0);
    acc.done += Number(row.com_checkin || 0);
    return acc;
  }, { total: 0, pending: 0, done: 0 });
  $("checkinStoreTable").innerHTML = `
    <thead><tr><th>Loja</th><th>Total</th><th>Faltam</th><th>Feitas</th></tr></thead>
    <tbody>
      <tr>
        <td><strong>Total</strong><small>${formatNumber(pendingStores.length)} lojas</small></td>
        <td>${formatNumber(storeTotals.total)}</td>
        <td class="${storeTotals.pending ? "negative" : "positive"}">${formatNumber(storeTotals.pending)}</td>
        <td class="positive">${formatNumber(storeTotals.done)}</td>
      </tr>
      ${pendingStores.map((row) => `
      <tr>
        <td><strong>${row.loja}</strong><small>${row.nome_loja || ""}</small></td>
        <td>${formatNumber(row.total)}</td>
        <td class="${Number(row.sem_checkin || 0) ? "negative" : "positive"}">${formatNumber(row.sem_checkin)}</td>
        <td class="positive">${formatNumber(row.com_checkin)}</td>
      </tr>
    `).join("")}</tbody>
  `;

  const pendingNotes = data.pendingNotes || [];
  $("checkinNoteTable").innerHTML = `
    <thead><tr><th>Loja</th><th>NF</th><th>Serie</th><th>Entrada</th><th>Itens</th></tr></thead>
    <tbody>${pendingNotes.map((row) => `
      <tr>
        <td>${row.loja}</td>
        <td><strong>${row.nota}</strong></td>
        <td>${row.serie || ""}</td>
        <td>${row.entrada_saida || row.emissao || ""}</td>
        <td>${formatNumber(row.itens)}</td>
      </tr>
    `).join("")}</tbody>
  `;

 $("checkinStatus").textContent = data.statusFileExists
    ? `Fonte ${data.source}. Janela consolidada de ${data.startDate} ate ${data.endDate}: inicia na nota pendente mais antiga, sem voltar antes de ${data.configuredStartDate || "2026-08-01"}. Mostrando ${formatNumber(pendingNotes.length)} notas pendentes de saida nao canceladas vindas do CD ${originStore}. Considera apenas destinatarios de lojas proprias entre 1 e 2999, exclui o CD ${originStore}; franquias ficam fora do controle SAP. Grafico mostra as ultimas 12 horas desta mesma janela: azul Total, vermelho Faltam, verde Feitas.`
    : `Sem arquivo ${data.statusFile}.`;
}

function renderTable(transactions) {
  const rows = [...(transactions || [])].sort((a, b) => (b.errors || 0) - (a.errors || 0));
  $("sapTable").innerHTML = `
    <thead>
      <tr>
        <th>Transacao</th>
        <th>Eventos</th>
        <th>Sucessos</th>
        <th>Erros</th>
        <th>Ign.</th>
        <th>Outros</th>
        <th>Erro %</th>
        <th>Media resp.</th>
        <th>P95</th>
        <th>Delta erros</th>
        <th>Principal motivo</th>
      </tr>
    </thead>
    <tbody>${rows.map((tx) => {
      const change = tx.changeFromPrevious || {};
      const reason = displayProblemReasons(tx).find((item) => Number(item.count || 0) > 0) || (tx.topReasons || []).find((item) => item.reason === "Sucesso");
      const delta = Number(change.errors || 0);
      return `<tr class="clickable-row" data-transaction-id="${escapeHtml(tx.id || "")}" title="Clique para ver detalhes e copiar">
        <td><strong>${shortLabel(tx.label)}</strong><small>${tx.id || ""}</small></td>
        <td>${formatNumber(tx.events)}</td>
        <td class="positive">${formatNumber(tx.success)}</td>
        <td class="${tx.errors ? "negative" : "positive"}">${formatNumber(tx.errors)}</td>
        <td>${formatNumber(tx.ignored)}</td>
        <td>${formatNumber(tx.other)}</td>
        <td>${formatDecimal(tx.errorRate)}%</td>
        <td>${formatDecimal(tx.avgResponseGapSeconds)}s</td>
        <td>${formatDecimal(tx.p95ResponseGapSeconds)}s</td>
        <td class="${delta > 0 ? "negative" : delta < 0 ? "positive" : ""}">${delta > 0 ? "+" : ""}${formatNumber(delta)}</td>
        <td>${reason ? `${reason.reason} (${formatNumber(reason.count)})` : "-"}</td>
      </tr>`;
    }).join("")}</tbody>
  `;
  $("sapTable").querySelectorAll("[data-transaction-id]").forEach((row) => {
    row.addEventListener("click", () => {
      const tx = rows.find((item) => String(item.id || "") === row.dataset.transactionId);
      if (tx) openTransactionModal(tx);
    });
  });
}

function render(data) {
  currentMonitorData = data;
  const totals = data.totals || {};
  const latest = data.latest || {};
  const transactions = data.transactions || [];
  const history = data.history || [];
  const monitorHistory = lastHours(history, 24);
  const worst = data.worstTransactions || transactions;

  $("pageSubtitle").textContent = `Janela movel de ${data.windowMinutes || 10} min · agora ${formatDateTime(data.now)}`;
  $("sapUpdatedAt").textContent = data.statusFileExists
    ? `Coleta ${formatDateTime(data.updatedAt)}`
    : "Sem arquivo de coleta";
  $("sapStatus").textContent = data.statusFileExists
    ? `Lendo ${data.statusFile}. Os tempos sao intervalos entre respostas registradas, nao duracao HTTP real.`
    : `Sem coleta. Aguarde o coletor gerar ${data.statusFile}.`;

  $("sapKpis").innerHTML = [
    kpi("Eventos", formatNumber(totals.events), "ultima janela"),
    kpi("Sucessos", formatNumber(totals.success), `${formatDecimal(totals.successRate)}%`, totals.success ? "positive" : ""),
    kpi("Erros", formatNumber(totals.errors), `${formatDecimal(totals.errorRate)}%`, totals.errors ? "negative" : "positive"),
    kpi("Ignorados", formatNumber(totals.ignored), `${formatDecimal(totals.ignoredRate)}% padrao`, totals.ignored ? "" : "positive"),
    kpi("Outros", formatNumber(totals.other), "sem classificacao", totals.other ? "" : "positive"),
    kpi("Transacoes", formatNumber(transactions.length), latest.host || ""),
    kpi("Janela", `${data.windowMinutes || 10} min`, `${formatTime(latest.windowStart)}-${formatTime(latest.windowEnd)} · coleta ${formatTime(latest.collectedAt)}`),
  ].join("");

  $("errorChartMeta").textContent = `ultimas 24 h · ${monitorHistory.length} ponto(s)`;
  $("successChartMeta").textContent = `ultimas 24 h · ${monitorHistory.length} ponto(s)`;
  $("distributionMeta").textContent = "ultima janela";
  $("errorChart").innerHTML = lineChart(seriesFor(monitorHistory, "errors"), { color: "#c93535" });
  $("successChart").innerHTML = lineChart(seriesFor(monitorHistory, "success"), { color: "#087443" });
  $("distributionChart").innerHTML = stackedStatusChart(worst);
  renderAggregateHistory(data);
  const busiest = [...transactions].sort((a, b) => (b.events || 0) - (a.events || 0))[0];
  $("responseChart").innerHTML = busiest
    ? lineChart(seriesFor(monitorHistory, "avgResponseGapSeconds", busiest.id), { suffix: "s", color: "#9a6700" })
    : `<div class="empty-chart">Sem transacao ativa.</div>`;

  renderTable(transactions);
  renderReasons(transactions);
  renderTriage(data);
}

function updateAutoRefreshStatus(state = "ok", message = "") {
  const seconds = Math.max(0, Math.ceil((nextRefreshAt - Date.now()) / 1000));
  const base = state === "loading"
    ? "Atualizando dados..."
    : `Atualizacao automatica em ${seconds}s`;
  $("autoRefreshStatus").textContent = `${base} · ultima tentativa ${formatClock()}${message ? ` · ${message}` : ""}`;
  $("autoRefreshStatus").className = `auto-refresh-status ${state === "error" ? "negative" : ""}`;
}

function startAutoRefreshTicker() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => updateAutoRefreshStatus(), 1000);
}

async function loadMonitor({ manual = false } = {}) {
  updateAutoRefreshStatus("loading", manual ? "manual" : "automatico");
  const [sapData, checkinData, routingData, chatData] = await Promise.all([
    api("/api/business-monitor/sap-api"),
    api("/api/business-monitor/checkin-notas"),
    api("/api/business-monitor/sap-api/routing"),
    api("/api/business-monitor/sap-api/google-chat"),
  ]);
  render(sapData);
  renderTriageRouting(routingData.rules || []);
  render24HourErrorTreatment(sapData);
  renderTriageChat(chatData);
  renderCheckin(checkinData);
  nextRefreshAt = Date.now() + refreshIntervalMs;
  updateAutoRefreshStatus("ok");
}

$("refreshButton").addEventListener("click", () => {
  loadMonitor({ manual: true }).catch((error) => {
    updateAutoRefreshStatus("error", error.message);
    $("sapStatus").textContent = error.message;
  });
});
$("triageRoutingForm").addEventListener("submit", saveTriageRouting);
$("triageChatForm").addEventListener("submit", saveTriageChat);
$("cancelTriageChatEdit").addEventListener("click", resetTriageChatForm);
$("generateTriageMemo").addEventListener("click", generateTriageMemo);
$("copyTriageMemo").addEventListener("click", () => copyText($("triageMemoBody").textContent, "Memo copiado.").catch(() => { $("triageMemoStatus").textContent = "Nao foi possivel copiar o memo."; }));
$("sendTriageMemo").addEventListener("click", async () => {
  const department = $("triageMemoDepartment").value;
  const text = $("triageMemoBody").textContent;
  if (!department || !text || text.startsWith("Selecione")) return;
  $("sendTriageMemo").disabled = true;
  try {
    const result = await api("/api/business-monitor/sap-api/google-chat/send", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ department, text }) });
    $("triageMemoStatus").textContent = `Memo enviado ao Google Chat de ${result.department} (${result.sent} destino(s)).`;
    await loadMonitor();
  } catch (error) {
    $("triageMemoStatus").textContent = error.message;
  } finally {
    $("sendTriageMemo").disabled = false;
  }
});
$("sendAllTriageErrors").addEventListener("click", async () => {
  const department = $("triageSendDepartment").value;
  if (!department) {
    $("triageChatStatus").textContent = "Selecione um departamento com webhook.";
    return;
  }
  if (!window.confirm(`Enviar o resumo de todos os erros coletados para ${department}?`)) return;
  const memoDepartment = $("triageMemoDepartment");
  const previousDepartment = memoDepartment.value;
  if (![...memoDepartment.options].some((option) => option.value === department)) memoDepartment.add(new Option(department, department));
  memoDepartment.value = department;
  try {
    const memo = buildTriageMemo({ all: true });
    $("sendAllTriageErrors").disabled = true;
    const result = await api("/api/business-monitor/sap-api/google-chat/send", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ department, text: memo.text }) });
    $("triageChatStatus").textContent = `Resumo de ${formatNumber(memo.count)} ocorrencia(s) enviado para ${result.department}.`;
    await loadMonitor();
  } catch (error) {
    $("triageChatStatus").textContent = error.message;
  } finally {
    $("sendAllTriageErrors").disabled = false;
    if (previousDepartment) memoDepartment.value = previousDepartment;
  }
});

const initialMemoEnd = new Date();
$("triageMemoEnd").value = toLocalInputValue(initialMemoEnd);
$("triageMemoStart").value = toLocalInputValue(new Date(initialMemoEnd.getTime() - 60 * 60 * 1000));

document.querySelectorAll("[data-sap-tab-button]").forEach((button) => {
  button.addEventListener("click", () => setActiveSapTab(button.dataset.sapTabButton));
});
$("openManualErrorSearch").addEventListener("click", openManualErrorModal);
$("closeManualErrorModal").addEventListener("click", closeManualErrorModal);
$("manualErrorModal").addEventListener("click", (event) => {
  if (event.target === $("manualErrorModal")) closeManualErrorModal();
});
$("manualErrorSearchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  runManualErrorSearch();
});
$("copyManualErrorSummary").addEventListener("click", () => {
  if (!manualErrorPayload) return;
  copyText(manualErrorPayloadText(manualErrorPayload), "Resumo copiado.").catch(() => {
    $("manualErrorStatus").textContent = "Nao foi possivel copiar.";
  });
});
$("copyManualErrorJson").addEventListener("click", () => {
  if (!manualErrorPayload) return;
  copyText(JSON.stringify(manualErrorPayload, null, 2), "JSON copiado.").catch(() => {
    $("manualErrorStatus").textContent = "Nao foi possivel copiar.";
  });
});
$("closeTransactionModal").addEventListener("click", closeTransactionModal);
$("transactionModal").addEventListener("click", (event) => {
  if (event.target === $("transactionModal")) closeTransactionModal();
});
$("copyTransactionSummary").addEventListener("click", () => {
  if (!selectedTransaction) return;
  const text = selectedDetailPayload ? detailPayloadText(selectedDetailPayload) : transactionSummary(selectedTransaction);
  copyText(text, "Resumo copiado.").catch(() => {
    $("copyTransactionStatus").textContent = "Nao foi possivel copiar.";
  });
});
$("copyTransactionJson").addEventListener("click", () => {
  if (!selectedTransaction) return;
  const filtered = selectedDetailPayload ? errorOnlyPayload(selectedDetailPayload) : errorOnlyTransaction(selectedTransaction);
  copyText(JSON.stringify(filtered, null, 2), "JSON copiado.").catch(() => {
    $("copyTransactionStatus").textContent = "Nao foi possivel copiar.";
  });
});
$("loadTransactionDetails").addEventListener("click", () => {
  loadTransactionDetails();
});
$("historyGrain").addEventListener("change", () => {
  if (currentMonitorData) renderAggregateHistory(currentMonitorData);
});
$("historyGrouping").addEventListener("change", () => {
  if (currentMonitorData) renderAggregateHistory(currentMonitorData);
});
$("applyHistoryRange").addEventListener("click", () => {
  if (currentMonitorData) renderAggregateHistory(currentMonitorData);
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("transactionModal").hidden) closeTransactionModal();
  if (!$("manualErrorModal").hidden) closeManualErrorModal();
});

setActiveSapTab(activeSapTab);

loadMonitor().catch((error) => {
  $("pageSubtitle").textContent = error.message;
  $("sapStatus").textContent = error.message;
  updateAutoRefreshStatus("error", error.message);
});

startAutoRefreshTicker();

setInterval(() => {
  loadMonitor().catch((error) => {
    $("sapStatus").textContent = error.message;
    nextRefreshAt = Date.now() + refreshIntervalMs;
    updateAutoRefreshStatus("error", error.message);
  });
}, refreshIntervalMs);

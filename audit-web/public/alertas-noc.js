let alertPolicy = null;
let alertAcknowledgements = {};

function $(id) {
  return document.getElementById(id);
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Erro na requisição.");
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDateTime(value) {
  if (!value) return "Ainda não salva";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return `Atualizada ${date.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}`;
}

function numberField(label, key, value, description = "") {
  return `
    <label class="alert-number-field">
      <span>${escapeHtml(label)}</span>
      <input type="number" min="0" step="1" data-policy-key="${escapeHtml(key)}" value="${Number(value || 0)}">
      ${description ? `<small>${escapeHtml(description)}</small>` : ""}
    </label>
  `;
}

function timeField(label, key, value, description = "") {
  return `
    <label class="alert-number-field">
      <span>${escapeHtml(label)}</span>
      <input type="time" data-policy-key="${escapeHtml(key)}" value="${escapeHtml(value || "")}">
      ${description ? `<small>${escapeHtml(description)}</small>` : ""}
    </label>
  `;
}

function checkbox(label, attributes, checked, description = "") {
  return `
    <label class="alert-toggle">
      <input type="checkbox" ${attributes} ${checked ? "checked" : ""}>
      <span><b>${escapeHtml(label)}</b>${description ? `<small>${escapeHtml(description)}</small>` : ""}</span>
    </label>
  `;
}

const weekdays = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"];

function weekdayChoices(selectedDays, attributeName, compact = false) {
  const selected = new Set(selectedDays || []);
  return `<div class="alert-weekday-choices ${compact ? "is-compact" : ""}">${weekdays.map((label, day) => `
    <label><input type="checkbox" ${attributeName} value="${day}" ${selected.has(day) ? "checked" : ""}><span>${label}</span></label>
  `).join("")}</div>`;
}

function scopeChoices(destination, scopes) {
  const selected = new Set(destination.scopes || ["all"]);
  const allSelected = selected.has("all");
  return `
    <div class="alert-scope-choices">
      ${checkbox("Todos os processos", `data-destination-all="${escapeHtml(destination.id)}"`, allSelected)}
      ${scopes.map((scope) => checkbox(scope.label, `data-destination-scope="${escapeHtml(destination.id)}" value="${escapeHtml(scope.id)}"`, !allSelected && selected.has(scope.id))).join("")}
    </div>
  `;
}

function renderDefaults(defaults) {
  $("alertPolicyDefaults").innerHTML = [
    `<div class="alert-weekdays-field"><span>Dias monitorados</span>${weekdayChoices(defaults.weekdays, "data-policy-weekday", true)}</div>`,
    timeField("Início", "monitorStart", defaults.monitorStart, "início da janela de monitoramento"),
    timeField("Fim", "monitorEnd", defaults.monitorEnd, "fim da janela de monitoramento"),
    numberField("Consulta OK", "okCheckIntervalSeconds", defaults.okCheckIntervalSeconds, "segundos entre consultas saudáveis"),
    numberField("Consulta falha", "failureCheckIntervalSeconds", defaults.failureCheckIntervalSeconds, "segundos entre novas consultas em falha"),
    numberField("Aguardar falha", "firstErrorAfterSeconds", defaults.firstErrorAfterSeconds, "segundos antes do primeiro alerta"),
    checkbox("Enviar falha", "data-policy-bool=\"sendFailure\"", defaults.sendFailure, "envia alerta quando encontrar erro"),
    numberField("Repetir falha", "repeatEverySeconds", defaults.repeatEverySeconds, "segundos entre alertas de falha"),
    numberField("Parar falha", "stopAfterSeconds", defaults.stopAfterSeconds, "0 mantém os alertas sem limite"),
    checkbox("Enviar acerto", "data-policy-bool=\"sendRecovery\"", defaults.sendRecovery, "avisa quando a falha for normalizada"),
    numberField("Intervalo acerto", "recoveryRepeatEverySeconds", defaults.recoveryRepeatEverySeconds, "segundos; 0 usa envio único"),
    checkbox("Enviar resumo", "data-policy-bool=\"sendProgressSummary\"", defaults.sendProgressSummary, "envia andamento para processos que suportam resumo"),
    numberField("Intervalo resumo", "progressSummaryEverySeconds", defaults.progressSummaryEverySeconds, "segundos entre resumos"),
    checkbox("Acerto único", "data-policy-bool=\"recoverySendOnce\"", defaults.recoverySendOnce, "envia somente uma vez ao voltar ao normal"),
    checkbox("Acerto no limite", "data-policy-bool=\"recoveryOnlyWithinStopWindow\"", defaults.recoveryOnlyWithinStopWindow, "não avisa após a janela de falha"),
  ].join("");
}

function processFieldSet(rule, defaults) {
  const value = (key) => rule[key] ?? defaults[key];
  return `
    <div class="alert-process-group">
      <h4>Monitoramento</h4>
      <div class="alert-process-fields">
        <div class="alert-weekdays-field"><span>Dias</span>${weekdayChoices(value("weekdays"), "data-scope-weekday", true)}</div>
        ${timeField("Início", "monitorStart", value("monitorStart"))}
        ${timeField("Fim", "monitorEnd", value("monitorEnd"))}
        ${numberField("Consulta OK", "okCheckIntervalSeconds", value("okCheckIntervalSeconds"))}
        ${numberField("Consulta falha", "failureCheckIntervalSeconds", value("failureCheckIntervalSeconds"))}
      </div>
    </div>
    <div class="alert-process-group">
      <h4>Mensagens</h4>
      <div class="alert-process-fields">
        ${numberField("Aguardar falha", "firstErrorAfterSeconds", value("firstErrorAfterSeconds"))}
        ${checkbox("Enviar falha", "data-scope-bool=\"sendFailure\"", value("sendFailure"))}
        ${numberField("Repetir falha", "repeatEverySeconds", value("repeatEverySeconds"))}
        ${numberField("Parar falha", "stopAfterSeconds", value("stopAfterSeconds"))}
        ${checkbox("Enviar acerto", "data-scope-bool=\"sendRecovery\"", value("sendRecovery"))}
        ${numberField("Intervalo acerto", "recoveryRepeatEverySeconds", value("recoveryRepeatEverySeconds"))}
        ${checkbox("Acerto único", "data-scope-bool=\"recoverySendOnce\"", value("recoverySendOnce"))}
        ${checkbox("Enviar resumo", "data-scope-bool=\"sendProgressSummary\"", value("sendProgressSummary"))}
        ${numberField("Intervalo resumo", "progressSummaryEverySeconds", value("progressSummaryEverySeconds"))}
        ${checkbox("Acerto no limite", "data-scope-bool=\"recoveryOnlyWithinStopWindow\"", value("recoveryOnlyWithinStopWindow"))}
      </div>
    </div>
  `;
}

function acknowledgementControl(scope, acknowledgement) {
  const mutedUntil = acknowledgement?.mutedUntil ? new Date(acknowledgement.mutedUntil) : null;
  const active = mutedUntil && !Number.isNaN(mutedUntil.getTime()) && mutedUntil > new Date();
  if (active) {
    return `<div class="alert-analysis-control is-active"><span>Em análise até ${escapeHtml(mutedUntil.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }))}</span><button type="button" data-resume-alerts="${escapeHtml(scope)}">Retomar alertas</button></div>`;
  }
  return `<div class="alert-analysis-control"><label><span>Silenciar por</span><select data-silence-duration="${escapeHtml(scope)}"><option value="1800">30 min</option><option value="3600">1 hora</option><option value="7200" selected>2 horas</option><option value="14400">4 horas</option></select></label><button type="button" data-silence-alerts="${escapeHtml(scope)}">Em análise</button></div>`;
}

function renderScopes(scopes, availableScopes, defaults) {
  $("alertPolicyScopes").innerHTML = availableScopes.map((scope) => {
    const rule = scopes[scope.id] || {};
    return `
      <article class="alert-process-row" data-alert-scope="${escapeHtml(scope.id)}">
        <div class="alert-process-title"><h3>${escapeHtml(scope.label)}</h3><span>${Object.keys(rule).length ? "Regra própria" : "Regra padrão"}</span>${acknowledgementControl(scope.id, alertAcknowledgements[scope.id])}</div>
        <div class="alert-process-config">
          ${processFieldSet(rule, defaults)}
          <button type="button" class="alert-reset-scope" data-reset-scope="${escapeHtml(scope.id)}">Usar padrão</button>
        </div>
      </article>
    `;
  }).join("");
}

function renderDestinations(destinations, scopes) {
  $("alertPolicyDestinations").innerHTML = destinations.map((destination) => {
    const isGoogleChat = destination.type === "google_chat";
    return `
      <article class="alert-destination" data-destination="${escapeHtml(destination.id)}">
        <div class="alert-destination-head">
          <div><h3>${escapeHtml(destination.name || (isGoogleChat ? "Google Chat" : "Telegram"))}</h3><span>${isGoogleChat ? "Webhook do espaço/grupo" : "Bot e chat IDs configurados no ambiente"}</span></div>
          <div class="alert-destination-actions">
            ${checkbox("Ativo", `data-destination-enabled="${escapeHtml(destination.id)}"`, destination.enabled)}
            ${isGoogleChat ? `<button class="alert-remove-destination" type="button" data-remove-destination="${escapeHtml(destination.id)}">Remover</button>` : ""}
          </div>
        </div>
        ${isGoogleChat ? `
          <label class="alert-group-field">
            <span>Nome do grupo</span>
            <input type="text" maxlength="80" data-destination-name="${escapeHtml(destination.id)}" value="${escapeHtml(destination.name || "Google Chat")}">
          </label>
          <label class="alert-webhook-field">
            <span>Webhook</span>
            <input type="url" data-destination-webhook="${escapeHtml(destination.id)}" placeholder="${destination.webhookConfigured ? "Webhook configurado - cole outro somente para trocar" : "https://chat.googleapis.com/..."}" autocomplete="off">
            <small>${destination.webhookConfigured ? "Webhook configurado." : "Ainda não configurado."}</small>
          </label>
        ` : ""}
        ${scopeChoices(destination, scopes)}
      </article>
    `;
  }).join("");
}

function render(policy, acknowledgements = {}) {
  alertPolicy = policy;
  alertAcknowledgements = acknowledgements.scopes || {};
  $("alertPolicyUpdatedAt").textContent = formatDateTime(policy.updatedAt);
  renderDefaults(policy.defaults || {});
  renderScopes(policy.scopes || {}, policy.availableScopes || [], policy.defaults || {});
  renderDestinations(policy.destinations || [], policy.availableScopes || []);
  $("alertPolicyStatus").textContent = "Configuração carregada.";
}

function readNumber(root, key) {
  return Math.max(0, Number(root.querySelector(`[data-policy-key="${key}"]`)?.value || 0));
}

function readTime(root, key, fallback = "00:00") {
  const value = root.querySelector(`[data-policy-key="${key}"]`)?.value || "";
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(value) ? value : fallback;
}

function readWeekdays(root, selector, fallback) {
  const values = [...root.querySelectorAll(`${selector}:checked`)].map((input) => Number(input.value)).filter(Number.isInteger);
  return values.length ? values : fallback;
}

function readCheckbox(root, selector) {
  return Boolean(root.querySelector(selector)?.checked);
}

function buildPayload() {
  const defaultsRoot = $("alertPolicyDefaults");
  const defaults = {
    weekdays: readWeekdays(defaultsRoot, "[data-policy-weekday]", [0, 1, 2, 3, 4, 5, 6]),
    monitorStart: readTime(defaultsRoot, "monitorStart"),
    monitorEnd: readTime(defaultsRoot, "monitorEnd", "23:59"),
    okCheckIntervalSeconds: readNumber(defaultsRoot, "okCheckIntervalSeconds"),
    failureCheckIntervalSeconds: readNumber(defaultsRoot, "failureCheckIntervalSeconds"),
    firstErrorAfterSeconds: readNumber(defaultsRoot, "firstErrorAfterSeconds"),
    repeatEverySeconds: readNumber(defaultsRoot, "repeatEverySeconds"),
    stopAfterSeconds: readNumber(defaultsRoot, "stopAfterSeconds"),
    sendFailure: readCheckbox(defaultsRoot, "[data-policy-bool=\"sendFailure\"]"),
    sendRecovery: readCheckbox(defaultsRoot, "[data-policy-bool=\"sendRecovery\"]"),
    recoveryRepeatEverySeconds: readNumber(defaultsRoot, "recoveryRepeatEverySeconds"),
    recoverySendOnce: readCheckbox(defaultsRoot, "[data-policy-bool=\"recoverySendOnce\"]"),
    sendProgressSummary: readCheckbox(defaultsRoot, "[data-policy-bool=\"sendProgressSummary\"]"),
    progressSummaryEverySeconds: readNumber(defaultsRoot, "progressSummaryEverySeconds"),
    recoveryOnlyWithinStopWindow: readCheckbox(defaultsRoot, "[data-policy-bool=\"recoveryOnlyWithinStopWindow\"]"),
  };
  const scopes = {};
  document.querySelectorAll("[data-alert-scope]").forEach((row) => {
    const id = row.dataset.alertScope;
    scopes[id] = {
      weekdays: readWeekdays(row, "[data-scope-weekday]", defaults.weekdays),
      monitorStart: readTime(row, "monitorStart"),
      monitorEnd: readTime(row, "monitorEnd", "23:59"),
      okCheckIntervalSeconds: readNumber(row, "okCheckIntervalSeconds"),
      failureCheckIntervalSeconds: readNumber(row, "failureCheckIntervalSeconds"),
      firstErrorAfterSeconds: readNumber(row, "firstErrorAfterSeconds"),
      repeatEverySeconds: readNumber(row, "repeatEverySeconds"),
      stopAfterSeconds: readNumber(row, "stopAfterSeconds"),
      sendFailure: readCheckbox(row, "[data-scope-bool=\"sendFailure\"]"),
      sendRecovery: readCheckbox(row, "[data-scope-bool=\"sendRecovery\"]"),
      recoveryRepeatEverySeconds: readNumber(row, "recoveryRepeatEverySeconds"),
      recoverySendOnce: readCheckbox(row, "[data-scope-bool=\"recoverySendOnce\"]"),
      sendProgressSummary: readCheckbox(row, "[data-scope-bool=\"sendProgressSummary\"]"),
      progressSummaryEverySeconds: readNumber(row, "progressSummaryEverySeconds"),
      recoveryOnlyWithinStopWindow: readCheckbox(row, "[data-scope-bool=\"recoveryOnlyWithinStopWindow\"]"),
    };
  });
  const destinations = (alertPolicy.destinations || []).map((destination) => {
    const id = destination.id;
    const all = document.querySelector(`[data-destination-all="${CSS.escape(id)}"]`)?.checked;
    const selected = all ? ["all"] : [...document.querySelectorAll(`[data-destination-scope="${CSS.escape(id)}"]:checked`)].map((input) => input.value);
    const webhook = document.querySelector(`[data-destination-webhook="${CSS.escape(id)}"]`)?.value.trim() || "";
    const name = document.querySelector(`[data-destination-name="${CSS.escape(id)}"]`)?.value.trim() || destination.name;
    return { ...destination, name, enabled: Boolean(document.querySelector(`[data-destination-enabled="${CSS.escape(id)}"]`)?.checked), scopes: selected.length ? selected : ["all"], webhook };
  });
  return { defaults, scopes, destinations };
}

async function load() {
  try {
    const [policy, acknowledgements] = await Promise.all([
      api("/api/business-monitor/alert-policy"),
      api("/api/business-monitor/alert-acknowledgements"),
    ]);
    render(policy, acknowledgements);
  } catch (error) {
    $("alertPolicyStatus").textContent = error.message;
  }
}

$("alertPolicyForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  button.disabled = true;
  $("alertPolicyStatus").textContent = "Salvando...";
  try {
    render(await api("/api/business-monitor/alert-policy", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(buildPayload()) }));
    $("alertPolicyStatus").textContent = "Configuração salva. A próxima verificação já usará estas regras.";
  } catch (error) {
    $("alertPolicyStatus").textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$("alertPolicyScopes").addEventListener("click", (event) => {
  const silenceButton = event.target.closest("[data-silence-alerts]");
  const resumeButton = event.target.closest("[data-resume-alerts]");
  if ((silenceButton || resumeButton) && alertPolicy) {
    const scope = (silenceButton || resumeButton).dataset.silenceAlerts || (silenceButton || resumeButton).dataset.resumeAlerts;
    const row = document.querySelector(`[data-alert-scope="${CSS.escape(scope)}"]`);
    const durationSeconds = Number(row.querySelector(`[data-silence-duration="${CSS.escape(scope)}"]`)?.value || 7200);
    const button = silenceButton || resumeButton;
    button.disabled = true;
    $("alertPolicyStatus").textContent = resumeButton ? "Retomando alertas..." : "Registrando processo em análise...";
    api("/api/business-monitor/alert-acknowledgements", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ scope, durationSeconds, resume: Boolean(resumeButton) }),
    }).then((acknowledgements) => {
      alertAcknowledgements = acknowledgements.scopes || {};
      renderScopes(alertPolicy.scopes || {}, alertPolicy.availableScopes || [], alertPolicy.defaults || {});
      $("alertPolicyStatus").textContent = resumeButton ? "Alertas retomados." : "Mensagens pausadas; o monitoramento continua ativo.";
    }).catch((error) => {
      $("alertPolicyStatus").textContent = error.message;
      button.disabled = false;
    });
    return;
  }
  const button = event.target.closest("[data-reset-scope]");
  if (!button || !alertPolicy) return;
  const row = document.querySelector(`[data-alert-scope="${CSS.escape(button.dataset.resetScope)}"]`);
  const defaults = alertPolicy.defaults;
  row.querySelectorAll("[data-policy-key]").forEach((input) => { input.value = defaults[input.dataset.policyKey]; });
  row.querySelectorAll("[data-scope-weekday]").forEach((input) => { input.checked = defaults.weekdays.includes(Number(input.value)); });
  row.querySelector("[data-scope-bool=\"sendFailure\"]").checked = Boolean(defaults.sendFailure);
  row.querySelector("[data-scope-bool=\"sendRecovery\"]").checked = Boolean(defaults.sendRecovery);
  row.querySelector("[data-scope-bool=\"recoverySendOnce\"]").checked = Boolean(defaults.recoverySendOnce);
  row.querySelector("[data-scope-bool=\"sendProgressSummary\"]").checked = Boolean(defaults.sendProgressSummary);
  row.querySelector("[data-scope-bool=\"recoveryOnlyWithinStopWindow\"]").checked = Boolean(defaults.recoveryOnlyWithinStopWindow);
});

$("addGoogleChatDestination").addEventListener("click", () => {
  if (!alertPolicy) return;
  const id = `google-chat-${Date.now()}`;
  alertPolicy.destinations.push({
    id,
    name: "Novo grupo Google Chat",
    type: "google_chat",
    enabled: true,
    scopes: ["all"],
    webhookEnv: "NOC_GOOGLE_CHAT_WEBHOOK",
    webhookConfigured: false,
  });
  renderDestinations(alertPolicy.destinations, alertPolicy.availableScopes || []);
  $("alertPolicyStatus").textContent = "Novo grupo adicionado. Informe o webhook e salve a configuração.";
});

$("alertPolicyDestinations").addEventListener("click", (event) => {
  const removeButton = event.target.closest("[data-remove-destination]");
  if (!removeButton || !alertPolicy) return;
  const id = removeButton.dataset.removeDestination;
  alertPolicy.destinations = alertPolicy.destinations.filter((destination) => destination.id !== id);
  renderDestinations(alertPolicy.destinations, alertPolicy.availableScopes || []);
  $("alertPolicyStatus").textContent = "Grupo removido. Salve a configuração para confirmar.";
});

$("alertPolicyDestinations").addEventListener("change", (event) => {
  if (!alertPolicy) return;
  const allId = event.target.dataset.destinationAll;
  const scopeId = event.target.dataset.destinationScope;
  if (allId && event.target.checked) {
    document.querySelectorAll(`[data-destination-scope="${CSS.escape(allId)}"]`).forEach((input) => { input.checked = false; });
  }
  if (scopeId && event.target.checked) {
    const all = document.querySelector(`[data-destination-all="${CSS.escape(scopeId)}"]`);
    if (all) all.checked = false;
  }
});

load();

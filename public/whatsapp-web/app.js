let currentStatus = "";
let currentCategory = "";
let currentSender = "";
let currentStore = "";
let search = "";
let watcherRunning = false;
let lastInteractionAt = 0;
let latestMessagesSignature = "";
let currentView = "messages";
const classificationOptions = new Set([
  "Checking",
  "Causa 1",
  "Causa 2",
  "Causa 3",
  "Causa 4",
  "Causa 5",
  "Causa 6",
  "Causa 7",
  "Causa 19",
  "Causa 20",
  "Causa 21",
  "Transferencia entre lojas",
  "Retificação",
]);

const messagesEl = document.querySelector("#messages");
const contentEl = document.querySelector(".content");
const dashboardEl = document.querySelector("#dashboard");
const showMessagesEl = document.querySelector("#showMessages");
const showDashboardEl = document.querySelector("#showDashboard");
const dashboardBackEl = document.querySelector("#dashboardBack");
const utilityPanelEl = document.querySelector("#utilityPanel");
const dashboardSubtitleEl = document.querySelector("#dashboardSubtitle");
const dashboardCategoriesEl = document.querySelector("#dashboardCategories");
const dashboardStatusesEl = document.querySelector("#dashboardStatuses");
const dashboardSendersEl = document.querySelector("#dashboardSenders");
const dashboardRepliesEl = document.querySelector("#dashboardReplies");
const categoriesEl = document.querySelector("#categories");
const markersEl = document.querySelector("#markers");
const eventsEl = document.querySelector("#events");
const watcherStateEl = document.querySelector("#watcherState");
const toggleWatcherEl = document.querySelector("#toggleWatcher");
const targetChatEl = document.querySelector("#targetChat");
const saveTargetChatEl = document.querySelector("#saveTargetChat");
const categoryFormEl = document.querySelector("#categoryForm");
const categoryIdEl = document.querySelector("#categoryId");
const categoryNameEl = document.querySelector("#categoryName");
const categoryPriorityEl = document.querySelector("#categoryPriority");
const categorySentimentEl = document.querySelector("#categorySentiment");
const categoryKeywordsEl = document.querySelector("#categoryKeywords");
const deleteCategoryEl = document.querySelector("#deleteCategory");
const markerFormEl = document.querySelector("#markerForm");
const markerIdEl = document.querySelector("#markerId");
const markerNameEl = document.querySelector("#markerName");
const markerColorEl = document.querySelector("#markerColor");
const reportSummaryEl = document.querySelector("#reportSummary");
const imageModalEl = document.querySelector("#imageModal");
const imageModalImgEl = document.querySelector("#imageModalImg");
const closeImageModalEl = document.querySelector("#closeImageModal");
const zoomInImageEl = document.querySelector("#zoomInImage");
const zoomOutImageEl = document.querySelector("#zoomOutImage");
const resetZoomImageEl = document.querySelector("#resetZoomImage");
const messageModalEl = document.querySelector("#messageModal");
const messageModalContentEl = document.querySelector("#messageModalContent");
const closeMessageModalEl = document.querySelector("#closeMessageModal");
let activeUtilityPanel = "";
let imageZoom = 1;

function fmtDate(value) {
  return new Intl.DateTimeFormat("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(payload.error || "Erro na API");
  return payload;
}

function markInteraction() {
  lastInteractionAt = Date.now();
}

function isEditingMessage() {
  const active = document.activeElement;
  return Boolean(
    active &&
      messagesEl.contains(active) &&
      ["TEXTAREA", "SELECT", "INPUT", "BUTTON"].includes(active.tagName)
  );
}

function shouldFreezeMessages() {
  return isEditingMessage() || Date.now() - lastInteractionAt < 15000;
}

async function setStatus(id, status) {
  markInteraction();
  await api(`/api/messages/${id}/status`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });
  await refresh();
}

async function moveMessageToCategory(id, category) {
  markInteraction();
  await api(`/api/messages/${id}/category`, {
    method: "POST",
    body: JSON.stringify({ category }),
  });
  latestMessagesSignature = "";
  await refresh();
}

async function setMessageClassification(id, classification) {
  markInteraction();
  await api(`/api/messages/${id}/classification`, {
    method: "POST",
    body: JSON.stringify({ classification }),
  });
  latestMessagesSignature = "";
  await refresh();
}

async function setMessageMarker(id, markerId) {
  markInteraction();
  await api(`/api/messages/${id}/marker`, {
    method: "POST",
    body: JSON.stringify({ markerId: markerId || null }),
  });
  latestMessagesSignature = "";
  await refresh();
}

async function setMessageObservation(id, observation) {
  markInteraction();
  await api(`/api/messages/${id}/observation`, {
    method: "POST",
    body: JSON.stringify({ observation }),
  });
  const message = (window.messageRows || []).find((item) => Number(item.id) === Number(id));
  if (message) message.observation = observation;
  latestMessagesSignature = "";
}

async function queueReply(id) {
  markInteraction();
  const textarea = document.querySelector(`#reply-${id}`);
  const text = textarea?.value.trim();
  if (!text) return;
  await api(`/api/messages/${id}/reply`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  textarea.value = "";
  await refresh();
}

function renderMessages(messages) {
  window.messageRows = messages;
  const signature = messages.map((message) => {
    const replies = (message.replies || []).map((reply) => `${reply.id}:${reply.status}`).join(".");
    return `${message.id}:${message.status}:${message.category}:${message.sentiment}:${message.marker_id || ""}:${message.observation || ""}:${message.attachments?.length || 0}:${replies}`;
  }).join("|");

  if (shouldFreezeMessages() && latestMessagesSignature) {
    return;
  }

  const previousScrollTop = messagesEl.scrollTop;
  const activeId = document.activeElement?.id || "";
  const activeValue = document.activeElement?.value;

  if (signature === latestMessagesSignature && latestMessagesSignature) return;

  messagesEl.innerHTML = renderBoard(messages);
  latestMessagesSignature = signature;
  messagesEl.scrollLeft = previousScrollTop;
  if (activeId) {
    const active = document.getElementById(activeId);
    if (active) {
      active.focus();
      if (typeof activeValue === "string") active.value = activeValue;
    }
  }
}

function renderBoard(messages) {
  const categories = window.categoryRows || [];
  const columns = [
    { type: "category", name: "outro", title: "Caixa de entrada" },
    ...categories.map((category) => ({ type: "category", name: category.name, title: category.name })),
    { type: "status", name: "concluido", title: "Concluido" },
  ];
  const visibleColumns = currentStatus === "concluido"
    ? columns.filter((column) => column.type === "status" && column.name === "concluido")
    : currentCategory
      ? columns.filter((column) => column.type === "category" && column.name === currentCategory)
    : columns;
  const grouped = new Map(visibleColumns.map((column) => [columnKey(column), []]));

  for (const message of messages) {
    const statusKey = columnKey({ type: "status", name: "concluido" });
    const categoryKey = columnKey({ type: "category", name: message.category });
    const fallbackKey = columnKey({ type: "category", name: "outro" });
    const key = message.status === "concluido" && grouped.has(statusKey)
      ? statusKey
      : grouped.has(categoryKey)
        ? categoryKey
        : fallbackKey;
    grouped.get(key)?.push(message);
  }

  if (!messages.length) {
    return "<div class=\"empty-board\"><p>Nenhuma mensagem encontrada.</p></div>";
  }

  return visibleColumns.map((column) => {
    const items = grouped.get(columnKey(column)) || [];
    return `
      <section class="board-column board-${escapeAttr(column.type)}" data-board-type="${escapeAttr(column.type)}" data-board-name="${escapeAttr(column.name)}">
        <header class="board-column-head">
          <h3>${escapeHtml(column.title)}</h3>
          <span>${items.length}</span>
        </header>
        <div
          class="board-dropzone"
          data-board-type="${escapeAttr(column.type)}"
          data-board-name="${escapeAttr(column.name)}"
          ondragover="handleCardDragOver(event)"
          ondragleave="handleCardDragLeave(event)"
          ondrop="handleCardDrop(event)"
        >
          ${items.map(renderMessageCard).join("") || "<p class=\"empty-column\">Sem mensagens</p>"}
        </div>
      </section>
    `;
  }).join("");
}

function columnKey(column) {
  return `${column.type}:${column.name}`;
}

function renderMessageCard(message) {
  return `
    <article
      class="message priority-${message.priority}"
      data-status="${escapeAttr(message.status)}"
      data-category="${escapeAttr(message.category)}"
      draggable="true"
      onclick="openMessageModal(${message.id}, event)"
      ondragstart="handleCardDragStart(event, ${message.id})"
      ondragend="handleCardDragEnd(event)"
    >
      <div class="message-head">
        <div class="contact">
          ${renderMarkerDot(message)}
          <button class="linklike" onclick="filterSender('${escapeAttr(message.sender_name || "")}', event)">${escapeHtml(message.sender_name || message.chat_name)}</button>
        </div>
        <div class="time">${fmtDate(message.captured_at)}</div>
      </div>
      <div class="chat-name">${escapeHtml(message.chat_name)}</div>
      ${renderStoreBadge(message)}
      <div class="text">${escapeHtml(message.text)}</div>
      ${renderAttachments(message.attachments || [])}
      <select class="classification-select" onchange="setMessageClassification(${message.id}, this.value)">
        ${renderClassificationOptions(message.sentiment)}
      </select>
      <select class="marker-select" onchange="setMessageMarker(${message.id}, this.value)">
        ${renderMarkerOptions(message.marker_id)}
      </select>
      <label class="observation-box">
        <span>Observacao</span>
        <textarea id="observation-${message.id}" placeholder="Digite uma observacao" onblur="setMessageObservation(${message.id}, this.value)">${escapeHtml(message.observation || "")}</textarea>
      </label>
      <div class="reply-box">
        <textarea id="reply-${message.id}" placeholder="Responder no grupo"></textarea>
        <button onclick="queueReply(${message.id})">Enviar resposta</button>
      </div>
      ${renderReplies(message.replies || [])}
    </article>
  `;
}

function renderStoreBadge(message) {
  if (!message.store_number) return "";
  return `<button class="store-badge" onclick="filterStore('${escapeAttr(message.store_number)}', event)">Loja ${escapeHtml(message.store_number)}</button>`;
}

function renderMarkerDot(message) {
  if (!message.marker_id || !message.marker_color) return "";
  return `<span class="marker-dot" style="background:${escapeAttr(message.marker_color)}" title="${escapeAttr(message.marker_name || "")}"></span>`;
}

function renderMarkerOptions(selected) {
  const rows = window.markerRows || [];
  return [
    `<option value="">Sem marcador</option>`,
    ...rows.map((marker) => `
      <option value="${marker.id}" ${Number(marker.id) === Number(selected) ? "selected" : ""}>${escapeHtml(marker.name)}</option>
    `),
  ].join("");
}

function renderClassificationOptions(selected) {
  return [...classificationOptions].map((option) => `
    <option value="${escapeHtml(option)}" ${option === selected ? "selected" : ""}>${escapeHtml(option)}</option>
  `).join("");
}

function handleCardDragStart(event, id) {
  if (
    event.target.closest("textarea, select, input, .attachments button") ||
    event.target.closest("button")
  ) {
    event.preventDefault();
    return;
  }
  markInteraction();
  const message = event.currentTarget.closest(".message");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", String(id));
  event.dataTransfer.setData("application/x-message-status", message?.dataset.status || "");
  message?.classList.add("dragging");
}

function handleCardDragEnd(event) {
  event.currentTarget.closest(".message")?.classList.remove("dragging");
  document.querySelectorAll(".board-dropzone.drag-over").forEach((item) => item.classList.remove("drag-over"));
}

function handleCardDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add("drag-over");
}

function handleCardDragLeave(event) {
  event.currentTarget.classList.remove("drag-over");
}

async function handleCardDrop(event) {
  event.preventDefault();
  event.currentTarget.classList.remove("drag-over");
  const id = Number(event.dataTransfer.getData("text/plain"));
  const boardType = event.currentTarget.dataset.boardType;
  const boardName = event.currentTarget.dataset.boardName;
  const previousStatus = event.dataTransfer.getData("application/x-message-status");
  if (!id || !boardType || !boardName) return;
  if (boardType === "status") {
    await setStatus(id, boardName);
    return;
  }
  if (previousStatus === "concluido") {
    await api(`/api/messages/${id}/category`, {
      method: "POST",
      body: JSON.stringify({ category: boardName }),
    });
    await api(`/api/messages/${id}/status`, {
      method: "POST",
      body: JSON.stringify({ status: "em_atendimento" }),
    });
    latestMessagesSignature = "";
    await refresh();
    return;
  }
  await moveMessageToCategory(id, boardName);
}

function renderReplies(replies) {
  if (!replies.length) return "";
  return `
    <div class="reply-history">
      ${replies.map((reply) => `
        <div class="reply-item">
          <strong>${escapeHtml(reply.status)}</strong>
          <span>${escapeHtml(reply.text)}</span>
          ${reply.error ? `<small>${escapeHtml(reply.error)}</small>` : ""}
        </div>
      `).join("")}
    </div>
  `;
}

function renderAttachments(attachments) {
  if (!attachments.length) return "";
  return `
    <div class="attachments">
      ${attachments.map((attachment) => `
        <button onclick="openImageModal('/api/media?path=${encodeURIComponent(attachment.file_path)}')">
          <img src="/api/media?path=${encodeURIComponent(attachment.file_path)}" alt="Imagem recebida" />
        </button>
      `).join("")}
    </div>
  `;
}

function openImageModal(src) {
  markInteraction();
  imageZoom = 1;
  applyImageZoom();
  imageModalImgEl.src = src;
  imageModalEl.hidden = false;
}

function closeImageModal() {
  imageModalEl.hidden = true;
  imageModalImgEl.src = "";
}

function applyImageZoom() {
  imageModalImgEl.style.transform = `scale(${imageZoom})`;
  resetZoomImageEl.textContent = `${Math.round(imageZoom * 100)}%`;
}

function zoomImage(delta) {
  imageZoom = Math.min(4, Math.max(0.5, imageZoom + delta));
  applyImageZoom();
}

function openMessageModal(id, event) {
  if (event?.target?.closest("textarea, select, input, button, .attachments")) return;
  const message = [...(window.messageRows || []), ...(window.relatedRows || [])].find((item) => Number(item.id) === Number(id));
  if (!message) return;
  markInteraction();
  messageModalContentEl.innerHTML = `
    <div class="message-modal-head">
      <div class="contact">
        ${renderMarkerDot(message)}
        <span>${escapeHtml(message.sender_name || message.chat_name)}</span>
      </div>
      <div class="time">${fmtDate(message.captured_at)}</div>
    </div>
    <div class="chat-name">${escapeHtml(message.chat_name)}</div>
    ${renderStoreBadge(message)}
    <div class="message-modal-text">${escapeHtml(message.text || "Mensagem sem texto.")}</div>
    ${renderAttachments(message.attachments || [])}
    <div class="message-modal-meta">
      <span>Categoria: ${escapeHtml(message.category || "outro")}</span>
      <span>Status: ${escapeHtml(message.status || "novo")}</span>
      <span>Classificacao: ${escapeHtml(message.sentiment || "Checking")}</span>
      <span>Marcador: ${escapeHtml(message.marker_name || "sem marcador")}</span>
      <span>Loja: ${escapeHtml(message.store_number || "sem loja")}</span>
    </div>
    <div class="message-modal-controls">
      <select class="classification-select" onchange="setMessageClassification(${message.id}, this.value)">
        ${renderClassificationOptions(message.sentiment)}
      </select>
      <select class="marker-select" onchange="setMessageMarker(${message.id}, this.value)">
        ${renderMarkerOptions(message.marker_id)}
      </select>
    </div>
    <label class="observation-box observation-box-large">
      <span>Observacao</span>
      <textarea id="modal-observation-${message.id}" placeholder="Digite uma observacao" onblur="setMessageObservation(${message.id}, this.value)">${escapeHtml(message.observation || "")}</textarea>
    </label>
    ${renderReplies(message.replies || [])}
    <section class="related-box">
      <h3>Mensagens relacionadas</h3>
      <div id="relatedMessages">Carregando...</div>
    </section>
  `;
  messageModalEl.hidden = false;
  loadRelatedMessages(message.id);
}

function closeMessageModal() {
  messageModalEl.hidden = true;
  messageModalContentEl.innerHTML = "";
}

function renderStats(stats, watcher, settings, categoryRows) {
  const byStatus = Object.fromEntries(stats.byStatus.map((item) => [item.status, item.total]));
  document.querySelector("#m24").textContent = stats.recent24h;
  document.querySelector("#mNew").textContent = byStatus.novo || 0;
  document.querySelector("#mHigh").textContent = stats.highPriority || 0;
  if (document.activeElement !== targetChatEl) {
    targetChatEl.value = settings.targetChat || "";
  }

  const counts = Object.fromEntries(stats.byCategory.map((item) => [item.category, item.total]));
  categoriesEl.innerHTML = categoryRows.map((item) => `
    <div class="category-row ${currentCategory === item.name ? "active" : ""}">
      <button class="category-filter" onclick="filterCategory('${escapeAttr(item.name)}')">${escapeHtml(item.name)}</button>
      <button class="count" onclick="filterCategory('${escapeAttr(item.name)}')">${counts[item.name] || 0}</button>
      <small>${escapeHtml(item.priority)} · ${escapeHtml(item.sentiment)}</small>
      <button class="edit-category" onclick="editCategory(${item.id})">Editar</button>
      <button class="delete-category-inline" onclick="deleteCategory(${item.id})">Apagar</button>
    </div>
  `).join("") || "<p>Nenhuma categoria.</p>";

  watcherRunning = watcher.running;
  watcherStateEl.textContent = watcher.running ? `Watcher rodando (PID ${watcher.pid})` : "Watcher parado";
  toggleWatcherEl.textContent = watcher.running ? "Parar" : "Iniciar";
}

function renderMarkers(markerRows) {
  markersEl.innerHTML = markerRows.map((marker) => `
    <div class="marker-row">
      <button class="marker-main" onclick="editMarker(${marker.id})">
        <span class="marker-dot" style="background:${escapeAttr(marker.color)}"></span>
        <strong>${escapeHtml(marker.name)}</strong>
      </button>
      <button class="delete-marker-inline" onclick="deleteMarker(${marker.id})">Apagar</button>
    </div>
  `).join("") || "<p>Nenhum marcador cadastrado.</p>";
}

function renderEvents(events) {
  eventsEl.innerHTML = events.slice(0, 20).map((event) => `
    <div class="event">
      <strong>${escapeHtml(event.type)}</strong><br>
      ${fmtDate(event.created_at)}<br>
      <span>${escapeHtml(eventSummary(event.payload))}</span>
    </div>
  `).join("") || "<p>Nenhum evento.</p>";
}

function renderReport(report) {
  const topCategories = report.byCategory.slice(0, 5).map((item) => `${item.category}: ${item.total}`).join(" · ");
  const replies = report.replies.map((item) => `${item.status}: ${item.total}`).join(" · ") || "sem respostas";
  reportSummaryEl.innerHTML = `
    <div class="report-line"><strong>${report.attachments}</strong><span>imagens</span></div>
    <div class="report-text">${escapeHtml(topCategories || "sem categorias")}</div>
    <div class="report-text">${escapeHtml(replies)}</div>
  `;
}

function renderDashboard(report, stats) {
  const byStatus = Object.fromEntries(report.byStatus.map((item) => [item.status, item.total]));
  const total = report.byStatus.reduce((sum, item) => sum + item.total, 0);
  document.querySelector("#dTotal").textContent = total;
  document.querySelector("#dNew").textContent = byStatus.novo || 0;
  document.querySelector("#dHigh").textContent = stats.highPriority || 0;
  document.querySelector("#dImages").textContent = report.attachments || 0;

  const target = targetChatEl.value.trim();
  dashboardSubtitleEl.textContent = target
    ? `Resumo do grupo ${target}`
    : "Resumo das mensagens monitoradas";

  dashboardCategoriesEl.innerHTML = renderBars(
    report.byCategory,
    "category",
    "Nenhuma categoria com mensagem.",
    (name) => `filterCategoryFromDashboard('${escapeAttr(name)}')`
  );
  dashboardStatusesEl.innerHTML = renderBars(
    report.byStatus,
    "status",
    "Nenhum status registrado.",
    (name) => `filterStatusFromDashboard('${escapeAttr(name)}')`
  );
  dashboardSendersEl.innerHTML = renderList(
    report.bySender,
    "sender",
    "Nenhum remetente registrado."
  );
  dashboardRepliesEl.innerHTML = renderBars(
    report.replies,
    "status",
    "Nenhuma resposta enviada pela pagina.",
    null
  );
}

function renderRelated(messages) {
  if (!messages.length) return "<p>Nenhuma mensagem relacionada.</p>";
  return messages.map((message) => `
    <button class="related-row" type="button" onclick="openMessageModal(${message.id})">
      <strong>${message.store_number ? `Loja ${escapeHtml(message.store_number)}` : escapeHtml(message.sender_name || "sem remetente")}</strong>
      <span>${escapeHtml(message.text || "").slice(0, 180)}</span>
      <small>${fmtDate(message.captured_at)}</small>
    </button>
  `).join("");
}

async function loadRelatedMessages(id) {
  const target = document.querySelector("#relatedMessages");
  if (!target) return;
  try {
    const payload = await api(`/api/messages/${id}/related`);
    window.relatedRows = payload.messages || [];
    target.innerHTML = renderRelated(payload.messages || []);
  } catch (error) {
    target.innerHTML = `<p>${escapeHtml(error.message)}</p>`;
  }
}

function renderBars(rows, labelKey, emptyText, onClick) {
  if (!rows.length) return `<p>${emptyText}</p>`;
  const max = Math.max(...rows.map((item) => item.total), 1);
  return rows.map((item) => {
    const label = item[labelKey] || "sem informacao";
    const width = Math.max(4, Math.round((item.total / max) * 100));
    const click = onClick ? ` onclick="${onClick(label)}"` : "";
    return `
      <button class="bar-row" type="button"${click}>
        <span>${escapeHtml(label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width: ${width}%"></div></div>
        <strong>${item.total}</strong>
      </button>
    `;
  }).join("");
}

function renderList(rows, labelKey, emptyText) {
  if (!rows.length) return `<p>${emptyText}</p>`;
  return rows.map((item) => `
    <div class="dashboard-list-row">
      <span>${escapeHtml(item[labelKey] || "sem informacao")}</span>
      <strong>${item.total}</strong>
    </div>
  `).join("");
}

function setView(view) {
  currentView = view;
  const isDashboard = view === "dashboard";
  contentEl.hidden = isDashboard;
  dashboardEl.hidden = !isDashboard;
  utilityPanelEl.hidden = isDashboard || !activeUtilityPanel;
  showMessagesEl.classList.toggle("active", !isDashboard);
  showDashboardEl.classList.toggle("active", isDashboard);
  refresh({ updateMessages: !isDashboard });
}

function toggleUtilityPanel(panel) {
  markInteraction();
  activeUtilityPanel = activeUtilityPanel === panel ? "" : panel;
  utilityPanelEl.hidden = !activeUtilityPanel || currentView === "dashboard";
  document.querySelectorAll(".utility-menu button").forEach((button) => {
    button.classList.toggle("active", button.dataset.panel === activeUtilityPanel);
  });
  document.querySelectorAll("[data-panel-content]").forEach((section) => {
    section.hidden = section.dataset.panelContent !== activeUtilityPanel;
  });
}

function eventSummary(payload) {
  try {
    const parsed = JSON.parse(payload || "{}");
    const text = parsed.message || parsed.text || parsed.targetChat || JSON.stringify(parsed);
    return String(text).slice(0, 180);
  } catch {
    return String(payload || "").slice(0, 180);
  }
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;",
  }[char]));
}

function escapeAttr(value) {
  return String(value ?? "").replace(/['\\]/g, "\\$&");
}

async function refresh({ updateMessages = true } = {}) {
  const params = new URLSearchParams();
  if (currentStatus) params.set("status", currentStatus);
  if (currentCategory) params.set("category", currentCategory);
  if (currentSender) params.set("sender", currentSender);
  if (currentStore) params.set("store", currentStore);
  if (search) params.set("q", search);

  const [statsPayload, eventsPayload, categoriesPayload, markersPayload, reportPayload] = await Promise.all([
    api("/api/stats"),
    api("/api/events"),
    api("/api/categories"),
    api("/api/markers"),
    api("/api/reports/summary"),
  ]);
  window.categoryRows = categoriesPayload.categories;
  window.markerRows = markersPayload.markers;
  renderStats(statsPayload.stats, statsPayload.watcher, statsPayload.settings, categoriesPayload.categories);
  renderMarkers(markersPayload.markers);
  renderEvents(eventsPayload.events);
  renderReport(reportPayload.report);
  renderDashboard(reportPayload.report, statsPayload.stats);

  if (updateMessages && currentView === "messages") {
    const messagesPayload = await api(`/api/messages?${params}`);
    renderMessages(messagesPayload.messages);
  }
}

document.querySelectorAll("nav button").forEach((button) => {
  button.addEventListener("click", () => {
    markInteraction();
    if (currentView !== "messages") setView("messages");
    document.querySelectorAll("nav button").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    currentStatus = button.dataset.status;
    if (!currentStatus) {
      currentCategory = "";
      currentSender = "";
      currentStore = "";
    }
    latestMessagesSignature = "";
    refresh();
  });
});

showMessagesEl.addEventListener("click", () => {
  markInteraction();
  setView("messages");
});

showDashboardEl.addEventListener("click", () => {
  markInteraction();
  setView("dashboard");
});

dashboardBackEl.addEventListener("click", () => {
  markInteraction();
  setView("messages");
});

document.querySelectorAll(".utility-menu button").forEach((button) => {
  button.addEventListener("click", () => toggleUtilityPanel(button.dataset.panel));
});

document.querySelector("#search").addEventListener("input", (event) => {
  markInteraction();
  search = event.target.value.trim();
  latestMessagesSignature = "";
  clearTimeout(window.searchTimer);
  window.searchTimer = setTimeout(refresh, 250);
});

toggleWatcherEl.addEventListener("click", async () => {
  markInteraction();
  await api(watcherRunning ? "/api/watcher/stop" : "/api/watcher/start", { method: "POST" });
  await refresh();
});

saveTargetChatEl.addEventListener("click", async () => {
  markInteraction();
  await api("/api/settings", {
    method: "POST",
    body: JSON.stringify({ targetChat: targetChatEl.value.trim() }),
  });
  await refresh();
});

categoryFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  markInteraction();
  await api("/api/categories", {
    method: "POST",
    body: JSON.stringify({
      id: categoryIdEl.value || undefined,
      name: categoryNameEl.value,
      priority: categoryPriorityEl.value,
      sentiment: categorySentimentEl.value,
      keywords: categoryKeywordsEl.value,
      active: true,
    }),
  });
  categoryFormEl.reset();
  categoryIdEl.value = "";
  await refresh();
});

deleteCategoryEl.addEventListener("click", async () => {
  markInteraction();
  const id = categoryIdEl.value;
  if (!id) return;
  await deleteCategory(id);
});

markerFormEl.addEventListener("submit", async (event) => {
  event.preventDefault();
  markInteraction();
  await api("/api/markers", {
    method: "POST",
    body: JSON.stringify({
      id: markerIdEl.value || undefined,
      name: markerNameEl.value,
      color: markerColorEl.value,
      active: true,
    }),
  });
  markerFormEl.reset();
  markerColorEl.value = "#2764b8";
  markerIdEl.value = "";
  await refresh();
});

async function deleteCategory(id) {
  markInteraction();
  const password = prompt("Digite a senha para apagar a categoria");
  if (password === null) return;
  await api(`/api/categories/${id}`, {
    method: "DELETE",
    body: JSON.stringify({ password }),
  });
  categoryFormEl.reset();
  categoryIdEl.value = "";
  currentCategory = "";
  latestMessagesSignature = "";
  await refresh();
}

function editCategory(id) {
  markInteraction();
  const category = (window.categoryRows || []).find((item) => item.id === id);
  if (!category) return;
  categoryIdEl.value = category.id;
  categoryNameEl.value = category.name;
  categoryPriorityEl.value = category.priority;
  categorySentimentEl.value = classificationOptions.has(category.sentiment) ? category.sentiment : "Checking";
  categoryKeywordsEl.value = category.keywords;
}

function editMarker(id) {
  markInteraction();
  const marker = (window.markerRows || []).find((item) => item.id === id);
  if (!marker) return;
  markerIdEl.value = marker.id;
  markerNameEl.value = marker.name;
  markerColorEl.value = marker.color;
}

async function deleteMarker(id) {
  markInteraction();
  await api(`/api/markers/${id}`, { method: "DELETE" });
  markerFormEl.reset();
  markerColorEl.value = "#2764b8";
  markerIdEl.value = "";
  latestMessagesSignature = "";
  await refresh();
}

function filterCategory(name) {
  markInteraction();
  currentCategory = currentCategory === name ? "" : name;
  currentSender = "";
  currentStore = "";
  latestMessagesSignature = "";
  refresh();
}

function filterSender(name, event) {
  event?.stopPropagation();
  if (!name) return;
  markInteraction();
  currentSender = currentSender === name ? "" : name;
  currentStore = "";
  currentCategory = "";
  latestMessagesSignature = "";
  refresh();
}

function filterStore(store, event) {
  event?.stopPropagation();
  if (!store) return;
  markInteraction();
  currentStore = currentStore === store ? "" : store;
  currentSender = "";
  currentCategory = "";
  latestMessagesSignature = "";
  refresh();
}

function filterCategoryFromDashboard(name) {
  markInteraction();
  currentCategory = name;
  currentStatus = "";
  document.querySelectorAll("nav button").forEach((item) => item.classList.toggle("active", item.dataset.status === ""));
  latestMessagesSignature = "";
  setView("messages");
}

function filterStatusFromDashboard(status) {
  markInteraction();
  currentStatus = status;
  currentCategory = "";
  document.querySelectorAll("nav button").forEach((item) => item.classList.toggle("active", item.dataset.status === status));
  latestMessagesSignature = "";
  setView("messages");
}

messagesEl.addEventListener("focusin", markInteraction);
messagesEl.addEventListener("input", markInteraction);
messagesEl.addEventListener("click", markInteraction);
closeImageModalEl.addEventListener("click", closeImageModal);
zoomInImageEl.addEventListener("click", () => zoomImage(0.25));
zoomOutImageEl.addEventListener("click", () => zoomImage(-0.25));
resetZoomImageEl.addEventListener("click", () => {
  imageZoom = 1;
  applyImageZoom();
});
imageModalEl.addEventListener("click", (event) => {
  if (event.target === imageModalEl) closeImageModal();
});
closeMessageModalEl.addEventListener("click", closeMessageModal);
messageModalEl.addEventListener("click", (event) => {
  if (event.target === messageModalEl) closeMessageModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !imageModalEl.hidden) closeImageModal();
  if (event.key === "Escape" && !messageModalEl.hidden) closeMessageModal();
});

window.setStatus = setStatus;
window.queueReply = queueReply;
window.openImageModal = openImageModal;
window.openMessageModal = openMessageModal;
window.editCategory = editCategory;
window.editMarker = editMarker;
window.deleteCategory = deleteCategory;
window.deleteMarker = deleteMarker;
window.filterCategory = filterCategory;
window.filterSender = filterSender;
window.filterStore = filterStore;
window.filterCategoryFromDashboard = filterCategoryFromDashboard;
window.filterStatusFromDashboard = filterStatusFromDashboard;
window.setMessageClassification = setMessageClassification;
window.setMessageMarker = setMessageMarker;
window.setMessageObservation = setMessageObservation;
window.handleCardDragStart = handleCardDragStart;
window.handleCardDragEnd = handleCardDragEnd;
window.handleCardDragOver = handleCardDragOver;
window.handleCardDragLeave = handleCardDragLeave;
window.handleCardDrop = handleCardDrop;
refresh();
setInterval(() => {
  refresh({ updateMessages: !shouldFreezeMessages() });
}, 5000);

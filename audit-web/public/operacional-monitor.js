const qty = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
let notasRejeitadasVisiveis = [];
let pdvQueueStages = [];

function $(id) {
  return document.getElementById(id);
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

function formatDateTime(value, includeSeconds = false) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    ...(includeSeconds ? { second: "2-digit" } : {}),
  });
}

function formatTime(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusClass(status) {
  return `business-${String(status || "sem_coleta").replaceAll("_", "-")}`;
}

function isOk(stage) {
  return ["concluido", "concluido_atrasado", "ok"].includes(String(stage?.status || ""));
}

function isBad(stage) {
  return Number(stage?.severity || 0) >= 3 || ["erro", "atrasado", "sem_acesso"].includes(String(stage?.status || ""));
}

function chipList(items, cls = "") {
  const visible = (items || []).slice(0, 30);
  const extra = Math.max(0, (items || []).length - visible.length);
  if (!visible.length && !extra) return `<span class="op-empty">Sem dados</span>`;
  return [
    ...visible.map((item) => `<span class="op-chip ${cls}">${item}</span>`),
    extra ? `<span class="op-chip more">+${extra}</span>` : "",
  ].join("");
}

function shortIssue(stage) {
  const storeTotal = Number(stage?.storeTotal || 0);
  const storeImported = Number(stage?.storeImported || 0);
  const storePending = Number(stage?.storePending || 0);
  if (storeTotal > 0 && (storePending > 0 || String(stage?.status || "") === "concluido")) {
    const importedFiles = Number(stage?.importedCount || 0);
    const pendingFiles = Number(stage?.pendingCount || 0);
    if (importedFiles || pendingFiles) {
      return `Arquivos ${formatNumber(importedFiles)}/${formatNumber(importedFiles + pendingFiles)} · lojas ${formatNumber(storeImported)}/${formatNumber(storeTotal)}`;
    }
    return `${formatNumber(storeImported)}/${formatNumber(storeTotal)} lojas${storePending ? ` · faltam ${formatNumber(storePending)}` : ""}`;
  }
  if (Number(stage?.severity || 0) <= 0) return "";
  if (stage?.variationCount !== "" && stage?.variationCount !== undefined && Number(stage.variationCount) > 0) {
    const first = (stage.variationStores || [])[0];
    const suffix = first?.store ? ` · L-${first.store} ${first.percent}%` : "";
    return `Variacao ${formatNumber(stage.variationCount)} loja(s)${suffix}`;
  }
  if (stage?.pendingCount !== "" && stage?.pendingCount !== undefined && Number(stage.pendingCount) > 0) {
    const imported = Number(stage?.importedCount || 0);
    const pending = Number(stage.pendingCount || 0);
    if (imported > 0) return `${formatNumber(imported)}/${formatNumber(imported + pending)} importados · faltam ${formatNumber(pending)}`;
    return `Sem imp. ${formatNumber(pending)}`;
  }
  if (stage?.missingInFile !== "" && stage?.missingInFile !== undefined) {
    const missing = Number(stage.missingInFile || 0);
    const extra = Number(stage.extraInFile || 0);
    const fileCount = Number(stage.fileCount || 0);
    const plenoCount = Number(stage.plenoCount || 0);
    if (missing || extra) return `Pleno ${formatNumber(plenoCount)} · arquivo ${formatNumber(fileCount)} · dif. ${formatNumber(missing + extra)}`;
    if (fileCount || plenoCount) return `Pleno ${formatNumber(plenoCount)} · arquivo ${formatNumber(fileCount)}`;
  }
  if (stage?.expectedCount !== "" && stage?.expectedCount !== undefined) {
    const expected = Number(stage.expectedCount || 0);
    const count = Number(stage.count || 0);
    const missing = stage.missingFiles || [];
    if (expected) {
      const shortMissing = missing.map((name) => String(name).replace(/^MERCADORIA_/, ""));
      return missing.length ? `${formatNumber(count)}/${formatNumber(expected)} · falta ${shortMissing.join(", ")}` : `${formatNumber(count)}/${formatNumber(expected)} arquivos`;
    }
  }
  const processCount = Array.isArray(stage?.processDetails) ? stage.processDetails.length : 0;
  if (processCount) return `${formatNumber(processCount)} processo(s) ativo(s)`;
  const details = String(stage?.details || stage?.description || "").replace(/\s+/g, " ").trim();
  return details ? details.split(".")[0].slice(0, 92) : "";
}

function stageCard(stage, index) {
  const status = statusClass(stage?.status);
  const pendingCount = Number(stage?.pendingCount || 0);
  const importedCount = Number(stage?.importedCount || 0);
  const metric = importedCount || pendingCount
    ? `${formatNumber(importedCount)}/${formatNumber(importedCount + pendingCount)} importados${pendingCount ? ` · faltam ${formatNumber(pendingCount)}` : ""}`
    : "";
  const target = stage?.targetTime || "-";
  const finishedAt = formatTime(stage?.actualAt);
  const statusText = [stage?.statusLabel || stage?.status || "-", finishedAt !== "-" ? finishedAt : ""].filter(Boolean).join(" · ");
  const issue = shortIssue(stage);
  const sideInfo = issue || metric;
  const tooltip = [
    stage?.details || "",
    stage?.actualAt ? `Ultima conferencia: ${formatDateTime(stage.actualAt, true)}` : "",
  ].filter(Boolean).join(" | ");
  return `
    <article class="op-step ${status}"${tooltip ? ` title="${escapeHtml(tooltip)}"` : ""}>
      <div class="op-step-marker"><b>${index + 1}</b><span>${target}</span></div>
      <div class="op-step-body">
        <strong>${escapeHtml(stage?.label || "-")}</strong>
        <div class="op-step-status-row">
          <span class="pill ${status}">${escapeHtml(statusText)}</span>
          ${sideInfo ? `<small class="op-step-note" title="${escapeHtml(stage?.details || sideInfo)}">${escapeHtml(sideInfo)}</small>` : ""}
        </div>
      </div>
    </article>
  `;
}

function renderTimeline(id, stages) {
  $(id).innerHTML = (stages || []).map(stageCard).join("") || `<span class="op-empty">Sem coleta</span>`;
}

function findStage(stages, id) {
  return (stages || []).find((stage) => stage.id === id) || {};
}

function renderPedidos(data) {
  const stages = data.stages || [];
  if (data.noSchedule) {
    const percent = 0;
    const gaugeColor = "#6b7280";
    $("pedidosPercent").textContent = "-";
    document.querySelector(".op-gauge").style.setProperty("--pct", percent);
    document.querySelector(".op-gauge").style.setProperty("--needle-angle", "-180deg");
    document.querySelector(".op-gauge").style.setProperty("--gauge-color", gaugeColor);
    document.querySelector(".op-progress").style.setProperty("--gauge-color", gaugeColor);
    $("pedidosImported").textContent = "0";
    $("pedidosTotal").textContent = "/ 0 lojas acompanhadas";
    $("pedidosPlenoDetail").textContent = "Domingo sem pedidos RELEX";
    $("pedidosPendingTitle").textContent = "Pendentes (0)";
    $("pedidosOkTitle").textContent = "Concluidas (0)";
    $("pedidosPendingList").innerHTML = `<span class="op-empty">Sem agenda hoje</span>`;
    $("pedidosOkList").innerHTML = `<span class="op-empty">Sem agenda hoje</span>`;
    $("pedidosNotice").textContent = data.notice || "";
    renderTimeline("pedidosTimeline", stages.filter((stage) => !["pedido_concluido", "lojas_diaflex"].includes(stage.id)));
    return;
  }
  const pleno = findStage(stages, "arquivo_vs_pleno");
  const diaflex = findStage(stages, "lojas_diaflex");
  const concluido = findStage(stages, "pedido_concluido");
  const fluxo = diaflex.id ? diaflex : pleno;
  const lojasConcluidas = fluxo.lojasNumerosConcluidas || fluxo.lojasNumerosPleno || [];
  const lojasEsperadas = fluxo.lojasNumerosEsperadas || pleno.lojasNumerosEsperadas || [];
  const totalEsperado = Number(fluxo.lojasEsperadas || fluxo.lojasArquivo || lojasEsperadas.length || pleno.lojasEsperadas || pleno.lojasArquivo || concluido.lojasArquivo || pleno.pedidosArquivo || concluido.pedidosArquivo || 0);
  const totalConcluido = Number(fluxo.lojasConcluidas || fluxo.lojasPleno || lojasConcluidas.length || fluxo.pedidosImportados || fluxo.count || 0);
  const percent = totalEsperado ? Math.round((totalConcluido / totalEsperado) * 100) : 0;
  const lojasPendentes = fluxo.pendingStores || [];
  const pedidosPendentes = concluido.pedidosPendentesConclusao || [];
  const gaugeColor = percent >= 100 ? "#11804b" : percent >= 60 ? "#c28a00" : "#c93535";

  $("pedidosPercent").textContent = `${percent}%`;
  document.querySelector(".op-gauge").style.setProperty("--pct", percent);
  document.querySelector(".op-gauge").style.setProperty("--needle-angle", `${-180 + (Math.max(0, Math.min(100, percent)) * 1.8)}deg`);
  document.querySelector(".op-gauge").style.setProperty("--gauge-color", gaugeColor);
  document.querySelector(".op-progress").style.setProperty("--gauge-color", gaugeColor);
  $("pedidosImported").textContent = formatNumber(totalConcluido);
  $("pedidosTotal").textContent = `/ ${formatNumber(totalEsperado)} lojas acompanhadas`;
  $("pedidosPlenoDetail").textContent = `Monitoramento em tempo real de ${formatNumber(totalEsperado || lojasConcluidas.length || lojasPendentes.length)} lojas`;
  $("pedidosPendingTitle").textContent = `Pendentes (${formatNumber(lojasPendentes.length || pedidosPendentes.length)})`;
  $("pedidosOkTitle").textContent = `Concluidas (${formatNumber(lojasConcluidas.length)})`;
  $("pedidosPendingList").innerHTML = chipList(lojasPendentes.length ? lojasPendentes.map((item) => `L-${item}`) : pedidosPendentes, "pending");
  $("pedidosOkList").innerHTML = chipList(lojasConcluidas.map((item) => `L-${item}`), "ok");
  $("pedidosNotice").textContent = data.notice || "";
  renderTimeline("pedidosTimeline", stages.filter((stage) => !["pedido_concluido", "lojas_diaflex"].includes(stage.id)));
}

function renderPromo(data) {
  const stages = data.stages || [];
  const cycleMeta = (items) => {
    const started = items.map((item) => item.cycleStartedAt).filter(Boolean).sort()[0];
    const finished = items.map((item) => item.cycleFinishedAt).filter(Boolean).sort().at(-1);
    const frozen = items.some((item) => item.cycleFrozen);
    if (frozen) return `Ciclo fechado · Início ${formatDateTime(started)} · Término ${formatDateTime(finished)}`;
    return data.statusFileExists ? `Em acompanhamento · Início ${formatDateTime(started)}` : "Sem coleta";
  };
  const cycle0430 = stages.filter((stage) => String(stage.batch || "").includes("04:30"));
  const cycle0630Preprod = stages.filter((stage) => String(stage.batch || "").includes("06:30") && String(stage.id || "").includes("_s1_"));
  const cycle0630Prod = stages.filter((stage) => String(stage.batch || "").includes("06:30") && String(stage.id || "").includes("_s2_"));
  $("promo0430Meta").textContent = cycleMeta(cycle0430);
  $("promo0630Meta").textContent = cycleMeta(cycle0630Prod);
  $("promo0630PreprodMeta").textContent = cycleMeta(cycle0630Preprod);
  renderTimeline("promo0430Timeline", cycle0430);
  renderTimeline("promo0630PreprodTimeline", cycle0630Preprod);
  renderTimeline("promo0630ProdTimeline", cycle0630Prod);
}

function statusCard(stage) {
  const cls = statusClass(stage?.status);
  const label = stage?.statusLabel || stage?.status || "Sem coleta";
  const icon = isBad(stage) ? "x" : isOk(stage) ? "ok" : "...";
  const issue = shortIssue(stage);
  return `
    <div class="op-status ${cls}">
      <strong>${icon}</strong>
      <div>
        <span>${label}</span>
        <small>Prazo ${stage?.targetTime || "-"} · Realizado ${formatDateTime(stage?.actualAt)}</small>
        ${issue ? `<small>${escapeHtml(issue)}</small>` : ""}
        <p>${stage?.details || stage?.description || ""}</p>
      </div>
    </div>
  `;
}

function renderNotasRejeitadas(data) {
  const stage = (data.stages || [])[0] || {};
  const cls = statusClass(stage?.status);
  const label = stage?.statusLabel || stage?.status || "Sem coleta";
  const notes = stage?.notes || [];
  notasRejeitadasVisiveis = notes.slice(0, 4);
  const sourceText = stage?.source ? String(stage.source).replace("/servpleno/importacao/NFE/", "") : "";
  const rows = notasRejeitadasVisiveis.map((note, index) => `
    <button class="op-note-row op-note-button" type="button" data-nota-index="${index}" title="Abrir XML rejeitado">
      <strong>NF ${escapeHtml(note.nota || "-")} · L-${escapeHtml(note.loja || "-")}</strong>
      <span>${escapeHtml(note.motivo || "Rejeitada sem entrada no Pleno")}</span>
    </button>
  `).join("");
  const extra = notes.length > 4 ? `<small class="op-note-extra">+${formatNumber(notes.length - 4)} nota(s)</small>` : "";
  $("notasRejeitadasMeta").textContent = data.statusFileExists ? `Coleta ${formatDateTime(data.updatedAt)}` : "Sem coleta";
  $("notasRejeitadasCard").innerHTML = `
    <div class="op-notes-status ${cls}">
      <span class="pill ${cls}">${escapeHtml(label)}${stage.count !== "" ? ` · ${formatNumber(stage.count)}` : ""}</span>
      <small>${escapeHtml(sourceText || "rejeitado")}</small>
    </div>
    <div class="op-notes-list">
      ${rows || `<span class="op-empty">Sem notas rejeitadas pendentes.</span>`}
      ${extra}
    </div>
  `;
}

function closeNotaXmlModal() {
  $("notaXmlModal")?.setAttribute("hidden", "hidden");
}

function showNotaXmlModal(title, meta, content) {
  $("notaXmlTitle").textContent = title;
  $("notaXmlMeta").textContent = meta || "-";
  $("notaXmlContent").textContent = content || "";
  $("notaXmlModal")?.removeAttribute("hidden");
}

async function openNotaXmlModal(note) {
  const file = note?.arquivo || "";
  if (!file) {
    showNotaXmlModal("XML rejeitado", "Arquivo nao informado", "O monitor nao recebeu o nome do XML nesta coleta.");
    return;
  }
  showNotaXmlModal(`NF ${note.nota || "-"} · L-${note.loja || "-"}`, file, "Carregando XML rejeitado...");
  try {
    const data = await api(`/api/business-monitor/notas-rejeitadas/xml?file=${encodeURIComponent(file)}`);
    const meta = [
      data.file || file,
      data.mtime ? `alterado ${formatDateTime(data.mtime)}` : "",
      data.size ? `${formatNumber(data.size)} bytes` : "",
      data.truncated ? "conteudo limitado" : "",
    ].filter(Boolean).join(" · ");
    showNotaXmlModal(`NF ${note.nota || "-"} · L-${note.loja || "-"}`, meta, data.content || "Arquivo sem conteudo.");
  } catch (error) {
    showNotaXmlModal(`NF ${note.nota || "-"} · L-${note.loja || "-"}`, file, error.message);
  }
}

function closePdvQueueModal() {
  $("pdvQueueModal")?.setAttribute("hidden", "hidden");
}

function pdvQueueMetric(stage) {
  const stale = Number(stage?.pendingCount || 0);
  if (stale) return `${formatNumber(stale)} parado(s)`;
  const active = Number(stage?.count || 0);
  if (active) return `${formatNumber(active)} em andamento`;
  const pending = Number(stage?.pdvStoresPending || 0);
  if (pending) return `${formatNumber(pending)} aguardando importacao`;
  return "sem fila parada";
}

function pdvStoreChips(stores, cls, emptyText) {
  if (!stores.length) return `<span class="op-pdv-store-empty">${escapeHtml(emptyText)}</span>`;
  const visible = stores.slice(0, 6);
  const rest = stores.length - visible.length;
  return `${visible.map((item) => `<span class="op-pdv-store-chip ${cls}">L-${escapeHtml(item.store || "-")}</span>`).join("")}${rest ? `<span class="op-pdv-store-chip ${cls}">+${formatNumber(rest)}</span>` : ""}`;
}

function renderPdvQueue(data) {
  pdvQueueStages = data.stages || [];
  $("pdvQueueMeta").textContent = data.statusFileExists ? `Coleta ${formatDateTime(data.updatedAt)}` : "Sem coleta";
  $("pdvQueueCard").innerHTML = pdvQueueStages.map((stage, index) => {
    const cls = statusClass(stage.status);
    return `
      <button class="op-pdv-queue-env ${cls}" type="button" data-pdv-queue-index="${index}" title="Abrir detalhes do envio PDV">
        <strong>${escapeHtml(stage.label || stage.serverTitle || "-")}</strong>
        <span>${escapeHtml(stage.statusLabel || "-")} · ${escapeHtml(pdvQueueMetric(stage))}</span>
        <span class="op-pdv-store-counts">Atualizadas ${formatNumber(stage.pdvStoresUpdated || 0)}/${formatNumber(stage.storeTotal || 0)} · Faltam ${formatNumber(stage.pdvStoresPending || 0)}</span>
        <span class="op-pdv-store-chips">${pdvStoreChips(stage.pdvPendingStores || [], "pending", "Nenhuma loja pendente")}</span>
      </button>
    `;
  }).join("") || `<span class="op-empty">Sem coleta</span>`;
}

function detailTable(headers, rows, emptyText) {
  if (!rows.length) return `<span class="op-empty">${escapeHtml(emptyText)}</span>`;
  return `
    <table class="op-detail-table">
      <thead><tr>${headers.map((item) => `<th>${escapeHtml(item)}</th>`).join("")}</tr></thead>
      <tbody>${rows.join("")}</tbody>
    </table>
  `;
}

function showPdvQueueModal(stage) {
  if (!stage) return;
  $("pdvQueueTitle").textContent = `Envio PDV · ${stage.label || stage.serverTitle || "-"}`;
  $("pdvQueueModalMeta").textContent = [
    `Coleta ${formatDateTime(stage.actualAt)}`,
    stage.source || "",
    stage.staleMinutes ? `limite ${stage.staleMinutes} min` : "",
  ].filter(Boolean).join(" · ");
  const stoppedImports = (stage.staleImports || []).slice(0, 80).map((item) => `
    <tr>
      <td>L-${escapeHtml(item.store || "-")}</td>
      <td>${escapeHtml(item.lockAt ? formatDateTime(item.lockAt) : "-")}</td>
      <td>${escapeHtml(String(item.ageMinutes ?? "-"))} min</td>
      <td>${escapeHtml(item.summary || "-")}</td>
    </tr>
  `);
  const activeImports = (stage.imports || []).filter((item) => item.active).slice(0, 80).map((item) => `
    <tr>
      <td>L-${escapeHtml(item.store || "-")}</td>
      <td>${escapeHtml(item.lockAt ? formatDateTime(item.lockAt) : "-")}</td>
      <td>${escapeHtml(String(item.ageMinutes ?? "-"))} min</td>
      <td>${escapeHtml(item.summary || "Processando importacao.")}</td>
    </tr>
  `);
  const updatedStores = (stage.pdvUpdatedStores || []).map((item) => `
    <tr>
      <td>L-${escapeHtml(item.store || "-")}</td>
      <td>${escapeHtml(item.file || "-")}</td>
      <td>${escapeHtml(item.importedAt ? formatDateTime(item.importedAt) : "-")}</td>
    </tr>
  `);
  const pendingStores = (stage.pdvPendingStores || []).map((item) => `
    <tr>
      <td>L-${escapeHtml(item.store || "-")}</td>
      <td>${escapeHtml(item.file || "-")}</td>
      <td>${escapeHtml(item.active ? "Importando" : "Aguardando")}</td>
    </tr>
  `);
  $("pdvQueueContent").innerHTML = `
    <div class="op-pdv-queue-summary ${statusClass(stage.status)}">
      <strong>${escapeHtml(stage.statusLabel || "-")}</strong>
      <span>${escapeHtml(stage.details || "-")}</span>
    </div>
    <section>
      <h3>Em andamento</h3>
      ${detailTable(["Loja", "Inicio", "Ha", "Resumo"], activeImports, "Sem cargas em andamento.")}
    </section>
    <section>
      <h3>Lojas atualizadas (${formatNumber(stage.pdvStoresUpdated || 0)})</h3>
      ${detailTable(["Loja", "Arquivo", "Atualizada em"], updatedStores, "Nenhuma loja atualizada nesta carga.")}
    </section>
    <section>
      <h3>Lojas que faltam (${formatNumber(stage.pdvStoresPending || 0)})</h3>
      ${detailTable(["Loja", "Arquivo", "Situacao"], pendingStores, "Nenhuma loja pendente.")}
    </section>
    <section>
      <h3>Cargas paradas</h3>
      ${detailTable(["Loja", "Inicio", "Parado ha", "Resumo"], stoppedImports, "Sem cargas paradas.")}
    </section>
  `;
  $("pdvQueueModal")?.removeAttribute("hidden");
}

function renderSimpleMonitor(data, metaId, cardId) {
  const stage = (data.stages || [])[0] || {};
  $(metaId).textContent = data.statusFileExists ? `Coleta ${formatDateTime(data.updatedAt)}` : "Sem coleta";
  $(cardId).innerHTML = statusCard(stage);
}

function renderTimelineMonitor(data, metaId, timelineId) {
  $(metaId).textContent = data.statusFileExists ? `Coleta ${formatDateTime(data.updatedAt)}` : "Sem coleta";
  renderTimeline(timelineId, data.stages || []);
}

function serviceBadge(stage) {
  const cls = statusClass(stage?.status);
  const label = stage?.label || "-";
  const process = (stage?.processDetails || [])[0] || {};
  const statusText = isOk(stage) ? "" : (stage?.statusLabel || stage?.status || "-");
  const tooltip = [
    stage?.details || "",
    process.pid ? `PID ${process.pid}` : "",
    process.startedAt ? `Inicio ${formatDateTime(process.startedAt)}` : "",
    process.cpuPct !== undefined ? `CPU ${process.cpuPct}%` : "",
    process.memPct !== undefined ? `Mem ${process.memPct}%` : "",
    process.command ? `Comando: ${process.command}` : "",
  ].filter(Boolean).join(" | ");
  return `
    <span class="op-service-badge ${cls}" title="${escapeHtml(tooltip || label)}">
      <b>${escapeHtml(label)}</b>
      ${statusText ? `<small>${escapeHtml(statusText)}</small>` : ""}
    </span>
  `;
}

function serviceGroupClass(stages) {
  const items = stages || [];
  if (items.some((stage) => isBad(stage))) return "business-erro";
  if (items.some((stage) => String(stage?.status || "") === "sem_acesso")) return "business-sem-acesso";
  if (items.length && items.every((stage) => isOk(stage))) return "business-concluido";
  return "business-aguardando";
}

function renderServiceCard(data, metaId, cardId, stages) {
  $(metaId).textContent = data.statusFileExists ? `Coleta ${formatDateTime(data.updatedAt)}` : "Sem coleta";
  $(cardId).innerHTML = (stages || []).map(serviceBadge).join("") || `<span class="op-empty">Sem coleta</span>`;
}

function serviceGroup(title, stages) {
  const cls = serviceGroupClass(stages);
  return `
    <div class="op-service-group ${cls}">
      <strong>${escapeHtml(title)}</strong>
      <div>${(stages || []).map(serviceBadge).join("") || `<span class="op-empty">Sem coleta</span>`}</div>
    </div>
  `;
}

function renderServiceMonitors(sgEstoqueCusto, pdvProcesses) {
  const plenoStages = sgEstoqueCusto.stages || [];
  const pdvStages = pdvProcesses.stages || [];
  const newest = [sgEstoqueCusto.updatedAt, pdvProcesses.updatedAt].filter(Boolean).sort().pop();
  $("processServicesMeta").textContent = newest ? `Coleta ${formatDateTime(newest)}` : "Sem coleta";
  $("processServicesCard").innerHTML = [
    serviceGroup("Pleno", plenoStages),
    serviceGroup("Pré Prod PDV", pdvStages.filter((stage) => stage.serverKey === "preprod" || String(stage.id || "").startsWith("preprod_"))),
    serviceGroup("Prod PDV", pdvStages.filter((stage) => stage.serverKey === "prod" || String(stage.id || "").startsWith("prod_"))),
  ].join("");
}

async function loadAll() {
  $("pageSubtitle").textContent = "Monitoramento em tempo real das lojas";
  const [pedidos, promo, notasRejeitadas, estoque, retificacao, devolucao, mercadoriaFilial, sgEstoqueCusto, pdvProcesses, pdvQueue] = await Promise.all([
    api("/api/business-monitor/pedidos"),
    api("/api/business-monitor/promopreco"),
    api("/api/business-monitor/notas-rejeitadas"),
    api("/api/business-monitor/estoque-relex"),
    api("/api/business-monitor/retificacao-ret"),
    api("/api/business-monitor/devolucao-as400"),
    api("/api/business-monitor/mercadoria-filial"),
    api("/api/business-monitor/sg-estoque-custo"),
    api("/api/business-monitor/pdv-processes"),
    api("/api/business-monitor/pdv-queue"),
  ]);
  renderPedidos(pedidos);
  renderPromo(promo);
  renderNotasRejeitadas(notasRejeitadas);
  renderTimelineMonitor(estoque, "estoqueMeta", "estoqueCard");
  renderSimpleMonitor(retificacao, "retificacaoMeta", "retificacaoCard");
  renderTimelineMonitor(devolucao, "devolucaoMeta", "devolucaoCard");
  renderTimelineMonitor(mercadoriaFilial, "mercadoriaFilialMeta", "mercadoriaFilialCard");
  renderServiceMonitors(sgEstoqueCusto, pdvProcesses);
  renderPdvQueue(pdvQueue);
  $("pageSubtitle").textContent = `Monitoramento em tempo real das lojas · Atualizado ${formatDateTime(new Date().toISOString())}`;
}

async function refreshPedidosOnly() {
  const button = $("refreshPedidosButton");
  button?.classList.add("loading");
  button?.setAttribute("disabled", "disabled");
  try {
    $("pageSubtitle").textContent = "Reverificando pedidos...";
    const pedidos = await api("/api/business-monitor/pedidos/refresh", { method: "POST" });
    renderPedidos(pedidos);
    $("pageSubtitle").textContent = `Monitoramento em tempo real das lojas · Atualizado ${formatDateTime(new Date().toISOString())}`;
  } catch (error) {
    // Preserve the latest known timeline when a manual collection cannot reach its source.
    const pedidos = await api("/api/business-monitor/pedidos").catch(() => null);
    if (pedidos) renderPedidos(pedidos);
    $("pageSubtitle").textContent = `Reverificação sem acesso: ${error.message}`;
  } finally {
    button?.classList.remove("loading");
    button?.removeAttribute("disabled");
  }
}

$("refreshButton").addEventListener("click", () => {
  loadAll().catch((error) => {
    $("pageSubtitle").textContent = error.message;
  });
});

$("refreshPedidosButton")?.addEventListener("click", () => {
  refreshPedidosOnly().catch((error) => {
    $("pageSubtitle").textContent = error.message;
  });
});

$("notasRejeitadasCard")?.addEventListener("click", (event) => {
  const row = event.target.closest("[data-nota-index]");
  if (!row) return;
  const note = notasRejeitadasVisiveis[Number(row.dataset.notaIndex)];
  openNotaXmlModal(note);
});

$("notaXmlClose")?.addEventListener("click", closeNotaXmlModal);
$("notaXmlModal")?.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-nota-xml]")) closeNotaXmlModal();
});
$("pdvQueueCard")?.addEventListener("click", (event) => {
  const row = event.target.closest("[data-pdv-queue-index]");
  if (!row) return;
  showPdvQueueModal(pdvQueueStages[Number(row.dataset.pdvQueueIndex)]);
});
$("pdvQueueClose")?.addEventListener("click", closePdvQueueModal);
$("pdvQueueModal")?.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-pdv-queue]")) closePdvQueueModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeNotaXmlModal();
  if (event.key === "Escape") closePdvQueueModal();
});

loadAll().catch((error) => {
  $("pageSubtitle").textContent = error.message;
});

setInterval(() => {
  loadAll().catch((error) => {
    $("pageSubtitle").textContent = error.message;
  });
}, 5 * 60 * 1000);

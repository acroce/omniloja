const state = {
  runs: [],
  snapshots: [],
  selectedRun: null,
  selectedStore: "",
  selectedTab: "conciliacao_sku",
};

const tabs = [
  ["conciliacao_sku", "Estoque Final"],
  ["vendas_sku", "Vendas"],
  ["movimentos_resumo", "Resumo Mov"],
  ["notas_entrada", "Entradas NF"],
  ["notas_cd", "Notas CD"],
  ["notas_saida", "NF Saida"],
  ["notas_pendentes_entrada", "NF Pendente"],
  ["mov_causa", "Mov Causa"],
  ["autoconsumo", "Autoconsumo"],
  ["mov_sem_causa", "Sem Causa"],
  ["pedidos_transferencia", "Pedidos"],
  ["pedido_nota_divergencia", "Pedido x Nota"],
  ["retificacoes", "Retificacoes"],
  ["inventarios", "Inventario"],
  ["inventario_itens", "Itens Inventario"],
  ["divergencia_custo", "Diverg Custo"],
  ["top_movimentos", "Top Mov"],
];

const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
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

function formatMoney(value) {
  return money.format(Number(value || 0));
}

function signedClass(value) {
  const number = Number(value || 0);
  if (number < 0) return "negative";
  if (number > 0) return "positive";
  return "";
}

function storeQuery() {
  return state.selectedStore ? `?store=${encodeURIComponent(state.selectedStore)}` : "";
}

function selectedRunInfo() {
  return state.runs.find((run) => run.name === state.selectedRun) || null;
}

function availableStores(run) {
  if (Array.isArray(run?.availableStores)) return run.availableStores.map(String).filter(Boolean);
  return String(run?.stores || "")
    .split(/[-,\s]+/)
    .map((store) => store.trim())
    .filter(Boolean);
}

function renderRuns() {
  $("runList").innerHTML = state.runs.map((run) => `
    <button class="run-item ${state.selectedRun === run.name ? "active" : ""}" data-run="${run.name}">
      <strong>${run.date || run.name}</strong>
      <span>Lojas ${run.stores || "-"}${run.totals ? ` · Divergencia ${formatMoney(run.totals.divergenciaValor)}` : ""}</span>
    </button>
  `).join("");
  document.querySelectorAll("[data-run]").forEach((button) => {
    button.addEventListener("click", () => selectRun(button.dataset.run));
  });
}

function renderSnapshots() {
  $("snapshotList").innerHTML = state.snapshots.map((snapshot) => `
    <div class="snapshot-item">
      <strong>${snapshot.date} ${snapshot.label}</strong>
      <span>${snapshot.time || ""} · lojas ${snapshot.stores || "-"} · ${snapshot.rows} linhas</span>
    </div>
  `).join("") || "<div class=\"status\">Nenhum snapshot importado.</div>";
}

function kpi(label, value, sub, cls = "") {
  return `<div class="kpi"><span>${label}</span><strong class="${cls}">${value}</strong><small>${sub || ""}</small></div>`;
}

function renderStoreFilter(run) {
  const stores = availableStores(run);
  const container = $("storeFilter");
  if (!container) return;
  if (!stores.length) {
    container.innerHTML = "";
    return;
  }
  if (!state.selectedStore || !stores.includes(state.selectedStore)) {
    state.selectedStore = stores[0];
  }
  if (stores.length === 1) {
    container.innerHTML = `<span>Loja selecionada: <strong>${stores[0]}</strong></span>`;
    return;
  }
  container.innerHTML = `
    <label for="storeSelect">Loja</label>
    <select id="storeSelect">
      ${stores.map((store) => `<option value="${store}" ${store === state.selectedStore ? "selected" : ""}>${store}</option>`).join("")}
    </select>
    <span>Esta carga tem ${stores.length} lojas. Os dados abaixo estao filtrados pela loja selecionada.</span>
  `;
  $("storeSelect").addEventListener("change", async (event) => {
    state.selectedStore = event.target.value;
    await selectRun(state.selectedRun, { keepStore: true });
  });
}

function renderDivergenceExplanation(run) {
  const totals = run.totals || {};
  const explanation = run.divergenceExplanation || {};
  const qtyClosed = Boolean(explanation.quantityClosed);
  const topRows = (explanation.topCusto || []).map((row) => `
    <tr>
      <td>${row.sku}</td>
      <td>${row.descricao || ""}</td>
      <td class="num ${signedClass(row.diferenca_valor)}">${formatMoney(row.diferenca_valor)}</td>
      <td class="num">${formatNumber(row.diferenca_qtd)}</td>
      <td class="num">${formatMoney(row.custo_inicial)}</td>
      <td class="num">${formatMoney(row.custo_final)}</td>
    </tr>
  `).join("");
  const qtyRows = (explanation.topQtd || []).map((row) => `
    <tr>
      <td>${row.sku}</td>
      <td>${row.descricao || ""}</td>
      <td class="num">${formatNumber(row.qtd_final_calculado)}</td>
      <td class="num">${formatNumber(row.qtd_final_exportado)}</td>
      <td class="num ${signedClass(row.diferenca_qtd)}">${formatNumber(row.diferenca_qtd)}</td>
      <td class="num ${signedClass(row.diferenca_valor)}">${formatMoney(row.diferenca_valor)}</td>
      <td>${row.motivo || ""}</td>
    </tr>
  `).join("");

  $("divergenceExplain").innerHTML = `
    <div class="explain-head">
      <div>
        <h2>Leitura da divergencia</h2>
        <p>${explanation.message || "Sem leitura disponivel para esta carga."}</p>
      </div>
      <strong class="${qtyClosed ? "positive" : "negative"}">${explanation.status || "-"}</strong>
    </div>
    <div class="explain-grid">
      <div class="explain-card">
        <span>Saldo por quantidade</span>
        <strong class="${signedClass(totals.divergenciaQtd)}">${formatNumber(totals.divergenciaQtd)} un.</strong>
        <small>${qtyClosed ? `Fechado dentro da tolerancia de ${formatNumber(explanation.quantityTolerance)} un.` : `${formatNumber(explanation.qtdItens)} item(ns) com diferenca de quantidade.`}</small>
      </div>
      <div class="explain-card">
        <span>Saldo por valor</span>
        <strong class="${signedClass(totals.divergenciaValor)}">${formatMoney(totals.divergenciaValor)}</strong>
        <small>${formatNumber(explanation.custoItens)} item(ns) explicados por mudanca de custo.</small>
      </div>
      <div class="explain-card">
        <span>Diferenca por custo</span>
        <strong class="${signedClass(explanation.custoValor)}">${formatMoney(explanation.custoValor)}</strong>
        <small>Valor com quantidade fechada e custo diferente.</small>
      </div>
      <div class="explain-card">
        <span>Diferenca por quantidade</span>
        <strong class="${signedClass(explanation.qtdValor)}">${formatMoney(explanation.qtdValor)}</strong>
        <small>Valor ligado a item cuja quantidade ainda nao fechou.</small>
      </div>
    </div>
    <div class="cost-preview">
      <div class="cost-preview-title">Maiores diferencas por custo</div>
      <table>
        <thead>
          <tr>
            <th>SKU</th>
            <th>Descricao</th>
            <th class="num">Dif valor</th>
            <th class="num">Dif qtd</th>
            <th class="num">Custo inicial</th>
            <th class="num">Custo final</th>
          </tr>
        </thead>
        <tbody>${topRows || "<tr><td colspan=\"6\">Sem diferenca de custo relevante.</td></tr>"}</tbody>
      </table>
    </div>
    <div class="cost-preview">
      <div class="cost-preview-title">Explicacao das diferencas de quantidade</div>
      <table>
        <thead>
          <tr>
            <th>SKU</th>
            <th>Descricao</th>
            <th class="num">Qtd calc.</th>
            <th class="num">Qtd export.</th>
            <th class="num">Dif qtd</th>
            <th class="num">Dif valor</th>
            <th>Motivo</th>
          </tr>
        </thead>
        <tbody>${qtyRows || "<tr><td colspan=\"7\">Sem diferenca de quantidade relevante.</td></tr>"}</tbody>
      </table>
    </div>
  `;
}

function renderSummary(run) {
  const totals = run.totals || {};
  const stockDates = run.stockDates || {};
  const stockSources = run.stockSources || {};
  $("pageTitle").textContent = `Auditoria ${run.date || run.name}`;
  $("pageSubtitle").textContent = `Lojas ${run.stores || "-"} · estoque inicial ${stockDates.initial || "-"} · estoque final ${stockDates.final || "-"} · carga ${run.name}`;
  renderStoreFilter(run);
  $("excelButton").href = `/api/export/excel/${encodeURIComponent(run.name)}`;
  $("imageButton").href = `/api/export/summary-image/${encodeURIComponent(run.name)}${storeQuery()}`;
  $("packageButton").href = `/api/export/package/${encodeURIComponent(run.name)}`;
  $("excelButton").classList.remove("disabled");
  $("imageButton").classList.remove("disabled");
  $("packageButton").classList.remove("disabled");

  $("kpis").innerHTML = [
    kpi("Estoque inicial", formatMoney(totals.estoqueInicialValor), `${stockDates.initial || "-"} · ${formatNumber(totals.estoqueInicialQtd)} un.`),
    kpi("Movimento total", formatMoney(totals.movimentoValor), `${formatNumber(totals.movimentoQtd)} un.`, signedClass(totals.movimentoValor)),
    kpi("Estoque final calculado", formatMoney(totals.esperadoValor), `${formatNumber(totals.esperadoQtd)} un.`),
    kpi("Estoque final exportado", formatMoney(totals.finalValor), `${stockDates.final || "-"} · ${formatNumber(totals.finalQtd)} un.`),
    kpi("Divergencia", formatMoney(totals.divergenciaValor), `${formatNumber(totals.divergenciaQtd)} un.`, signedClass(totals.divergenciaValor)),
    kpi("Pedidos pendentes", formatMoney(totals.pedidosValor), `${formatNumber(totals.pedidos)} itens`, totals.pedidos ? "negative" : ""),
    kpi("Vendas cupom", formatMoney(totals.vendasValor), `${formatNumber(totals.vendasQtd)} un.`),
    kpi("Notas CD", formatMoney(totals.saidasCdValor), `${formatNumber(totals.saidasCdQtd)} un.`),
    kpi("Autoconsumo", formatMoney(totals.autoconsumoValor), `${formatNumber(totals.autoconsumoQtd)} un.`),
    kpi("Entradas NF", formatMoney(totals.entradasValor), `${formatNumber(totals.entradasQtd)} un.`),
    kpi("NF pendente", formatMoney(totals.pendentesEntradaValor), `${formatNumber(totals.pendentesEntrada)} notas`, totals.pendentesEntrada ? "negative" : ""),
    kpi("Inventarios", formatNumber(totals.inventarios), "registros no periodo", totals.inventarios ? "negative" : ""),
  ].join("");
  renderDivergenceExplanation(run);

  const originLabels = {
    NOTAS_CD: "NOTAS CD",
    ENTRADAS_NF: "ENTRADAS NF",
    DEVOLUCAO_CD: "DEVOLUCAO CD",
    NF_S: "NOTAS CD",
    NF_E: "ENTRADAS NF",
    VENDA_CUPOM: "VENDAS CUPOM",
    INVENTARIO: "INVENTARIO",
    AUTOCONSUMO: "AUTOCONSUMO",
    SEM_CAUSA: "SEM CAUSA",
  };
  const originRows = (run.origins || []).map((row) => [
    originLabels[row.origem] || row.origem,
    formatNumber(row.linhas),
    formatNumber(row.qtd_movimento),
    formatMoney(row.valor_movimento_custo),
  ]);
  if ((run.origins || []).length) {
    originRows.push([
      "TOTAL",
      formatNumber((run.origins || []).reduce((total, row) => total + Number(row.linhas || 0), 0)),
      formatNumber((run.origins || []).reduce((total, row) => total + Number(row.qtd_movimento || 0), 0)),
      formatMoney((run.origins || []).reduce((total, row) => total + Number(row.valor_movimento_custo || 0), 0)),
    ]);
  }
  $("originTable").innerHTML = tableHtml(
    ["Origem", "Linhas", "Qtd Movimento", "Valor Movimento"],
    originRows,
  );

  $("stockCheck").innerHTML = [
    ["Data estoque inicial", stockDates.initial || "-"],
    ["Data estoque final", stockDates.final || "-"],
    ["Estoque inicial", formatMoney(totals.estoqueInicialValor)],
    ["Movimentos", formatMoney(totals.movimentoValor)],
    ["Estoque esperado", formatMoney(totals.esperadoValor)],
    ["Estoque final 22:30", formatMoney(totals.finalValor)],
    ["Final - esperado", formatMoney(totals.divergenciaValor)],
    ["Fonte inicial", stockSources.initial || "-"],
    ["Fonte final", stockSources.final || "-"],
  ].map(([label, value]) => `<div class="check-row"><span>${label}</span><strong>${value}</strong></div>`).join("");
}

function pedidoNotaRowClass(row) {
  const status = String(row?.situacao || "").toUpperCase();
  if (status === "FALTOU_NA_NOTA") return "pedido-status-missing";
  if (status === "VEIO_SEM_PEDIDO" || status === "NOTA_CD_SEM_PEDIDO") return "pedido-status-extra";
  if (status === "DIVERGENCIA_QTD") return "pedido-status-different";
  if (status === "OK") return "pedido-status-ok";
  return "";
}

function tableHtml(headers, rows, rowObjects = []) {
  const isNumeric = (value) => {
    if (value === "" || value === null || value === undefined) return false;
    if (typeof value === "number") return Number.isFinite(value);
    const text = String(value).trim();
    if (!text) return false;
    if (text.includes("R$")) return true;
    const normalized = text.replace(/\./g, "").replace(",", ".");
    return /^-?\d+(\.\d+)?$/.test(normalized);
  };
  const labels = {
    valor_contagem_custo: "Valor contado",
    valor_contado_custo: "Valor contado",
    qtd_contagem: "Qtd contada",
    qtd_sistema: "Qtd sistema",
    valor_sistema_custo: "Valor sistema",
    diferenca_valor: "Dif valor",
    diferenca_qtd: "Dif qtd",
    custo_inicial: "Custo inicial",
    custo_final: "Custo final",
    valor_inicial: "Valor inicial",
    valor_movimento: "Valor movimento",
    qtd_final_calculado: "Qtd final calc.",
    valor_final_calculado: "Valor final calc.",
    qtd_final_exportado: "Qtd final exp.",
    valor_final_exportado: "Valor final exp.",
    qtd_ruptura_pedido: "Qtd ruptura",
    qtd_extra_nota: "Qtd extra nota",
    valor_ruptura_pedido: "Valor ruptura",
    valor_pedido_custo_atual: "Valor pedido",
    valor_item_nota: "Valor nota",
    qtd_nota_cd: "Qtd nota CD",
    valor_nota_cd: "Valor nota CD",
    qtd_nota_saida: "Qtd nota saida",
    valor_nota_saida: "Valor nota saida",
    diferenca_valor_custo: "Dif valor",
  };
  return `
    <thead><tr>${headers.map((header) => `<th>${labels[header] || header}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((row, index) => `<tr class="${pedidoNotaRowClass(rowObjects[index])}">${row.map((value) => `<td class="${isNumeric(value) ? "num" : ""}">${value ?? ""}</td>`).join("")}</tr>`).join("")}</tbody>
  `;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function exportSummaryImage(event) {
  if (!state.selectedRun) return;
  event.preventDefault();
  const button = $("imageButton");
  const oldText = button.textContent;
  button.textContent = "Gerando...";
  try {
    const response = await fetch(`/api/export/summary-image/${encodeURIComponent(state.selectedRun)}${storeQuery()}`);
    if (!response.ok) throw new Error(await response.text());
    const svg = await response.text();
    const svgBlob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(svgBlob);
    const image = new Image();
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = url;
    });
    const canvas = document.createElement("canvas");
    canvas.width = image.naturalWidth || 1900;
    canvas.height = image.naturalHeight || 1280;
    const context = canvas.getContext("2d");
    context.fillStyle = "#f4f7f9";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(image, 0, 0);
    URL.revokeObjectURL(url);
    const pngBlob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!pngBlob) throw new Error("Nao foi possivel gerar a imagem.");
    const storeSuffix = state.selectedStore ? `_loja_${state.selectedStore}` : "";
    downloadBlob(pngBlob, `resumo_auditoria_${state.selectedRun}${storeSuffix}.png`);
  } catch {
    window.location.href = `/api/export/summary-image/${encodeURIComponent(state.selectedRun)}${storeQuery()}`;
  } finally {
    button.textContent = oldText;
  }
}

function renderTabs() {
  $("tabs").innerHTML = tabs.map(([key, label]) => `
    <button class="${state.selectedTab === key ? "active" : ""}" data-tab="${key}">${label}</button>
  `).join("");
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedTab = button.dataset.tab;
      renderTabs();
      loadTable();
    });
  });
}

async function loadTable() {
  if (!state.selectedRun) return;
  $("detailTable").innerHTML = "";
  $("tableStatus").textContent = "Carregando...";
  const data = await api(`/api/runs/${encodeURIComponent(state.selectedRun)}/tables/${state.selectedTab}${storeQuery()}`);
  const rows = data.rows.map((row) => data.headers.map((header) => row[header]));
  $("detailTable").innerHTML = tableHtml(data.headers, rows, data.rows);
  $("tableStatus").textContent = `${data.totalRows} linha(s). Mostrando ate 1000 na tela.${data.warning ? ` ${data.warning}` : ""}`;
}

async function selectRun(runName, options = {}) {
  const changedRun = state.selectedRun !== runName;
  state.selectedRun = runName;
  if (changedRun || !options.keepStore) {
    const stores = availableStores(selectedRunInfo());
    state.selectedStore = stores[0] || "";
  }
  renderRuns();
  let run = await api(`/api/runs/${encodeURIComponent(runName)}${storeQuery()}`);
  const listRun = state.runs.find((item) => item.name === runName);
  if (listRun && Array.isArray(run.availableStores) && run.availableStores.length) {
    listRun.availableStores = run.availableStores.map(String).filter(Boolean);
  }
  const stores = availableStores(run);
  if (stores.length && (!state.selectedStore || !stores.includes(state.selectedStore))) {
    state.selectedStore = stores[0];
    run = await api(`/api/runs/${encodeURIComponent(runName)}${storeQuery()}`);
  }
  renderSummary(run);
  renderTabs();
  await loadTable();
}

async function refresh() {
  const data = await api("/api/runs");
  state.runs = data.runs || [];
  state.snapshots = data.snapshots || [];
  if (!state.selectedRun && state.runs[0]) state.selectedRun = state.runs[0].name;
  renderRuns();
  renderSnapshots();
  if (state.selectedRun) await selectRun(state.selectedRun);
}

$("fileInput").addEventListener("change", async (event) => {
  const files = [...event.target.files];
  if (!files.length) return;
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  $("uploadStatus").textContent = "Importando pacotes...";
  try {
    const result = await api("/api/import", { method: "POST", body: form });
    $("uploadStatus").textContent = `${result.imported.length} pacote(s) importado(s).`;
    await refresh();
  } catch (error) {
    $("uploadStatus").textContent = error.message;
  } finally {
    event.target.value = "";
  }
});

$("imageButton").addEventListener("click", exportSummaryImage);

refresh().catch((error) => {
  $("uploadStatus").textContent = error.message;
});

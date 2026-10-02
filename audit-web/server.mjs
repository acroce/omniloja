#!/usr/bin/env node
import { createServer } from "node:http";
import { createReadStream } from "node:fs";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import { createExportRoutes } from "./exportacoes/routes.mjs";

const exportRoutes = createExportRoutes();

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PUBLIC_DIR = path.join(ROOT, "audit-web", "public");
const OUTPUTS_DIR = path.join(ROOT, "outputs");
const TESOURARIA_COFRE_DIR = path.join(OUTPUTS_DIR, "tesouraria_cofre_inteligente");
const TESOURARIA_COFRE_DB = path.join(TESOURARIA_COFRE_DIR, "acompanhamento.sqlite");
const PREVENCAO_PERDAS_DIR = path.join(OUTPUTS_DIR, "prevencao_perdas");
const PREVENCAO_PERDAS_DB = path.join(PREVENCAO_PERDAS_DIR, "acompanhamento.sqlite");
const AUDIT_DIR = path.join(OUTPUTS_DIR, "pleno_stock_audit");
const SNAPSHOT_DIR = path.join(OUTPUTS_DIR, "pleno_stock_snapshots");
const RECEIVED_DIR = path.join(OUTPUTS_DIR, "recebidos_servidor");
const OFFICIAL_STOCK_DIR = path.join(OUTPUTS_DIR, "pleno_stock_official");
const OFFICIAL_STOCK_INDEX_DIR = path.join(OUTPUTS_DIR, "pleno_stock_official_index");
const EXCEL_DIR = path.join(OUTPUTS_DIR, "pleno_stock_audit_excel");
const CRON_MONITOR_DIR = path.join(OUTPUTS_DIR, "pleno_cron_monitor");
const CRON_STATUS_FILE = process.env.CRON_MONITOR_STATUS_FILE || path.join(CRON_MONITOR_DIR, "status.json");
const BUSINESS_MONITOR_DIR = path.join(OUTPUTS_DIR, "pleno_business_monitor");
const PEDIDOS_STATUS_FILE = process.env.PEDIDOS_MONITOR_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "pedidos.json");
const PROMOPRECO_STATUS_FILE = process.env.PROMOPRECO_MONITOR_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "promopreco.json");
const ESTOQUE_RELEX_STATUS_FILE = process.env.ESTOQUE_RELEX_MONITOR_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "estoque_relex.json");
const RETIFICACAO_RET_STATUS_FILE = process.env.RETIFICACAO_RET_MONITOR_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "retificacao_ret.json");
const NOTAS_REJEITADAS_STATUS_FILE = process.env.NOTAS_REJEITADAS_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "notas_rejeitadas.json");
const DEVOLUCAO_AS400_STATUS_FILE = process.env.DEVOLUCAO_AS400_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "devolucao_as400.json");
const MERCADORIA_FILIAL_STATUS_FILE = process.env.MERCADORIA_FILIAL_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "mercadoria_filial.json");
const SG_ESTOQUE_CUSTO_STATUS_FILE = process.env.SG_ESTOQUE_CUSTO_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "sg_estoque_custo.json");
const PDV_PROCESS_STATUS_FILE = process.env.PDV_PROCESS_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "pdv_processes.json");
const PDV_QUEUE_STATUS_FILE = process.env.PDV_QUEUE_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "pdv_queue.json");
const PDV_CONSUMO_STATUS_FILE = path.join(BUSINESS_MONITOR_DIR, "pdv_consumo.json");
const PROCESS_RESOURCES_STATUS_FILE = process.env.PROCESS_RESOURCES_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "process_resources.json");
const NOC_ALERT_POLICY_FILE = process.env.NOC_ALERT_POLICY_FILE || path.join(BUSINESS_MONITOR_DIR, "noc_alert_policy.json");
const NOC_ALERT_ACKNOWLEDGEMENTS_FILE = process.env.NOC_ALERT_ACKNOWLEDGEMENTS_FILE || path.join(BUSINESS_MONITOR_DIR, "noc_alert_acknowledgements.json");
const SAP_API_MONITOR_STATUS_FILE = process.env.SAP_API_MONITOR_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "sap_api_monitor.json");
const SAP_API_ROUTING_FILE = process.env.SAP_API_ROUTING_FILE || path.join(BUSINESS_MONITOR_DIR, "sap_api_error_routing.json");
const SAP_API_GOOGLE_CHAT_FILE = process.env.SAP_API_GOOGLE_CHAT_FILE || path.join(BUSINESS_MONITOR_DIR, "sap_api_google_chat.json");
const SAP_API_DETAIL_DIR = process.env.SAP_API_DETAIL_DIR || path.join(BUSINESS_MONITOR_DIR, "sap_api_details");
const CHECKIN_NOTAS_STATUS_FILE = process.env.CHECKIN_NOTAS_STATUS_FILE || path.join(BUSINESS_MONITOR_DIR, "checkin_notas_monitor.json");
const NODE_BIN = process.env.AUDIT_NODE_BIN || process.execPath;
const PYTHON_BIN = process.env.AUDIT_PYTHON_BIN || "python3";
const HOST = process.env.AUDIT_WEB_HOST || "127.0.0.1";
const PORT = Number(process.env.AUDIT_WEB_PORT || 8094);
const MIN_AUDIT_DATE = "2026-07-08";
const SUMMARY_QTY_TOLERANCE = 1;
const RECEIVED_SCAN_INTERVAL_MS = Number(process.env.AUDIT_RECEIVED_SCAN_INTERVAL_MS || 10 * 60 * 1000);
const RECEIVED_FILE_STABLE_MS = Number(process.env.AUDIT_RECEIVED_FILE_STABLE_MS || 60 * 1000);
const SAP_API_MONITOR_INTERVAL_MS = Number(process.env.SAP_API_MONITOR_INTERVAL_MS || 10 * 60 * 1000);
const SAP_API_MONITOR_ENABLED = process.env.SAP_API_MONITOR_ENABLED !== "0";
const SAP_API_GOOGLE_CHAT_ENABLED = process.env.SAP_API_GOOGLE_CHAT_ENABLED === "1";
const SAP_API_GOOGLE_CHAT_INTERVAL_MS = Number(process.env.SAP_API_GOOGLE_CHAT_INTERVAL_MS || 60 * 60 * 1000);
const CHECKIN_NOTAS_MONITOR_INTERVAL_MS = Number(process.env.CHECKIN_NOTAS_MONITOR_INTERVAL_MS || SAP_API_MONITOR_INTERVAL_MS);
const CHECKIN_NOTAS_MONITOR_ENABLED = process.env.CHECKIN_NOTAS_MONITOR_ENABLED !== "0";
const officialStockCache = new Map();
const officialStockRowsCache = new Map();
const officialStockDateCache = new Map();
const officialStockSelectionCache = new Map();
const receivedScanState = new Map();
const csvCache = new Map();

const nocAlertScopes = [
  { id: "pedidos", label: "Pedidos" },
  { id: "promopreco", label: "Preços e Promoções" },
  { id: "notas-rejeitadas", label: "Notas rejeitadas" },
  { id: "estoque-relex", label: "Estoque RELEX" },
  { id: "retificacao-ret", label: "Retificação RET" },
  { id: "devolucao-as400", label: "Devoluções AS400" },
  { id: "mercadoria-filial", label: "Mercadoria Filial" },
];

const nocAlertDefaults = {
  weekdays: [0, 1, 2, 3, 4, 5, 6],
  monitorStart: "00:00",
  monitorEnd: "23:59",
  okCheckIntervalSeconds: 300,
  failureCheckIntervalSeconds: 60,
  firstErrorAfterSeconds: 0,
  repeatEverySeconds: 3600,
  stopAfterSeconds: 10800,
  sendFailure: true,
  sendRecovery: true,
  recoveryRepeatEverySeconds: 0,
  progressSummaryEverySeconds: 600,
  recoverySendOnce: true,
  sendProgressSummary: false,
  recoveryOnlyWithinStopWindow: true,
};

const nocAlertScopeDefaults = {
  pedidos: { weekdays: [0, 1, 2, 3, 4, 5] },
};

const nocAlertDestinations = [
  { id: "telegram-noc-pleno", name: "Telegram NOC Pleno", type: "telegram", enabled: true, scopes: ["all"], tokenEnv: "TELEGRAM_BOT_TOKEN", chatIdsEnv: "TELEGRAM_CHAT_IDS" },
  { id: "google-chat-noc-pleno", name: "Google Chat NOC Pleno", type: "google_chat", enabled: false, scopes: ["all"], webhookEnv: "NOC_GOOGLE_CHAT_WEBHOOK", webhook: "" },
];

const cronJobs = [
  { id: "sg_fatura", label: "Fatura", schedule: "0 1 * * *", command: "/usr/share/pleno/scripts/sg_fatura.sh", group: "Pleno" },
  { id: "apagalogs", label: "Apaga logs", schedule: "10 1 * * *", command: "/usr/share/pleno/scripts/apagalogs.sh", group: "Manutencao" },
  { id: "novos_ncms", label: "Novos NCMs", schedule: "0 5 1 4 *", command: "/usr/share/pleno/scripts/novos_NCMs.sh", group: "Fiscal", graceMinutes: 180 },
  { id: "sg_curva_abc", label: "Curva ABC", schedule: "30 1 * * *", command: "/usr/share/pleno/cgi/sg_curva_abc", group: "Pleno" },
  { id: "sg_processos_fin", label: "Processos financeiros", schedule: "30 1 * * *", command: "/usr/share/pleno/cgi/sg_processos_fin -b", group: "Financeiro" },
  { id: "sg_avalia_estoques", label: "Avalia estoques", schedule: "30 2 * * *", command: "/usr/share/pleno/cgi/sg_avalia_estoques 0", group: "Estoque", graceMinutes: 120 },
  { id: "sg_mantem_ncm", label: "Mantem NCM", schedule: "20 1 * * *", command: "/usr/share/pleno/cgi/sg_mantem_ncm", group: "Fiscal" },
  { id: "sg_mantem_aliq", label: "Mantem aliquotas", schedule: "25 1 * * *", command: "/usr/share/pleno/cgi/sg_mantem_aliq", group: "Fiscal" },
  { id: "sg_avalia_venda", label: "Avalia venda", schedule: "0 3 * * *", command: "/usr/share/pleno/cgi/sg_avalia_venda", group: "Venda", graceMinutes: 120 },
  { id: "nfe_server", label: "NFe server", schedule: "0 8-18/3 * * *", command: "/servidor/nfe_server -c", group: "NFe", graceMinutes: 45 },
  { id: "importa_pleno_m", label: "Importa Pleno -m", schedule: "5 7 * * *", command: "/servpleno/importa_pleno -m", group: "Integracao", graceMinutes: 90 },
  { id: "sg_importa_tributacao_api", label: "Importa tributacao API", schedule: "15 7 * * *", command: "/usr/share/pleno/cgi/sg_importa_tributacao_api DIA", group: "Fiscal", graceMinutes: 90 },
  { id: "carga", label: "Carga", schedule: "25 7 * * *", command: "/usr/share/pleno/scripts/carga.sh", group: "Integracao", graceMinutes: 90 },
  { id: "importa_pleno_p", label: "Importa Pleno -p", schedule: "5 * * * *", command: "/servpleno/importa_pleno -p", group: "Integracao", graceMinutes: 20 },
  { id: "exporta_pedidos_ret_csv", label: "Exporta pedidos Ret CSV", schedule: "30 9 * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/integracao/Dia/exportaPedidosRetCsv.php", group: "Dia" },
  { id: "gatilho_importa_nf_transf", label: "Importa NF transferencia", schedule: "0 * * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/fiscal/ImportacaoNotafiscalTransferencia/gatilhoImportaNfTransf.php", group: "Fiscal", graceMinutes: 20 },
  { id: "exporta_devolucao_cd_csv", label: "Exporta devolucao CD", schedule: "45 17 * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/integracao/Dia/exportaDevolucaoCdCsv.php", group: "Dia" },
  { id: "exporta_estoque_csv", label: "Exporta estoque", schedule: "30 22 * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/integracao/Dia/exportaEstoqueCsv.php", group: "Dia", graceMinutes: 90 },
  { id: "exporta_retificacao_csv", label: "Exporta retificacao", schedule: "10 18 * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/integracao/Dia/exportaRetificacaoCsv.php", group: "Dia" },
  { id: "importa_retificacao_csv", label: "Importa retificacao", schedule: "0 * * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/integracao/Dia/importaRetificacaoCsv.php", group: "Dia", graceMinutes: 20 },
  { id: "inicializacao_estoque", label: "Inicializacao estoque", schedule: "30 11 * * *", command: "cd /usr/share/pleno/php && /usr/bin/php /usr/share/pleno/php/cron/integracao/Dia/inicializacaoEstoque.php", group: "Dia" },
  { id: "analisar_variacao_estoque", label: "Analisa variacao estoque", schedule: "20 1 * * *", command: "/servpleno/exportacao/processados/analisar_variacao_estoque.sh >> /servpleno/exportacao/processados/estoque_variacao.log 2>&1", group: "Estoque", graceMinutes: 120 },
];

const pedidosStages = [
  {
    id: "arquivo_original",
    label: "Arquivos originais",
    targetTime: "07:55",
    phase: "Recepcao",
    description: "Arquivos PEDIDO e PEDIDO_ITEM sem prefixo imp. devem chegar ate 07:55; se o par imp. ja existir, esta etapa tambem fica OK.",
  },
  {
    id: "arquivo_chegada",
    label: "Arquivos importados",
    targetTime: "08:10",
    phase: "Recepcao",
    description: "Arquivos imp.*.PEDIDO e imp.*.PEDIDO_ITEM do dia devem estar disponiveis ate 08:10.",
  },
  {
    id: "arquivo_vs_pleno",
    label: "Pedidos no Pleno",
    targetTime: "08:10",
    phase: "Conferencia",
    description: "Cruza os pedidos do arquivo PEDIDO com a com16_pretransferencia para confirmar a importacao.",
  },
  {
    id: "lojas_diaflex",
    label: "Fluxo Diaflex",
    targetTime: "09:30",
    phase: "Exportacao",
    description: "Consulta no Pleno as lojas acompanhadas, pendentes e exportadas pelo campo com16_dthr_exportado_trd.",
  },
  {
    id: "checagem_0805",
    label: "Consulta pedidos MySQL",
    targetTime: "08:05",
    phase: "Conferencia",
    description: "Consulta no MySQL para validar pedidos tipo 3 e resumir entradas realizadas versus pendentes.",
  },
  {
    id: "checagem_0810",
    label: "Segunda consulta MySQL",
    targetTime: "08:10",
    phase: "Conferencia",
    description: "Repeticao da consulta MySQL para confirmar o status dos pedidos tipo 3.",
  },
  {
    id: "envio_relex",
    label: "Arquivo RELEX gerado",
    targetTime: "09:30",
    phase: "Envio",
    description: "Arquivos PEDIDO_RET_YYYYMMDD0930SS.csv e PEDIDO_ITEM_RET_YYYYMMDD0930SS.csv em /servpleno/exportacao.",
  },
  {
    id: "relex_processados",
    label: "Enviado ao RELEX",
    targetTime: "09:35",
    phase: "Envio",
    description: "Arquivos RELEX movidos para processados, confirmando o envio ate 09:35.",
  },
];

const promoprecoStages = [
  {
    id: "r0430_s2_arquivos_pasta",
    batch: "Rodada 04:30",
    label: "Producao Arquivos",
    targetTime: "05:00",
    phase: "Recepcao",
    description: "Verifica arquivos de hoje em PROM e PROD no segundo servidor.",
  },
  {
    id: "r0430_s2_arquivo_importado",
    batch: "Rodada 04:30",
    label: "Producao Importado",
    targetTime: "05:05",
    phase: "Integracao",
    description: "Verifica arquivos de hoje com prefixo imp. em PROM e PROD no segundo servidor.",
  },
  {
    id: "r0430_s2_processo_carga",
    batch: "Rodada 04:30",
    label: "Producao Processo",
    targetTime: "05:00",
    phase: "Processo",
    description: "Verifica se cargas.sh, cargas2.sh, importa ou gerabd ainda estao rodando para esta rodada.",
  },
  {
    id: "r0630_s1_arquivos_pasta",
    batch: "Rodada 06:30",
    label: "Pre Producao Arquivos",
    targetTime: "07:00",
    phase: "Recepcao",
    description: "Verifica arquivos da segunda rodada em PROM e PROD.",
  },
  {
    id: "r0630_s1_arquivo_importado",
    batch: "Rodada 06:30",
    label: "Pre Producao Importado",
    targetTime: "07:05",
    phase: "Integracao",
    description: "Verifica arquivos da segunda rodada com prefixo imp. em PROM e PROD.",
  },
  {
    id: "r0630_s1_processo_carga",
    batch: "Rodada 06:30",
    label: "Pre Producao Processo",
    targetTime: "07:00",
    phase: "Processo",
    description: "Verifica se cargas.sh, cargas2.sh, importa ou gerabd ainda estao rodando para esta rodada.",
  },
  {
    id: "r0630_s2_arquivos_pasta",
    batch: "Rodada 06:30",
    label: "Producao Arquivos",
    targetTime: "07:00",
    phase: "Recepcao",
    description: "Verifica arquivos da segunda rodada em PROM e PROD no segundo servidor.",
  },
  {
    id: "r0630_s2_arquivo_importado",
    batch: "Rodada 06:30",
    label: "Producao Importado",
    targetTime: "07:05",
    phase: "Integracao",
    description: "Verifica arquivos da segunda rodada com prefixo imp. no segundo servidor.",
  },
  {
    id: "r0630_s2_processo_carga",
    batch: "Rodada 06:30",
    label: "Producao Processo",
    targetTime: "07:00",
    phase: "Processo",
    description: "Verifica se cargas.sh, cargas2.sh, importa ou gerabd ainda estao rodando para esta rodada.",
  },
];

const estoqueRelexStages = [
  {
    id: "arquivo_gerado",
    label: "Estoque gerado",
    targetTime: "22:30",
    phase: "Geracao",
    description: "Verifica se o arquivo de estoque do dia anterior foi gerado em /servpleno/exportacao.",
  },
  {
    id: "variacao_estoque",
    label: "Variacao estoque",
    targetTime: "23:30",
    phase: "Conferencia",
    description: "Compara a soma de estoque por loja com o arquivo anterior e alerta variacoes acima do limite.",
  },
  {
    id: "arquivo_consumido",
    label: "Estoque consumido",
    targetTime: "06:00",
    phase: "Consumo",
    description: "Verifica se o arquivo de estoque do dia anterior foi movido para /servpleno/exportacao/processados.",
  },
];

const retificacaoRetStages = [
  {
    id: "arquivos_pendentes",
    label: "Retificacao RET pendente",
    targetTime: "00:00",
    phase: "Importacao",
    description: "Verifica de hora em hora arquivos RETIFICACAO_RET_*.* em /servpleno/importacao. Acima de 3 arquivos gera alerta.",
  },
];

const notasRejeitadasStages = [
  {
    id: "notas_rejeitadas",
    label: "Notas rejeitadas",
    targetTime: "00:00",
    phase: "Fiscal",
    description: "Verifica de hora em hora XMLs rejeitados de CD para lojas proprias abaixo de 3000 que ainda nao entraram no Pleno.",
  },
];

const devolucaoAs400Stages = [
  {
    id: "arquivo_gerado",
    label: "Arquivo gerado",
    targetTime: "17:45",
    phase: "Envio",
    description: "Verifica se o arquivo DEVOLUCAO_CD do dia foi gerado.",
  },
  {
    id: "enviado_as400",
    label: "Enviado AS400",
    targetTime: "18:15",
    phase: "Envio",
    description: "Verifica se Luiz moveu o arquivo para enviados_devolucao/enviados_YYYYMMDD e compara com a view_dia_devolucao_cd do Pleno.",
  },
];

const mercadoriaFilialStages = [
  {
    id: "arquivo_recebido",
    label: "Mercadoria filial recebido",
    targetTime: "08:30",
    phase: "Recepcao",
    description: "Verifica se o arquivo MERCADORIA_FILIAL do dia anterior chegou em /servpleno/importacao.",
  },
  {
    id: "arquivo_consumido",
    label: "Consumido pelo Pleno",
    targetTime: "09:30",
    phase: "Consumo",
    description: "Verifica se o arquivo MERCADORIA_FILIAL foi renomeado para imp.* ou movido para processados.",
  },
];

const sgEstoqueCustoStages = [
  {
    id: "processo_ativo",
    label: "sg_estoque_custo",
    targetTime: "00:00",
    phase: "Servico",
    description: "Verifica se /usr/share/pleno/cgi/sg_estoque_custo esta ativo no servidor Pleno.",
  },
];

const pdvProcessStages = [
  { id: "preprod_pdv_server", label: "pdv_server", targetTime: "00:00", phase: "Pré Prod PDV", description: "Verifica pdv_server no S1." },
  { id: "preprod_scc", label: "scc", targetTime: "00:00", phase: "Pré Prod PDV", description: "Verifica scc no S1." },
  { id: "preprod_nfx_server", label: "nfx_server", targetTime: "00:00", phase: "Pré Prod PDV", description: "Verifica nfx_server no S1." },
  { id: "prod_pdv_server", label: "pdv_server", targetTime: "00:00", phase: "Prod PDV", description: "Verifica pdv_server no S2." },
  { id: "prod_scc", label: "scc", targetTime: "00:00", phase: "Prod PDV", description: "Verifica scc no S2." },
  { id: "prod_nfx_server", label: "nfx_server", targetTime: "00:00", phase: "Prod PDV", description: "Verifica nfx_server no S2." },
];

const pdvQueueStages = [
  { id: "preprod_pdv_queue", label: "Pré Produção", targetTime: "00:00", phase: "Envio PDV", description: "Monitora cargas de preços e promoções para PDV no S1." },
  { id: "prod_pdv_queue", label: "Produção", targetTime: "00:00", phase: "Envio PDV", description: "Monitora cargas de preços e promoções para PDV no S2." },
];

const auditTables = [
  ["conciliacao_sku", "Estoque Final", "conciliacao_sku.csv"],
  ["vendas_sku", "Vendas", "vendas_sku.csv"],
  ["movimentos_resumo", "Resumo Mov", "movimentos_resumo.csv"],
  ["notas_entrada", "Entradas NF", "notas_entrada.csv"],
  ["notas_cd", "Notas CD", "notas_cd.csv"],
  ["notas_saida", "NF Saida", "notas_saida.csv"],
  ["notas_pendentes_entrada", "NF Pendente", "notas_pendentes_entrada.csv"],
  ["mov_causa", "Mov Causa", "movimentos_estoque.csv"],
  ["autoconsumo", "Autoconsumo", "movimentos_estoque.csv"],
  ["mov_sem_causa", "Mov Sem Causa", "movimentos_estoque.csv"],
  ["pedidos_transferencia", "Pedidos", "pedidos_transferencia.csv"],
  ["pedido_nota_divergencia", "Pedido x Nota", "pedido_nota_divergencia.csv"],
  ["retificacoes", "Retificacoes", "retificacoes.csv"],
  ["inventarios", "Inventario", "inventarios.csv"],
  ["inventario_itens", "Itens Inventario", "inventario_itens.csv"],
  ["divergencia_custo", "Diverg Custo", ""],
  ["top_movimentos", "Top Mov", "top_movimentos.csv"],
];

const tableFilters = {
  notas_cd: (row) => row.origem === "NF_S" && String(row.serie || "").trim() === "1",
  notas_saida: (row) => row.origem === "NF_S" && String(row.serie || "").trim() !== "1",
  mov_causa: (row) => row.origem === "NF_S" && String(row.serie || "").trim() !== "1",
  autoconsumo: (row) =>
    (row.origem === "BOLETIM" || row.origem === "AUTOCONSUMO")
    && number(row.qtd_movimento) < 0,
  mov_sem_causa: (row) => row.origem === "SEM_CAUSA",
  inventario_itens: (row) => row.origem === "INVENTARIO",
};

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
  });
  res.end(body);
}

function safeRunName(name) {
  if (!/^[\w.-]+_lojas_[\w.-]+$/.test(name)) {
    throw new Error("Carga invalida.");
  }
  return name;
}

function parseCsv(text) {
  if (!text.trim()) return { headers: [], rows: [] };
  const lines = [];
  let row = [];
  let cell = "";
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell.replace(/\r$/, ""));
      lines.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell || row.length) {
    row.push(cell.replace(/\r$/, ""));
    lines.push(row);
  }
  const headers = lines[0] || [];
  const rows = lines.slice(1)
    .filter((items) => items.some((value) => value !== ""))
    .map((items) => Object.fromEntries(headers.map((header, idx) => [header, items[idx] ?? ""])));
  return { headers, rows };
}

async function readCsv(filePath) {
  const stat = await fs.stat(filePath).catch(() => null);
  const cacheKey = stat ? `${filePath}|${stat.size}|${Math.round(stat.mtimeMs)}` : `${filePath}|missing`;
  if (csvCache.has(cacheKey)) return csvCache.get(cacheKey);
  const text = await fs.readFile(filePath, "utf8").catch(() => "");
  const parsed = parseCsv(text);
  csvCache.set(cacheKey, parsed);
  return parsed;
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseCronField(field, min, max) {
  const values = new Set();
  for (const part of String(field).split(",")) {
    const [rangePart, stepPart] = part.split("/");
    const step = Number(stepPart || 1);
    if (!Number.isFinite(step) || step <= 0) continue;
    let start = min;
    let end = max;
    if (rangePart !== "*") {
      if (rangePart.includes("-")) {
        const [rawStart, rawEnd] = rangePart.split("-").map(Number);
        start = rawStart;
        end = rawEnd;
      } else {
        start = Number(rangePart);
        end = start;
      }
    }
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    for (let value = Math.max(min, start); value <= Math.min(max, end); value += step) {
      values.add(value);
    }
  }
  return values;
}

function cronMatcher(expression) {
  const [minute, hour, dom, month, dow] = expression.split(/\s+/);
  const minutes = parseCronField(minute, 0, 59);
  const hours = parseCronField(hour, 0, 23);
  const days = parseCronField(dom, 1, 31);
  const months = parseCronField(month, 1, 12);
  const weekdays = parseCronField(dow, 0, 7);
  return (date) => {
    const weekday = date.getDay();
    return minutes.has(date.getMinutes())
      && hours.has(date.getHours())
      && days.has(date.getDate())
      && months.has(date.getMonth() + 1)
      && (weekdays.has(weekday) || (weekday === 0 && weekdays.has(7)));
  };
}

function dateFloorMinute(date) {
  const rounded = new Date(date);
  rounded.setSeconds(0, 0);
  return rounded;
}

function isoLocal(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function scheduledTimes(job, now = new Date()) {
  const match = cronMatcher(job.schedule);
  const everyHour = /\*/.test(job.schedule.split(/\s+/)[1]) || job.schedule.split(/\s+/)[1].includes("/");
  const lookbackMinutes = everyHour ? 30 * 60 : 400 * 24 * 60;
  const cursor = dateFloorMinute(new Date(now.getTime() - lookbackMinutes * 60 * 1000));
  const end = dateFloorMinute(now);
  const times = [];
  while (cursor <= end) {
    if (match(cursor)) times.push(new Date(cursor));
    cursor.setMinutes(cursor.getMinutes() + 1);
  }
  return times;
}

function normalizeCronRuns(statusData) {
  if (Array.isArray(statusData?.runs)) {
    return Object.fromEntries(statusData.runs.map((run) => [run.id, run]));
  }
  return statusData?.runs || {};
}

function jobGraceMinutes(job) {
  if (job.graceMinutes) return job.graceMinutes;
  const [, hour] = job.schedule.split(/\s+/);
  if (hour === "*" || hour.includes("/")) return 25;
  return 90;
}

function evaluateCronJob(job, actual, statusFileExists, now = new Date()) {
  const times = scheduledTimes(job, now);
  const expected = times.at(-1) || null;
  const previous = times.at(-2) || null;
  const lastStarted = actual?.lastStartedAt ? new Date(actual.lastStartedAt) : null;
  const lastFinished = actual?.lastFinishedAt ? new Date(actual.lastFinishedAt) : null;
  const lastSeen = lastFinished || lastStarted;
  const graceMinutes = jobGraceMinutes(job);
  const dueLimit = expected ? new Date(expected.getTime() + graceMinutes * 60 * 1000) : null;
  let status = "sem_coleta";
  let statusLabel = "Sem coleta";
  let severity = 2;

  if (actual?.status === "running") {
    status = "rodando";
    statusLabel = "Rodando";
    severity = 1;
  } else if (actual?.exitCode && Number(actual.exitCode) !== 0) {
    status = "erro";
    statusLabel = "Erro";
    severity = 3;
  } else if (!statusFileExists || !actual) {
    status = "sem_coleta";
    statusLabel = "Sem coleta";
    severity = 2;
  } else if (!expected) {
    status = "aguardando";
    statusLabel = "Aguardando agenda";
    severity = 1;
  } else if (lastSeen && lastSeen >= expected) {
    status = "rodou";
    statusLabel = "Rodou";
    severity = 0;
  } else if (dueLimit && now <= dueLimit) {
    status = "aguardando";
    statusLabel = "Aguardando";
    severity = 1;
  } else {
    status = "nao_rodou";
    statusLabel = "Nao rodou";
    severity = 3;
  }

  return {
    ...job,
    expectedAt: expected ? isoLocal(expected) : "",
    previousExpectedAt: previous ? isoLocal(previous) : "",
    nextGraceLimitAt: dueLimit ? isoLocal(dueLimit) : "",
    graceMinutes,
    lastStartedAt: actual?.lastStartedAt || "",
    lastFinishedAt: actual?.lastFinishedAt || "",
    exitCode: actual?.exitCode ?? "",
    actualStatus: actual?.status || "",
    logTail: actual?.logTail || "",
    status,
    statusLabel,
    severity,
  };
}

async function cronMonitorSummary() {
  const now = new Date();
  let statusData = {};
  let statusFileExists = true;
  try {
    statusData = JSON.parse(await fs.readFile(CRON_STATUS_FILE, "utf8"));
  } catch {
    statusFileExists = false;
  }
  const runs = normalizeCronRuns(statusData);
  const jobs = cronJobs
    .map((job) => evaluateCronJob(job, runs[job.id], statusFileExists, now))
    .sort((a, b) => b.severity - a.severity || String(a.expectedAt).localeCompare(String(b.expectedAt)) || a.label.localeCompare(b.label));
  const counts = jobs.reduce((acc, job) => {
    acc[job.status] = (acc[job.status] || 0) + 1;
    return acc;
  }, {});
  return {
    updatedAt: statusData.updatedAt || "",
    collector: statusData.collector || "",
    statusFile: CRON_STATUS_FILE,
    statusFileExists,
    now: isoLocal(now),
    counts,
    jobs,
  };
}

function todayAt(timeText, now = new Date()) {
  if (!/^\d{2}:\d{2}$/.test(String(timeText || ""))) return null;
  const [hours, minutes] = timeText.split(":").map(Number);
  const date = new Date(now);
  date.setHours(hours, minutes, 0, 0);
  return date;
}

function normalizeBusinessEvents(statusData) {
  if (Array.isArray(statusData?.events)) {
    return Object.fromEntries(statusData.events.map((event) => [event.id, event]));
  }
  return statusData?.events || {};
}

function sameLocalDate(first, second) {
  return first instanceof Date
    && second instanceof Date
    && Number.isFinite(first.getTime())
    && Number.isFinite(second.getTime())
    && first.getFullYear() === second.getFullYear()
    && first.getMonth() === second.getMonth()
    && first.getDate() === second.getDate();
}

function pedidoMysqlEventOk(event) {
  return String(event?.status || "").toLowerCase() === "ok"
    && Boolean(event?.actualAt)
    && Number(event?.count || 0) > 0;
}

function evaluateBusinessStage(stage, event, statusFileExists, now = new Date(), process = "") {
  const configuredTarget = event?.targetTime || stage.targetTime;
  const expected = todayAt(configuredTarget, now);
  const actualAt = event?.actualAt ? new Date(event.actualAt) : null;
  const forcedStatus = String(event?.status || "").trim().toLowerCase();
  const tracksDeadline = process !== "notas_rejeitadas";
  const details = String(event?.details || "");
  const pendingEvidence = process === "pedidos"
    && ["envio_relex", "relex_processados"].includes(stage.id)
    && !event?.actualAt
    && /pendente|faltando/i.test(details);
  let status = "sem_coleta";
  let statusLabel = "Sem coleta";
  let severity = 2;
  const completedAfterDeadline = actualAt && expected && Number.isFinite(actualAt.getTime())
    && actualAt >= new Date(expected.getTime() + 60 * 1000);

  if (!expected) {
    status = "configurar";
    statusLabel = "Configurar horario";
    severity = 2;
  } else if (forcedStatus === "sem_acesso" || forcedStatus === "sem acesso") {
    status = "sem_acesso";
    statusLabel = "Sem acesso";
    severity = 3;
  } else if (forcedStatus === "error" || forcedStatus === "erro") {
    status = "erro";
    statusLabel = "Erro";
    severity = 3;
  } else if (["ok", "concluido", "concluido_ok"].includes(forcedStatus)) {
    const delayed = tracksDeadline && completedAfterDeadline;
    status = delayed ? "concluido_atrasado" : "concluido";
    statusLabel = delayed ? "Concluido com atraso" : "Concluido";
    severity = delayed ? 1 : 0;
  } else if (forcedStatus === "warning" || forcedStatus === "atencao") {
    status = "aguardando";
    statusLabel = "Atencao";
    severity = 1;
  } else if (forcedStatus === "running" || forcedStatus === "rodando") {
    status = "rodando";
    statusLabel = "Rodando";
    severity = 1;
  } else if (forcedStatus === "waiting" || forcedStatus === "aguardando") {
    status = "aguardando";
    statusLabel = "Aguardando";
    severity = 1;
  } else if (actualAt && Number.isFinite(actualAt.getTime())) {
    const delayed = completedAfterDeadline;
    status = delayed ? "concluido_atrasado" : "concluido";
    statusLabel = delayed ? "Concluido com atraso" : "Concluido";
    severity = delayed ? 1 : 0;
  } else if (now < expected) {
    status = "aguardando";
    statusLabel = "Aguardando";
    severity = 1;
  } else if (pendingEvidence) {
    status = "aguardando";
    statusLabel = "Aguardando";
    severity = 1;
  } else if (!statusFileExists || !event) {
    status = now > expected ? "atrasado" : "sem_coleta";
    statusLabel = now > expected ? "Atrasado" : "Sem coleta";
    severity = now > expected ? 3 : 2;
  } else if (now > expected) {
    status = "atrasado";
    statusLabel = "Atrasado";
    severity = 3;
  } else {
    status = "aguardando";
    statusLabel = "Aguardando";
    severity = 1;
  }

  return {
    ...stage,
    targetTime: configuredTarget || "",
    expectedAt: expected ? isoLocal(expected) : "",
    actualAt: event?.actualAt || "",
    source: event?.source || "",
    details: event?.details || "",
    count: event?.count ?? "",
    pendingCount: event?.pendingCount ?? "",
    importedCount: event?.importedCount ?? "",
    pendingStores: event?.pendingStores ?? [],
    lojasEsperadas: event?.lojasEsperadas ?? "",
    lojasPleno: event?.lojasPleno ?? "",
    lojasConcluidas: event?.lojasConcluidas ?? "",
    lojasNumerosEsperadas: event?.lojasNumerosEsperadas ?? [],
    lojasNumerosPleno: event?.lojasNumerosPleno ?? [],
    lojasNumerosConcluidas: event?.lojasNumerosConcluidas ?? [],
    lojasExportadas: event?.lojasExportadas ?? "",
    lojasNumerosExportadas: event?.lojasNumerosExportadas ?? [],
    itensTotal: event?.itensTotal ?? "",
    itensConfirmados: event?.itensConfirmados ?? "",
    firstExportAt: event?.firstExportAt ?? "",
    lastExportAt: event?.lastExportAt ?? "",
    storeTotal: event?.storeTotal ?? "",
    storeImported: event?.storeImported ?? "",
    pdvStoresUpdated: event?.pdvStoresUpdated ?? "",
    pdvStoresPending: event?.pdvStoresPending ?? "",
    pdvUpdatedStores: event?.pdvUpdatedStores ?? [],
    pdvPendingStores: event?.pdvPendingStores ?? [],
    storePending: event?.storePending ?? "",
    folderStats: event?.folderStats ?? [],
    firstFileTime: event?.firstFileTime ?? "",
    lastFileTime: event?.lastFileTime ?? "",
    lastImportedAt: event?.lastImportedAt ?? "",
    cycleStartedAt: event?.cycleStartedAt ?? "",
    cycleFinishedAt: event?.cycleFinishedAt ?? "",
    cycleFrozenAt: event?.cycleFrozenAt ?? "",
    cycleFrozen: event?.cycleFrozen ?? false,
    processRunning: event?.processRunning ?? false,
    processDetails: event?.processDetails ?? [],
    processStartTime: event?.processStartTime ?? "",
    files: event?.files ?? [],
    imports: event?.imports ?? [],
    uploads: event?.uploads ?? [],
    staleImports: event?.staleImports ?? [],
    staleUploads: event?.staleUploads ?? [],
    fileTotal: event?.fileTotal ?? "",
    importTotal: event?.importTotal ?? "",
    uploadTotal: event?.uploadTotal ?? "",
    staleMinutes: event?.staleMinutes ?? "",
    maxUploadAgeMinutes: event?.maxUploadAgeMinutes ?? "",
    maxImportAgeMinutes: event?.maxImportAgeMinutes ?? "",
    upgradeDir: event?.upgradeDir ?? "",
    retagDir: event?.retagDir ?? "",
    maxFiles: event?.maxFiles ?? "",
    pattern: event?.pattern ?? "",
    variationCount: event?.variationCount ?? "",
    variationStores: event?.variationStores ?? [],
    variationThresholdPercent: event?.variationThresholdPercent ?? "",
    notes: event?.notes ?? [],
    checkedXmls: event?.checkedXmls ?? "",
    candidateXmls: event?.candidateXmls ?? "",
    lookbackHours: event?.lookbackHours ?? "",
    fileCount: event?.fileCount ?? "",
    plenoCount: event?.plenoCount ?? "",
    missingInFile: event?.missingInFile ?? "",
    extraInFile: event?.extraInFile ?? "",
    missingSamples: event?.missingSamples ?? [],
    extraSamples: event?.extraSamples ?? [],
    expectedCount: event?.expectedCount ?? "",
    missingFiles: event?.missingFiles ?? [],
    status,
    statusLabel,
    severity,
  };
}

async function businessMonitorSummary({ process, title, statusFile, stages }) {
  const now = new Date();
  let statusData = {};
  let statusFileExists = true;
  try {
    statusData = JSON.parse(await fs.readFile(statusFile, "utf8"));
  } catch {
    statusFileExists = false;
  }
  let events = normalizeBusinessEvents(statusData);
  let notice = "";
  const collectedAt = statusData.updatedAt ? new Date(statusData.updatedAt) : null;
  const collectedToday = sameLocalDate(collectedAt, now);
  if (!collectedToday) {
    events = {};
    notice = statusData.updatedAt
      ? `Coleta antiga (${isoLocal(collectedAt)}); aguardando nova execucao da crontab de hoje.`
      : "Sem coleta de hoje; aguardando execucao da crontab.";
  }
  if (process === "pedidos") {
    if (now.getDay() === 0) {
      notice = "Domingo sem pedidos RELEX para as lojas; monitoramento de pedidos sem agenda hoje.";
      const evaluatedStages = stages.map((stage) => ({
        ...stage,
        expectedAt: "",
        actualAt: "",
        source: "",
        details: "Domingo sem pedidos RELEX para as lojas.",
        count: "",
        pendingCount: "",
        importedCount: "",
        pendingStores: [],
        status: "sem_coleta",
        statusLabel: "Sem agenda",
        severity: 0,
      }));
      return {
        process,
        title,
        date: isoLocal(now).slice(0, 10),
        now: isoLocal(now),
        updatedAt: statusData.updatedAt || "",
        collector: statusData.collector || "",
        notice,
        noSchedule: true,
        statusFile,
        statusFileExists,
        counts: { sem_coleta: evaluatedStages.length },
        stages: evaluatedStages,
      };
    }
    const processStart = todayAt("07:50", now);
    const collectedBeforeStart = !collectedAt || !Number.isFinite(collectedAt.getTime()) || (processStart && collectedAt < processStart);
    if (processStart && (now < processStart || collectedBeforeStart)) {
      events = {};
      notice = now < processStart
        ? "Aguardando inicio dos processos de pedidos as 07:50."
        : "Coleta anterior ao inicio; aguardando nova execucao da crontab apos 07:50.";
    }
    if (pedidoMysqlEventOk(events.checagem_0810) && !pedidoMysqlEventOk(events.checagem_0805)) {
      events.checagem_0805 = {
        ...events.checagem_0810,
        targetTime: "08:05",
        actualAt: events.checagem_0810.actualAt,
        details: `Consulta 08:05 validada pela segunda consulta das 08:10. ${events.checagem_0810.details || ""}`.trim(),
      };
    }
  }
  const evaluatedStages = stages.map((stage) => evaluateBusinessStage(stage, events[stage.id], statusFileExists, now, process));
  const counts = evaluatedStages.reduce((acc, stage) => {
    acc[stage.status] = (acc[stage.status] || 0) + 1;
    return acc;
  }, {});
  return {
    process,
    title,
    date: isoLocal(now).slice(0, 10),
    now: isoLocal(now),
    updatedAt: statusData.updatedAt || "",
    collector: statusData.collector || "",
    notice,
    statusFile,
    statusFileExists,
    counts,
    stages: evaluatedStages,
  };
}

async function pedidosBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "pedidos",
    title: "Monitor Pedidos",
    statusFile: PEDIDOS_STATUS_FILE,
    stages: pedidosStages,
  });
}

async function promoprecoBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "promopreco",
    title: "Monitor Promocao e Precos",
    statusFile: PROMOPRECO_STATUS_FILE,
    stages: promoprecoStages,
  });
}

async function estoqueRelexBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "estoque_relex",
    title: "Monitor Estoque RELEX",
    statusFile: ESTOQUE_RELEX_STATUS_FILE,
    stages: estoqueRelexStages,
  });
}

async function retificacaoRetBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "retificacao_ret",
    title: "Monitor Retificacao RET",
    statusFile: RETIFICACAO_RET_STATUS_FILE,
    stages: retificacaoRetStages,
  });
}

async function notasRejeitadasBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "notas_rejeitadas",
    title: "Monitor Notas Rejeitadas",
    statusFile: NOTAS_REJEITADAS_STATUS_FILE,
    stages: notasRejeitadasStages,
  });
}

async function devolucaoAs400BusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "devolucao_as400",
    title: "Monitor Devolucao AS400",
    statusFile: DEVOLUCAO_AS400_STATUS_FILE,
    stages: devolucaoAs400Stages,
  });
}

async function mercadoriaFilialBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "mercadoria_filial",
    title: "Monitor Mercadoria Filial",
    statusFile: MERCADORIA_FILIAL_STATUS_FILE,
    stages: mercadoriaFilialStages,
  });
}

async function sgEstoqueCustoBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "sg_estoque_custo",
    title: "Monitor sg_estoque_custo",
    statusFile: SG_ESTOQUE_CUSTO_STATUS_FILE,
    stages: sgEstoqueCustoStages,
  });
}

async function pdvProcessBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "pdv_processes",
    title: "Monitor Processos PDV",
    statusFile: PDV_PROCESS_STATUS_FILE,
    stages: pdvProcessStages,
  });
}

async function pdvQueueBusinessMonitorSummary() {
  return businessMonitorSummary({
    process: "pdv_queue",
    title: "Monitor Envio PDV",
    statusFile: PDV_QUEUE_STATUS_FILE,
    stages: pdvQueueStages,
  });
}

function pdvConsumptionStatus(value) {
  const normalized = String(value || "aguardando").toLowerCase();
  if (["ok", "concluido", "completed", "complete"].includes(normalized)) return "atencao";
  if (["error", "erro", "timeout", "failed", "fail"].includes(normalized)) return "erro";
  if (["warning", "atencao", "atrasado", "late"].includes(normalized)) return "atencao";
  return "aguardando";
}

function pdvEstimatedMinutes(row) {
  if (row?.estimateMinutes != null && row.estimateMinutes !== "" && Number.isFinite(Number(row.estimateMinutes))) return Math.max(0, Math.ceil(Number(row.estimateMinutes)));
  const progress = row?.progress || {};
  const expected = Number(progress.bytesExpected ?? progress.totalBytes ?? 0);
  const completed = Number(progress.bytesCompleted ?? progress.completedBytes ?? 0);
  const rate = Number(progress.bytesPerSecond ?? progress.rateBytesPerSecond ?? 0);
  return expected > completed && rate > 0 ? Math.ceil((expected - completed) / rate / 60) : null;
}

function pdvConsumptionRows(snapshot) {
  return (Array.isArray(snapshot.rows) ? snapshot.rows : []).map((row) => ({
    store: row.store || row.loja || "-",
    code: row.environment || row.service || row.ambiente || "PDV",
    name: row.name || row.process || "Consumo ARIUS",
    status: pdvConsumptionStatus(row.status || row.state),
    statusLabel: row.label || row.state || "Sem confirmação",
    lastSentAt: row.publishedAt || row.sourceAt || row.lastSentAt || "",
    checkedAt: row.completedAt || row.consumedAt || row.checkedAt || "",
    consumptionCount: row.fileCount ?? row.consumptionCount ?? "",
    packageStatus: row.packageStatus || "",
    deliveryId: row.deliveryId || "",
    detail: row.detail || row.error || "",
    estimateMinutes: pdvEstimatedMinutes(row),
    warningCount: row.warningCount ?? 0,
    startedAt: row.startedAt || "",
    stale: Boolean(row.stale),
  }));
}

async function pdvConsumoBusinessMonitorSummary() {
  let payload;
  let fileUpdatedAt = "";
  try {
    [payload, fileUpdatedAt] = await Promise.all([
      fs.readFile(PDV_CONSUMO_STATUS_FILE, "utf8").then(JSON.parse),
      fs.stat(PDV_CONSUMO_STATUS_FILE).then((stat) => stat.mtime.toISOString()),
    ]);
  } catch {
    return {
      available: false,
      status: "sem_coleta",
      message: "Aguardando a coleta oficial dos servidores PDV/ARIUS.",
      generatedAt: "",
      rows: [],
      counts: {},
    };
  }
  const snapshot = payload?.data && typeof payload.data === "object" ? payload.data : payload;
  const rows = pdvConsumptionRows(snapshot);
  const counts = rows.reduce((total, row) => {
    total[row.status] = (total[row.status] || 0) + 1;
    return total;
  }, {});
  return {
    available: true,
    status: payload?.collection?.status || "ok",
    message: payload?.collection?.error || payload?.error || "",
    generatedAt: snapshot.generatedAt || payload?.lastSuccessAt || fileUpdatedAt,
    lastAttemptAt: payload?.lastAttemptAt || "",
    version: snapshot.version || "",
    rows,
    counts,
    fileRows: Array.isArray(snapshot.fileRows) ? snapshot.fileRows : [],
    areas: Array.isArray(snapshot.areas) ? snapshot.areas : [],
    rounds: Array.isArray(snapshot.rounds) ? snapshot.rounds : [],
    notice: snapshot.notice || "",
    comparisonLabel: snapshot.comparisonLabel || "Conteúdo igual ao original ARIUS",
    fileErrors: Array.isArray(snapshot.fileErrors) ? snapshot.fileErrors : [],
  };
}

async function processResourcesMonitorSummary() {
  let statusData = {};
  let statusFileExists = true;
  try {
    statusData = JSON.parse(await fs.readFile(PROCESS_RESOURCES_STATUS_FILE, "utf8"));
  } catch {
    statusFileExists = false;
  }
  const servers = statusData.servers || [];
  const counts = servers.reduce((acc, server) => {
    const status = server.status || "sem_coleta";
    acc[status] = (acc[status] || 0) + 1;
    return acc;
  }, {});
  return {
    process: "process-resources",
    title: "Monitor Recursos dos Processos",
    now: isoLocal(new Date()),
    updatedAt: statusData.updatedAt || "",
    collector: statusData.collector || "",
    statusFile: PROCESS_RESOURCES_STATUS_FILE,
    statusFileExists,
    counts,
    servers,
  };
}

async function sapApiMonitorSummary() {
  let statusData = {};
  let statusFileExists = true;
  try {
    statusData = JSON.parse(await fs.readFile(SAP_API_MONITOR_STATUS_FILE, "utf8"));
  } catch {
    statusFileExists = false;
  }
  const latest = statusData.latest || {};
  const transactions = Array.isArray(latest.transactions) ? latest.transactions : [];
  const totals = latest.totals || { events: 0, monitoredEvents: 0, success: 0, errors: 0, ignored: 0, other: 0, successRate: 0, errorRate: 0, ignoredRate: 0 };
  const history = Array.isArray(statusData.history) ? statusData.history : [];
  const worstTransactions = [...transactions]
    .sort((a, b) => (b.errors || 0) - (a.errors || 0))
    .slice(0, 5);
  const busiestTransactions = [...transactions]
    .sort((a, b) => (b.events || 0) - (a.events || 0))
    .slice(0, 5);
  return {
    process: "sap-api",
    title: "Monitor APIs SAP",
    now: isoLocal(new Date()),
    updatedAt: statusData.updatedAt || "",
    collector: statusData.collector || "",
    statusFile: SAP_API_MONITOR_STATUS_FILE,
    statusFileExists,
    windowMinutes: statusData.windowMinutes || latest.windowMinutes || 10,
    historyLimit: statusData.historyLimit || 0,
    aggregateHistoryLimit: statusData.aggregateHistoryLimit || 0,
    latest,
    totals,
    transactions,
    worstTransactions,
    busiestTransactions,
    history,
    aggregates: statusData.aggregates || {},
    triage: statusData.triage || { occurrences: [], departments: [], reasons: [] },
  };
}

async function requestJson(req) {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 250_000) throw new Error("Corpo da requisicao muito grande.");
  }
  try {
    return JSON.parse(raw || "{}");
  } catch {
    throw new Error("Dados invalidos.");
  }
}

function alertSeconds(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, Math.round(parsed)) : fallback;
}

function alertTime(value, fallback) {
  return /^([01]\d|2[0-3]):[0-5]\d$/.test(String(value || "")) ? String(value) : fallback;
}

function alertWeekdays(value, fallback) {
  const days = Array.isArray(value) ? value : fallback;
  const normalized = [...new Set(days.map(Number).filter((day) => Number.isInteger(day) && day >= 0 && day <= 6))].sort((a, b) => a - b);
  return normalized.length ? normalized : fallback;
}

function normalizeNocAlertPolicy(raw = {}, { includeWebhooks = false } = {}) {
  const allowedScopeIds = new Set(nocAlertScopes.map((item) => item.id));
  const defaults = { ...nocAlertDefaults, ...(raw.defaults || {}) };
  defaults.weekdays = alertWeekdays(defaults.weekdays, nocAlertDefaults.weekdays);
  for (const key of ["okCheckIntervalSeconds", "failureCheckIntervalSeconds", "firstErrorAfterSeconds", "repeatEverySeconds", "stopAfterSeconds", "recoveryRepeatEverySeconds", "progressSummaryEverySeconds"]) {
    defaults[key] = alertSeconds(defaults[key], nocAlertDefaults[key]);
  }
  for (const key of ["monitorStart", "monitorEnd"]) defaults[key] = alertTime(defaults[key], nocAlertDefaults[key]);
  for (const key of ["sendFailure", "sendRecovery", "recoverySendOnce", "sendProgressSummary", "recoveryOnlyWithinStopWindow"]) {
    defaults[key] = defaults[key] !== false;
  }

  const scopes = {};
  for (const scope of nocAlertScopes) {
    const rawRule = (raw.scopes || {})[scope.id];
    const inherited = nocAlertScopeDefaults[scope.id] || {};
    const rule = { ...inherited, ...(rawRule && typeof rawRule === "object" ? rawRule : {}) };
    if (!rawRule && !Object.keys(inherited).length) continue;
    scopes[scope.id] = {};
    scopes[scope.id].weekdays = alertWeekdays(rule.weekdays, defaults.weekdays);
    for (const key of ["okCheckIntervalSeconds", "failureCheckIntervalSeconds", "firstErrorAfterSeconds", "repeatEverySeconds", "stopAfterSeconds", "recoveryRepeatEverySeconds", "progressSummaryEverySeconds"]) {
      if (rule[key] !== undefined && rule[key] !== "") scopes[scope.id][key] = alertSeconds(rule[key], defaults[key]);
    }
    for (const key of ["monitorStart", "monitorEnd"]) {
      if (rule[key] !== undefined && rule[key] !== "") scopes[scope.id][key] = alertTime(rule[key], defaults[key]);
    }
    for (const key of ["sendFailure", "sendRecovery", "recoverySendOnce", "sendProgressSummary", "recoveryOnlyWithinStopWindow"]) {
      if (typeof rule[key] === "boolean") scopes[scope.id][key] = rule[key];
    }
  }

  const storedDestinations = Array.isArray(raw.destinations) && raw.destinations.length ? raw.destinations : nocAlertDestinations;
  const destinations = storedDestinations.map((item, index) => {
    const type = item.type === "google_chat" ? "google_chat" : "telegram";
    const fallbackName = item.id === "google-chat-noc-pleno"
      ? "Google Chat NOC Pleno"
      : (type === "google_chat" ? `Google Chat ${index + 1}` : "Telegram NOC Pleno");
    const scopesForDestination = Array.isArray(item.scopes)
      ? item.scopes.filter((scope) => scope === "all" || allowedScopeIds.has(scope))
      : ["all"];
    const normalized = {
      id: String(item.id || `${type}-${index + 1}`),
      name: String(item.name || fallbackName).slice(0, 80),
      type,
      enabled: item.enabled !== false,
      scopes: scopesForDestination.length ? scopesForDestination : ["all"],
      tokenEnv: String(item.tokenEnv || "TELEGRAM_BOT_TOKEN"),
      chatIdsEnv: String(item.chatIdsEnv || "TELEGRAM_CHAT_IDS"),
      webhookEnv: String(item.webhookEnv || "NOC_GOOGLE_CHAT_WEBHOOK"),
      webhookConfigured: Boolean(item.webhook),
    };
    if (includeWebhooks && type === "google_chat") normalized.webhook = String(item.webhook || "");
    return normalized;
  });
  return { updatedAt: raw.updatedAt || "", defaults, scopes, destinations, availableScopes: nocAlertScopes };
}

async function nocAlertPolicyConfig({ includeWebhooks = false } = {}) {
  try {
    const raw = JSON.parse(await fs.readFile(NOC_ALERT_POLICY_FILE, "utf8"));
    return normalizeNocAlertPolicy(raw, { includeWebhooks });
  } catch {
    return normalizeNocAlertPolicy({}, { includeWebhooks });
  }
}

async function saveNocAlertPolicy(req) {
  const payload = await requestJson(req);
  const current = await nocAlertPolicyConfig({ includeWebhooks: true });
  const existing = new Map(current.destinations.map((item) => [item.id, item]));
  const raw = {
    updatedAt: isoLocal(new Date()),
    defaults: payload.defaults || current.defaults,
    scopes: payload.scopes || current.scopes,
    destinations: (Array.isArray(payload.destinations) ? payload.destinations : current.destinations).map((item, index) => {
      const previous = existing.get(String(item.id || ""));
      const type = item.type === "google_chat" ? "google_chat" : "telegram";
      const fallbackName = item.id === "google-chat-noc-pleno"
        ? "Google Chat NOC Pleno"
        : (type === "google_chat" ? `Google Chat ${index + 1}` : "Telegram NOC Pleno");
      const webhook = String(item.webhook || "").trim();
      if (webhook && !/^https:\/\/chat\.googleapis\.com\//i.test(webhook)) throw new Error("O webhook do Google Chat deve iniciar com https://chat.googleapis.com/.");
      return {
        id: String(item.id || `${type}-${index + 1}`),
        name: String(item.name || previous?.name || fallbackName).trim().slice(0, 80),
        type,
        enabled: item.enabled !== false,
        scopes: Array.isArray(item.scopes) ? item.scopes : ["all"],
        tokenEnv: String(item.tokenEnv || previous?.tokenEnv || "TELEGRAM_BOT_TOKEN"),
        chatIdsEnv: String(item.chatIdsEnv || previous?.chatIdsEnv || "TELEGRAM_CHAT_IDS"),
        webhookEnv: String(item.webhookEnv || previous?.webhookEnv || "NOC_GOOGLE_CHAT_WEBHOOK"),
        webhook: webhook || previous?.webhook || "",
      };
    }),
  };
  const normalized = normalizeNocAlertPolicy(raw, { includeWebhooks: true });
  const stored = {
    updatedAt: raw.updatedAt,
    defaults: normalized.defaults,
    scopes: normalized.scopes,
    destinations: normalized.destinations.map((item) => ({
      id: item.id,
      name: item.name,
      type: item.type,
      enabled: item.enabled,
      scopes: item.scopes,
      tokenEnv: item.tokenEnv,
      chatIdsEnv: item.chatIdsEnv,
      webhookEnv: item.webhookEnv,
      webhook: item.webhook || "",
    })),
  };
  await fs.mkdir(path.dirname(NOC_ALERT_POLICY_FILE), { recursive: true });
  await fs.writeFile(`${NOC_ALERT_POLICY_FILE}.tmp`, `${JSON.stringify(stored, null, 2)}\n`, "utf8");
  await fs.rename(`${NOC_ALERT_POLICY_FILE}.tmp`, NOC_ALERT_POLICY_FILE);
  return nocAlertPolicyConfig();
}

function normalizeNocAlertAcknowledgements(raw = {}) {
  const allowedScopeIds = new Set(nocAlertScopes.map((item) => item.id));
  const scopes = {};
  for (const [scope, value] of Object.entries(raw.scopes || {})) {
    if (!allowedScopeIds.has(scope) || !value || typeof value !== "object") continue;
    const mutedUntil = new Date(String(value.mutedUntil || ""));
    if (Number.isNaN(mutedUntil.getTime()) || mutedUntil <= new Date()) continue;
    scopes[scope] = {
      acknowledgedAt: String(value.acknowledgedAt || ""),
      mutedUntil: mutedUntil.toISOString(),
    };
  }
  return { updatedAt: String(raw.updatedAt || ""), scopes };
}

async function nocAlertAcknowledgements() {
  try {
    const raw = JSON.parse(await fs.readFile(NOC_ALERT_ACKNOWLEDGEMENTS_FILE, "utf8"));
    return normalizeNocAlertAcknowledgements(raw);
  } catch {
    return { updatedAt: "", scopes: {} };
  }
}

async function saveNocAlertAcknowledgement(req) {
  const payload = await requestJson(req);
  const scope = String(payload.scope || "");
  if (!nocAlertScopes.some((item) => item.id === scope)) throw new Error("Processo de alerta inválido.");

  const current = await nocAlertAcknowledgements();
  if (payload.resume === true) {
    delete current.scopes[scope];
  } else {
    const durationSeconds = Math.round(Number(payload.durationSeconds || 0));
    if (!Number.isFinite(durationSeconds) || durationSeconds < 60 || durationSeconds > 24 * 60 * 60) {
      throw new Error("O período de silêncio deve ficar entre 1 minuto e 24 horas.");
    }
    const now = new Date();
    current.scopes[scope] = {
      acknowledgedAt: now.toISOString(),
      mutedUntil: new Date(now.getTime() + durationSeconds * 1000).toISOString(),
    };
  }
  const stored = { updatedAt: isoLocal(new Date()), scopes: current.scopes };
  await fs.mkdir(path.dirname(NOC_ALERT_ACKNOWLEDGEMENTS_FILE), { recursive: true });
  await fs.writeFile(`${NOC_ALERT_ACKNOWLEDGEMENTS_FILE}.tmp`, `${JSON.stringify(stored, null, 2)}\n`, "utf8");
  await fs.rename(`${NOC_ALERT_ACKNOWLEDGEMENTS_FILE}.tmp`, NOC_ALERT_ACKNOWLEDGEMENTS_FILE);
  return nocAlertAcknowledgements();
}

async function sapApiRoutingRules() {
  try {
    const data = JSON.parse(await fs.readFile(SAP_API_ROUTING_FILE, "utf8"));
    return { updatedAt: data.updatedAt || "", rules: Array.isArray(data.rules) ? data.rules : [] };
  } catch {
    return { updatedAt: "", rules: [] };
  }
}

async function sapApiGoogleChatConfig({ includeWebhooks = false } = {}) {
  try {
    const data = JSON.parse(await fs.readFile(SAP_API_GOOGLE_CHAT_FILE, "utf8"));
    const channels = Array.isArray(data.channels) ? data.channels : [];
    return {
      updatedAt: data.updatedAt || "",
      enabled: SAP_API_GOOGLE_CHAT_ENABLED,
      intervalMinutes: Math.round(SAP_API_GOOGLE_CHAT_INTERVAL_MS / 60000),
      channels: channels.map((channel) => includeWebhooks ? channel : ({
        id: channel.id,
        department: channel.department,
        enabled: channel.enabled !== false,
        webhookConfigured: Boolean(channel.webhook),
        lastSentAt: channel.lastSentAt || "",
      })),
    };
  } catch {
    return { updatedAt: "", enabled: SAP_API_GOOGLE_CHAT_ENABLED, intervalMinutes: Math.round(SAP_API_GOOGLE_CHAT_INTERVAL_MS / 60000), channels: [] };
  }
}

async function saveSapApiGoogleChatConfig(req) {
  const payload = await requestJson(req);
  const current = await sapApiGoogleChatConfig({ includeWebhooks: true });
  let channels = current.channels;
  if (payload.action === "delete") {
    channels = channels.filter((channel) => channel.id !== String(payload.id || ""));
  } else {
    const department = String(payload.department || "").trim();
    const webhook = String(payload.webhook || "").trim();
    const requestedId = String(payload.id || "");
    const previousById = requestedId ? channels.find((item) => item.id === requestedId) : null;
    if (!department || (!webhook && !previousById)) throw new Error("Informe o departamento e o webhook do Google Chat.");
    if (webhook && !/^https:\/\/chat\.googleapis\.com\//i.test(webhook)) throw new Error("O webhook deve iniciar com https://chat.googleapis.com/.");
    const previous = previousById || channels.find((item) => item.department === department);
    const channel = {
      id: String(requestedId || previous?.id || `chat-${Date.now()}`),
      department,
      webhook: webhook || previous?.webhook || "",
      enabled: true,
      lastSentAt: previous?.lastSentAt || "",
    };
    // Um departamento tem um destino principal. Cadastre novamente o mesmo
    // nome para trocar o webhook sem duplicar os envios horarios.
    channels = [...channels.filter((item) => item.department !== department && item.id !== channel.id), channel];
    if (previousById && previousById.department !== department) {
      try {
        const routing = JSON.parse(await fs.readFile(SAP_API_ROUTING_FILE, "utf8"));
        routing.rules = (routing.rules || []).map((rule) => rule.department === previousById.department ? { ...rule, department } : rule);
        routing.updatedAt = isoLocal(new Date());
        await fs.writeFile(`${SAP_API_ROUTING_FILE}.tmp`, `${JSON.stringify(routing, null, 2)}\n`, "utf8");
        await fs.rename(`${SAP_API_ROUTING_FILE}.tmp`, SAP_API_ROUTING_FILE);
      } catch {
        // O departamento pode ainda nao ter regras de erro vinculadas.
      }
      try {
        const status = JSON.parse(await fs.readFile(SAP_API_MONITOR_STATUS_FILE, "utf8"));
        for (const occurrence of status.triage?.occurrences || []) {
          if (occurrence.department === previousById.department) occurrence.department = department;
        }
        await fs.writeFile(`${SAP_API_MONITOR_STATUS_FILE}.tmp`, `${JSON.stringify(status, null, 2)}\n`, "utf8");
        await fs.rename(`${SAP_API_MONITOR_STATUS_FILE}.tmp`, SAP_API_MONITOR_STATUS_FILE);
      } catch {
        // A primeira coleta ainda nao criou o arquivo de ocorrencias.
      }
    }
  }
  const stored = { updatedAt: isoLocal(new Date()), channels };
  await fs.mkdir(path.dirname(SAP_API_GOOGLE_CHAT_FILE), { recursive: true });
  await fs.writeFile(`${SAP_API_GOOGLE_CHAT_FILE}.tmp`, `${JSON.stringify(stored, null, 2)}\n`, "utf8");
  await fs.rename(`${SAP_API_GOOGLE_CHAT_FILE}.tmp`, SAP_API_GOOGLE_CHAT_FILE);
  return sapApiGoogleChatConfig();
}

async function sendSapApiGoogleChatMemo(req) {
  const payload = await requestJson(req);
  const department = String(payload.department || "").trim();
  const text = String(payload.text || "").trim();
  if (!department || !text) throw new Error("Informe o departamento e gere o memo antes de enviar.");
  const config = await sapApiGoogleChatConfig({ includeWebhooks: true });
  const channels = config.channels.filter((channel) => channel.enabled !== false && channel.department === department && channel.webhook);
  if (!channels.length) throw new Error(`Nenhum webhook Google Chat cadastrado para ${department}.`);
  for (const channel of channels) {
    const response = await fetch(channel.webhook, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ text: text.slice(0, 3800) }),
    });
    if (!response.ok) throw new Error(`Google Chat respondeu HTTP ${response.status}.`);
    channel.lastSentAt = isoLocal(new Date());
  }
  await fs.writeFile(`${SAP_API_GOOGLE_CHAT_FILE}.tmp`, `${JSON.stringify({ updatedAt: isoLocal(new Date()), channels: config.channels }, null, 2)}\n`, "utf8");
  await fs.rename(`${SAP_API_GOOGLE_CHAT_FILE}.tmp`, SAP_API_GOOGLE_CHAT_FILE);
  return { sent: channels.length, department };
}

function occurrenceBelongsToDepartment(occurrence, department, rules) {
  const candidates = (rules || []).filter((rule) => String(rule.department || "").trim() === department);
  return candidates.some((rule) => occurrenceMatchesRule(occurrence, rule))
    || (!candidates.length && String(occurrence.department || "") === department);
}

function googleChatErrorMemo(department, occurrences, from, until) {
  const totals = new Map();
  for (const occurrence of occurrences) totals.set(occurrence.reason || "Sem motivo", (totals.get(occurrence.reason || "Sem motivo") || 0) + 1);
  const lines = [
    `Monitor SAP - erros para ${department}`,
    `Periodo: ${isoLocal(from)} ate ${isoLocal(until)}`,
    `Ocorrencias novas: ${occurrences.length}`,
    "",
    "Resumo por erro:",
    ...[...totals.entries()].sort((a, b) => b[1] - a[1]).map(([reason, count]) => `- ${reason}: ${count}`),
    "",
    "Referencias:",
    ...occurrences.slice(0, 30).map((item) => `- ${item.transaction || item.transactionId}: ${item.reason}${item.store ? ` | loja ${item.store}` : ""}${item.note ? ` | NF/doc ${item.note}` : ""}${item.material ? ` | produto ${item.material}` : ""}`),
  ];
  const text = lines.join("\n");
  return text.length > 3800 ? `${text.slice(0, 3750)}\n... lista cortada; consulte o monitor para o restante.` : text;
}

let sapApiGoogleChatRunning = false;
async function runSapApiGoogleChatDispatch() {
  if (!SAP_API_GOOGLE_CHAT_ENABLED || sapApiGoogleChatRunning) return;
  sapApiGoogleChatRunning = true;
  try {
    const [config, routing, status] = await Promise.all([
      sapApiGoogleChatConfig({ includeWebhooks: true }),
      sapApiRoutingRules(),
      fs.readFile(SAP_API_MONITOR_STATUS_FILE, "utf8").then(JSON.parse),
    ]);
    const until = new Date();
    let changed = false;
    for (const channel of config.channels.filter((item) => item.enabled !== false && item.webhook)) {
      const from = channel.lastSentAt ? new Date(channel.lastSentAt) : new Date(until.getTime() - SAP_API_GOOGLE_CHAT_INTERVAL_MS);
      const occurrences = (status.triage?.occurrences || []).filter((item) => {
        const at = new Date(item.occurrenceAt).getTime();
        return Number.isFinite(at) && at > from.getTime() && at <= until.getTime() && occurrenceBelongsToDepartment(item, channel.department, routing.rules);
      });
      if (!occurrences.length) {
        console.log(`Google Chat: nenhum erro novo para ${channel.department}.`);
        continue;
      }
      const response = await fetch(channel.webhook, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: googleChatErrorMemo(channel.department, occurrences, from, until) }) });
      if (!response.ok) throw new Error(`Google Chat respondeu HTTP ${response.status} para ${channel.department}.`);
      channel.lastSentAt = isoLocal(until);
      changed = true;
      console.log(`Google Chat: ${occurrences.length} erro(s) enviados para ${channel.department}.`);
    }
    if (changed) {
      await fs.writeFile(`${SAP_API_GOOGLE_CHAT_FILE}.tmp`, `${JSON.stringify({ updatedAt: isoLocal(until), channels: config.channels }, null, 2)}\n`, "utf8");
      await fs.rename(`${SAP_API_GOOGLE_CHAT_FILE}.tmp`, SAP_API_GOOGLE_CHAT_FILE);
    }
  } catch (error) {
    console.error("Envio horario Google Chat falhou:", error.message);
  } finally {
    sapApiGoogleChatRunning = false;
  }
}

function startSapApiGoogleChatDispatch() {
  if (!SAP_API_GOOGLE_CHAT_ENABLED) {
    console.log("Envio Google Chat desabilitado por SAP_API_GOOGLE_CHAT_ENABLED=0.");
    return;
  }
  // Faz a primeira verificacao imediatamente apos iniciar o container. Assim
  // um restart nao deixa os departamentos aguardando uma hora inteira.
  runSapApiGoogleChatDispatch();
  setInterval(runSapApiGoogleChatDispatch, SAP_API_GOOGLE_CHAT_INTERVAL_MS);
  console.log(`Envio Google Chat ativo a cada ${Math.round(SAP_API_GOOGLE_CHAT_INTERVAL_MS / 60000)} minuto(s).`);
}

function occurrenceMatchesRule(occurrence, rule) {
  const pattern = String(rule.pattern || "").trim().toLocaleLowerCase("pt-BR");
  if (!pattern) return false;
  const context = [
    occurrence.reason, occurrence.sapCode, occurrence.sapMessage, occurrence.returnReason,
    occurrence.transaction, occurrence.transactionId, occurrence.raw,
  ].join("\n").toLocaleLowerCase("pt-BR");
  return context.includes(pattern);
}

async function saveSapApiRouting(req) {
  const payload = await requestJson(req);
  const current = await sapApiRoutingRules();
  let rules = current.rules;
  if (payload.action === "delete") {
    rules = rules.filter((rule) => rule.id !== String(payload.id || ""));
  } else {
    const pattern = String(payload.pattern || "").trim();
    const department = String(payload.department || "").trim();
    const recommendedAction = String(payload.recommendedAction || "").trim();
    if (!pattern || !department) throw new Error("Informe o trecho do erro e o departamento responsavel.");
    const rule = {
      id: String(payload.id || `regra-${Date.now()}`),
      pattern,
      department,
      recommendedAction,
      enabled: true,
      updatedAt: isoLocal(new Date()),
    };
    rules = [...rules.filter((item) => item.id !== rule.id), rule];
  }
  const result = { updatedAt: isoLocal(new Date()), rules };
  await fs.mkdir(path.dirname(SAP_API_ROUTING_FILE), { recursive: true });
  await fs.writeFile(`${SAP_API_ROUTING_FILE}.tmp`, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  await fs.rename(`${SAP_API_ROUTING_FILE}.tmp`, SAP_API_ROUTING_FILE);

  // Atualiza a tela imediatamente; o coletor tambem reaplicara estas regras
  // em todas as coletas futuras.
  try {
    const status = JSON.parse(await fs.readFile(SAP_API_MONITOR_STATUS_FILE, "utf8"));
    const occurrences = status.triage?.occurrences || [];
    for (const occurrence of occurrences) {
      const rule = [...rules].reverse().find((item) => occurrenceMatchesRule(occurrence, item));
      if (!rule) continue;
      occurrence.department = rule.department;
      occurrence.area = "Regra cadastrada";
      occurrence.recommendedAction = rule.recommendedAction || "Encaminhar para a area responsavel";
    }
    const counts = new Map();
    for (const occurrence of occurrences) counts.set(occurrence.department || "Triagem TI / Integracoes", (counts.get(occurrence.department || "Triagem TI / Integracoes") || 0) + 1);
    const reasonCounts = new Map();
    for (const occurrence of occurrences) {
      const department = occurrence.department || "Triagem TI / Integracoes";
      const reason = occurrence.reason || "Pendente de classificacao - verificar retorno";
      const key = `${department}\u0000${reason}`;
      reasonCounts.set(key, (reasonCounts.get(key) || 0) + 1);
    }
    status.triage = status.triage || {};
    status.triage.updatedAt = result.updatedAt;
    status.triage.occurrences = occurrences;
    status.triage.departments = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([department, occurrences]) => ({ department, occurrences }));
    status.triage.reasons = [...reasonCounts.entries()]
      .map(([key, occurrences]) => {
        const [department, reason] = key.split("\u0000");
        return { department, reason, occurrences };
      })
      .sort((a, b) => b.occurrences - a.occurrences || a.reason.localeCompare(b.reason, "pt-BR"));
    await fs.writeFile(`${SAP_API_MONITOR_STATUS_FILE}.tmp`, `${JSON.stringify(status, null, 2)}\n`, "utf8");
    await fs.rename(`${SAP_API_MONITOR_STATUS_FILE}.tmp`, SAP_API_MONITOR_STATUS_FILE);
  } catch {
    // A regra permanece salva mesmo antes da primeira coleta do monitor.
  }
  return result;
}

async function sapApiTransactionDetails(searchParams) {
  const transactionId = String(searchParams.get("transactionId") || "").trim();
  const requestedMinutes = Number(searchParams.get("minutes") || 10);
  const minutes = Math.max(1, Math.min(Number.isFinite(requestedMinutes) ? Math.round(requestedMinutes) : 10, 24 * 60));
  const start = String(searchParams.get("start") || "").trim();
  const end = String(searchParams.get("end") || "").trim();
  if (!transactionId) throw new Error("Informe a transacao.");
  const script = path.join(ROOT, "scripts", "update_sap_api_monitor.py");
  const args = [
    script,
    "--detail-transaction",
    transactionId,
    "--window-minutes",
    String(minutes),
    "--details-limit",
    "2000",
    "--detail-dir",
    SAP_API_DETAIL_DIR,
  ];
  if (start && end) args.push("--start", start, "--end", end);
  const result = await runCommand(PYTHON_BIN, args, {
    env: {
      ...process.env,
      SAP_API_DETAIL_DIR,
    },
  });
  const raw = result.stdout.trim();
  if (!raw) throw new Error(result.stderr.trim() || "Consulta sem retorno.");
  return JSON.parse(raw.split(/\r?\n/).at(-1));
}

async function sapApiManualErrorSearch(searchParams) {
  const store = String(searchParams.get("store") || "").trim();
  const reason = String(searchParams.get("reason") || "").trim();
  const approximateAt = String(searchParams.get("approximateAt") || "").trim();
  const requestedMinutes = Number(searchParams.get("minutes") || 120);
  const minutes = Math.max(10, Math.min(Number.isFinite(requestedMinutes) ? Math.round(requestedMinutes) : 120, 24 * 60));
  if (!store) throw new Error("Informe a loja.");
  if (!/^\d{1,6}$/.test(store)) throw new Error("A loja deve conter apenas numeros.");
  if (!reason) throw new Error("Informe o motivo ou parte do erro retornado pelo SAP.");
  const script = path.join(ROOT, "scripts", "update_sap_api_monitor.py");
  const args = [
    script,
    "--manual-store",
    store,
    "--manual-reason",
    reason,
    "--manual-at",
    approximateAt,
    "--manual-window-minutes",
    String(minutes),
    "--detail-dir",
    SAP_API_DETAIL_DIR,
  ];
  const result = await runCommand(PYTHON_BIN, args, {
    env: {
      ...process.env,
      SAP_API_DETAIL_DIR,
    },
  });
  const raw = result.stdout.trim();
  if (!raw) throw new Error(result.stderr.trim() || "Consulta sem retorno.");
  return JSON.parse(raw.split(/\r?\n/).at(-1));
}

async function checkinNotasMonitorSummary() {
  let statusData = {};
  let statusFileExists = true;
  try {
    statusData = JSON.parse(await fs.readFile(CHECKIN_NOTAS_STATUS_FILE, "utf8"));
  } catch {
    statusFileExists = false;
  }
  return {
    process: "checkin-notas",
    title: "Notas CD 704 para check-in",
    now: isoLocal(new Date()),
    updatedAt: statusData.updatedAt || "",
    collector: statusData.collector || "",
    statusFile: CHECKIN_NOTAS_STATUS_FILE,
    statusFileExists,
    startDate: statusData.startDate || "",
    configuredStartDate: statusData.configuredStartDate || "",
    endDate: statusData.endDate || "",
    originStore: statusData.originStore || "",
    source: statusData.source || "",
    totals: statusData.totals || { total: 0, comCheckin: 0, semCheckin: 0, doneRate: 0, pendingRate: 0 },
    summary: statusData.summary || [],
    byDay: statusData.byDay || [],
    history: statusData.history || [],
    last24HoursHistory: statusData.last24HoursHistory || statusData.history || [],
    pendingStores: statusData.pendingStores || [],
    pendingNotes: statusData.pendingNotes || [],
  };
}

function isoDateOnly(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(value || "")) ? String(value) : "";
}

function parseStoreList(value) {
  return String(value || "")
    .split(",")
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0);
}

async function inventarioContagemMonitorSummary(searchParams) {
  const today = isoLocal(new Date()).slice(0, 10);
  let startDate = isoDateOnly(searchParams.get("startDate")) || today;
  let endDate = isoDateOnly(searchParams.get("endDate")) || startDate;
  if (startDate > endDate) {
    [startDate, endDate] = [endDate, startDate];
  }
  const stores = parseStoreList(searchParams.get("lojas"));
  const onlyActive = searchParams.get("active") !== "0";
  const script = path.join(ROOT, "scripts", "query_inventario_contagem_monitor.py");
  const args = [script, "--start-date", startDate, "--end-date", endDate];
  if (stores.length) args.push("--lojas", stores.join(","));
  if (!onlyActive) args.push("--include-inactive");
  const result = await runCommand(PYTHON_BIN, args, { env: { ...process.env } });
  return JSON.parse(result.stdout);
}

async function notaRejeitadaXml(searchParams) {
  const file = String(searchParams.get("file") || "").trim();
  if (!file) throw new Error("Informe o arquivo XML.");
  if (file !== path.basename(file) || file.includes("..") || !file.toLowerCase().endsWith(".xml")) {
    throw new Error("Arquivo XML invalido.");
  }
  const script = path.join(ROOT, "scripts", "fetch_nota_rejeitada_xml.py");
  const result = await runCommand(PYTHON_BIN, [script, "--file", file], { env: { ...process.env } });
  const raw = result.stdout.trim();
  if (!raw) throw new Error(result.stderr.trim() || "Consulta sem retorno.");
  return JSON.parse(raw.split(/\r?\n/).at(-1));
}

function sum(rows, field) {
  return rows.reduce((total, row) => total + number(row[field]), 0);
}

function sumAbs(rows, field) {
  return rows.reduce((total, row) => total + Math.abs(number(row[field])), 0);
}

function operationalOrigin(row) {
  if (row.origem === "NF_S" && String(row.serie || "").trim() === "1") return "NOTAS_CD";
  if (row.origem === "NF_S") return "DEVOLUCAO_CD";
  if (row.origem === "NF_E") return "ENTRADAS_NF";
  if (row.origem === "VENDA_CUPOM") return "VENDA_CUPOM";
  if (row.origem === "INVENTARIO") return "INVENTARIO";
  if (row.origem === "BOLETIM" || row.origem === "AUTOCONSUMO") return "AUTOCONSUMO";
  if (row.origem === "AUTOCONSUMO_ENTRADA") return "AUTOCONSUMO_ENTRADA";
  return row.origem || "SEM_CAUSA";
}

function operationalSignedMovement(row) {
  const origin = operationalOrigin(row);
  const rawQtd = number(row.qtd_movimento);
  const rawValor = number(row.valor_movimento_custo);
  if (origin === "NOTAS_CD" || origin === "ENTRADAS_NF") {
    return { qtd: Math.abs(rawQtd), valor: Math.abs(rawValor) };
  }
  if (["DEVOLUCAO_CD", "VENDA_CUPOM", "AUTOCONSUMO", "AUTOCONSUMO_ENTRADA"].includes(origin)) {
    return { qtd: -Math.abs(rawQtd), valor: -Math.abs(rawValor) };
  }
  return { qtd: rawQtd, valor: rawValor };
}

function normalizeMovementSummary(rows) {
  const groups = new Map();
  for (const row of rows) {
    const origem = operationalOrigin(row);
    if (origem === "AUTOCONSUMO_ENTRADA") continue;
    const key = [row.loja || "", row.nome_loja || "", row.data_movimento || "", origem].join("|");
    const signed = operationalSignedMovement(row);
    const current = groups.get(key) || {
      loja: row.loja || "",
      nome_loja: row.nome_loja || "",
      data_movimento: row.data_movimento || "",
      origem,
      linhas: 0,
      qtd_movimento: 0,
      valor_movimento_custo: 0,
    };
    current.linhas += 1;
    current.qtd_movimento += signed.qtd;
    current.valor_movimento_custo += signed.valor;
    groups.set(key, current);
  }
  const order = ["AUTOCONSUMO", "INVENTARIO", "NOTAS_CD", "ENTRADAS_NF", "DEVOLUCAO_CD", "VENDA_CUPOM", "SEM_CAUSA"];
  return [...groups.values()]
    .map((group) => ({
      ...group,
      linhas: String(group.linhas),
      qtd_movimento: String(Number(group.qtd_movimento.toFixed(3))),
      valor_movimento_custo: String(money(group.valor_movimento_custo)),
    }))
    .sort((a, b) => {
      const aIdx = order.indexOf(a.origem);
      const bIdx = order.indexOf(b.origem);
      return (aIdx < 0 ? 999 : aIdx) - (bIdx < 0 ? 999 : bIdx) || a.origem.localeCompare(b.origem);
    });
}

function notaSaidaRowsFromMovements(rows) {
  return rows.filter(tableFilters.notas_saida).map((row) => ({
    loja: row.loja,
    nome_loja: row.nome_loja,
    data_movimento: row.data_movimento,
    nota: row.nota,
    serie: row.serie,
    entrada_saida: row.nota_entrada_saida || "S",
    sku: row.sku,
    descricao: row.descricao,
    qtd_nota_saida: Math.abs(number(row.qtd_movimento)).toFixed(3),
    valor_nota_saida: Math.abs(number(row.valor_movimento_custo)).toFixed(2),
    movimento_id: row.movimento_id,
    devolucao_codigos: row.devolucao_codigos,
    devolucao_causa_codigos: row.devolucao_causa_codigos,
    devolucao_causas: row.devolucao_causas,
    retificacao_ids: row.retificacao_ids,
    retificacao_albarans: row.retificacao_albarans,
  }));
}

function inventorySummaryFromMovements(rows) {
  const groups = new Map();
  for (const row of rows.filter(tableFilters.inventario_itens)) {
    const key = [row.loja || "", row.nome_loja || "", row.inventario_id || "", row.data_movimento || ""].join("|");
    const current = groups.get(key) || {
      loja: row.loja || "",
      nome_loja: row.nome_loja || "",
      inventario_id: row.inventario_id || "",
      descricao_inventario: row.inventario_id ? `Inventario ${row.inventario_id}` : "Inventario",
      data_inventario: row.data_movimento || "",
      inicio: "",
      fim: row.data_movimento || "",
      fechado: "1",
      cancelado: "0",
      itens: 0,
      qtd_sistema: "",
      valor_sistema_custo: "",
      qtd_contagem: "",
      valor_contagem_custo: "",
      diferenca_qtd: 0,
      diferenca_valor_custo: 0,
    };
    current.itens += 1;
    current.diferenca_qtd += number(row.qtd_movimento);
    current.diferenca_valor_custo += number(row.valor_movimento_custo);
    groups.set(key, current);
  }
  return [...groups.values()].map((row) => ({
    ...row,
    itens: String(row.itens),
    diferenca_qtd: String(Number(row.diferenca_qtd.toFixed(3))),
    diferenca_valor_custo: String(money(row.diferenca_valor_custo)),
  }));
}

function normalizeAutoconsumoSummary(rows, autoconsumoRows) {
  const normalized = rows.filter((row) => !["BOLETIM", "AUTOCONSUMO", "AUTOCONSUMO_ENTRADA"].includes(row.origem));
  const groups = new Map();
  for (const row of autoconsumoRows) {
    const key = [row.loja || "", row.nome_loja || "", row.data_movimento || ""].join("|");
    const current = groups.get(key) || {
      loja: row.loja || "",
      nome_loja: row.nome_loja || "",
      data_movimento: row.data_movimento || "",
      origem: "AUTOCONSUMO",
      linhas: 0,
      qtd_movimento: 0,
      valor_movimento_custo: 0,
    };
    current.linhas += 1;
    current.qtd_movimento += Math.abs(number(row.qtd_movimento));
    current.valor_movimento_custo += Math.abs(number(row.valor_movimento_custo));
    groups.set(key, current);
  }
  for (const group of groups.values()) {
    normalized.unshift({
      ...group,
      linhas: String(group.linhas),
      qtd_movimento: String(Number((-group.qtd_movimento).toFixed(3))),
      valor_movimento_custo: String(money(-group.valor_movimento_custo)),
    });
  }
  return normalized.map((row) => {
    const qtd = number(row.qtd_movimento);
    const valor = number(row.valor_movimento_custo);
    if (row.origem === "NF_S") {
      return {
        ...row,
        qtd_movimento: String(Number(Math.abs(qtd).toFixed(3))),
        valor_movimento_custo: String(money(Math.abs(valor))),
      };
    }
    if (row.origem === "NF_E" || row.origem === "VENDA_CUPOM") {
      return {
        ...row,
        qtd_movimento: String(Number((-Math.abs(qtd)).toFixed(3))),
        valor_movimento_custo: String(money(-Math.abs(valor))),
      };
    }
    return row;
  });
}

function money(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

async function readManifest(runDir) {
  const manifestPath = path.join(runDir, "manifest.json");
  const text = await fs.readFile(manifestPath, "utf8").catch(() => "{}");
  try {
    return JSON.parse(text);
  } catch {
    return {};
  }
}

function parseAuditRunName(name) {
  const match = name.match(/^(\d{4}-\d{2}-\d{2})_lojas_(.+)$/);
  const stores = match?.[2] === "todas" ? "todas" : match?.[2]?.replaceAll("-", ", ") || "";
  return { date: match?.[1] || "", stores };
}

function previousDate(dateText) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateText || "")) return "";
  const date = new Date(`${dateText}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

function previousAuditRunName(runName) {
  const match = runName.match(/^(\d{4}-\d{2}-\d{2})_lojas_(.+)$/);
  if (!match) return "";
  const previous = previousDate(match[1]);
  return previous ? `${previous}_lojas_${match[2]}` : "";
}

function stockExportDate(dateText) {
  return (dateText || "").replaceAll("-", "");
}

function storesFromRunName(runName) {
  const stores = runName.match(/^(\d{4}-\d{2}-\d{2})_lojas_(.+)$/)?.[2] || "";
  if (stores === "todas") return new Set();
  return new Set(stores.split("-").map((store) => store.trim()).filter(Boolean));
}

function storeListFromRunName(runName) {
  return [...storesFromRunName(runName)].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b));
}

function storeListFromRows(...rowGroups) {
  const stores = new Set();
  for (const rows of rowGroups) {
    for (const row of rows || []) {
      const loja = String(row.loja || "").trim();
      if (loja) stores.add(loja);
    }
  }
  return [...stores].sort((a, b) => Number(a) - Number(b) || a.localeCompare(b));
}

async function availableStoresForRun(runName) {
  const storesFromName = storeListFromRunName(runName);
  if (storesFromName.length) return storesFromName;

  const runDir = path.join(AUDIT_DIR, safeRunName(runName));
  const lojaCsv = await readCsv(path.join(runDir, "estoque_diario_loja.csv"));
  return storeListFromRows(lojaCsv.rows);
}

function selectedStoresFromRunName(runName, store = "") {
  const stores = storesFromRunName(runName);
  const selected = String(store || "").trim();
  if (!selected || selected === "all") return stores;
  if (!/^[\w.-]+$/.test(selected) || (stores.size && !stores.has(selected))) {
    throw new Error("Loja invalida para esta carga.");
  }
  return new Set([selected]);
}

function filterRowsByStore(rows, store = "") {
  const selected = String(store || "").trim();
  if (!selected || selected === "all") return rows;
  return rows.filter((row) => String(row.loja || "").trim() === selected);
}

async function findOfficialStockFile(dateText) {
  const prefix = `estoque_${stockExportDate(dateText)}`;
  const candidates = [];
  for (const dir of [OFFICIAL_STOCK_DIR, RECEIVED_DIR]) {
    const entries = await fs.readdir(dir).catch(() => []);
    for (const name of entries) {
      if (name.startsWith(prefix) && name.toLowerCase().endsWith(".csv")) {
        const filePath = path.join(dir, name);
        const stat = await fs.stat(filePath).catch(() => null);
        candidates.push({ name, filePath, mtimeMs: stat?.mtimeMs || 0 });
      }
    }
  }
  return candidates
    .sort((a, b) => a.name.localeCompare(b.name) || a.mtimeMs - b.mtimeMs)
    .at(-1)?.filePath || "";
}

async function findOfficialStockIndexFile(dateText, store) {
  if (!dateText || !store) return "";
  const prefix = `estoque_${stockExportDate(dateText)}`;
  const suffix = `_loja_${store}.json`;
  const entries = await fs.readdir(OFFICIAL_STOCK_INDEX_DIR).catch(() => []);
  return entries
    .filter((name) => name.startsWith(prefix) && name.endsWith(suffix))
    .sort((a, b) => a.localeCompare(b))
    .at(-1) || "";
}

async function readOfficialStockIndex(indexPath, dateText, fallbackFile = "") {
  const indexed = await fs.readFile(indexPath, "utf8")
    .then((text) => JSON.parse(text))
    .catch(() => null);
  if (!indexed) return null;
  return {
    date: dateText,
    file: indexed.file || fallbackFile || path.basename(indexPath).replace(/_loja_[^_]+\.json$/, ".csv"),
    linhas: number(indexed.linhas),
    qtd: number(indexed.qtd),
    valor: number(indexed.valor),
    rows: new Map((indexed.rows || []).map((row) => [
      String(row[0]),
      { sku: String(row[0]), qtd: number(row[1]), valor: number(row[2]) },
    ])),
  };
}

async function readOfficialStockIndexes(dateText, indexNames) {
  const rows = new Map();
  let linhas = 0;
  let qtd = 0;
  let valor = 0;
  let file = "";

  for (const indexName of indexNames) {
    const indexed = await readOfficialStockIndex(path.join(OFFICIAL_STOCK_INDEX_DIR, indexName), dateText);
    if (!indexed) continue;
    file ||= indexed.file;
    linhas += indexed.linhas;
    qtd += indexed.qtd;
    valor += indexed.valor;
    for (const [sku, row] of indexed.rows.entries()) {
      const current = rows.get(sku) || { sku, qtd: 0, valor: 0 };
      current.qtd += number(row.qtd);
      current.valor += number(row.valor);
      rows.set(sku, current);
    }
  }

  if (!indexNames.length || !file) return null;
  return { date: dateText, file, linhas, qtd, valor, rows };
}

async function readOfficialStockDate(dateText) {
  if (!dateText) return null;
  if (officialStockDateCache.has(dateText)) return officialStockDateCache.get(dateText);

  const filePath = await findOfficialStockFile(dateText);
  if (!filePath) {
    officialStockDateCache.set(dateText, null);
    return null;
  }

  const stream = createReadStream(filePath, { encoding: "utf8" });
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  let headers = [];
  let lojaIdx = -1;
  let skuIdx = -1;
  let qtdIdx = -1;
  let valorIdx = -1;
  const byStore = new Map();

  for await (const line of rl) {
    if (!line.trim()) continue;
    const items = line.split(";");
    if (!headers.length) {
      headers = items;
      lojaIdx = headers.indexOf("nro_loja");
      skuIdx = headers.indexOf("codigo_interno");
      qtdIdx = headers.indexOf("qtd_estoque");
      valorIdx = headers.indexOf("valor_estoque");
      continue;
    }
    if (lojaIdx < 0 || skuIdx < 0 || qtdIdx < 0 || valorIdx < 0) continue;
    const loja = items[lojaIdx] || "";
    const sku = items[skuIdx] || "";
    if (!loja || !sku) continue;
    const qtdLinha = number(items[qtdIdx]);
    const valorLinha = number(items[valorIdx]);
    if (!byStore.has(loja)) {
      byStore.set(loja, { qtd: 0, valor: 0, linhas: 0, rows: new Map() });
    }
    const storeData = byStore.get(loja);
    storeData.linhas += 1;
    storeData.qtd += qtdLinha;
    storeData.valor += valorLinha;
    const item = storeData.rows.get(sku) || { sku, qtd: 0, valor: 0 };
    item.qtd += qtdLinha;
    item.valor += valorLinha;
    storeData.rows.set(sku, item);
  }

  const stock = { date: dateText, file: path.basename(filePath), byStore };
  officialStockDateCache.set(dateText, stock);
  return stock;
}

async function readOfficialStockSelection(dateText, runName, store = "") {
  if (!dateText) return null;
  const stores = selectedStoresFromRunName(runName, store);
  const cacheKey = `${dateText}|${[...stores].sort().join("-")}|selection`;
  if (officialStockSelectionCache.has(cacheKey)) return officialStockSelectionCache.get(cacheKey);

  const singleStore = stores.size === 1 ? [...stores][0] : "";
  const filePath = await findOfficialStockFile(dateText);
  if (!filePath && singleStore) {
    const indexedName = await findOfficialStockIndexFile(dateText, singleStore);
    if (indexedName) {
      const indexed = await readOfficialStockIndex(path.join(OFFICIAL_STOCK_INDEX_DIR, indexedName), dateText);
      if (indexed) {
        officialStockSelectionCache.set(cacheKey, indexed);
        return indexed;
      }
    }
  }
  if (!filePath && !singleStore) {
    const prefix = `estoque_${stockExportDate(dateText)}`;
    const indexedNames = (await fs.readdir(OFFICIAL_STOCK_INDEX_DIR).catch(() => []))
      .filter((name) => name.startsWith(prefix) && /_loja_[^/]+\.json$/.test(name))
      .sort((a, b) => a.localeCompare(b));
    const indexed = await readOfficialStockIndexes(dateText, indexedNames);
    if (indexed) {
      officialStockSelectionCache.set(cacheKey, indexed);
      return indexed;
    }
  }
  if (!filePath) {
    officialStockSelectionCache.set(cacheKey, null);
    return null;
  }

  const indexPath = singleStore
    ? path.join(OFFICIAL_STOCK_INDEX_DIR, `${path.basename(filePath, ".csv")}_loja_${singleStore}.json`)
    : "";
  if (indexPath) {
    const indexed = await readOfficialStockIndex(indexPath, dateText, path.basename(filePath));
    if (indexed) {
      officialStockSelectionCache.set(cacheKey, indexed);
      return indexed;
    }
  }

  const stream = createReadStream(filePath, { encoding: "utf8" });
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  let headers = [];
  let lojaIdx = -1;
  let skuIdx = -1;
  let qtdIdx = -1;
  let valorIdx = -1;
  let linhas = 0;
  let qtd = 0;
  let valor = 0;
  const rows = new Map();

  for await (const line of rl) {
    if (!line.trim()) continue;
    const items = line.split(";");
    if (!headers.length) {
      headers = items;
      lojaIdx = headers.indexOf("nro_loja");
      skuIdx = headers.indexOf("codigo_interno");
      qtdIdx = headers.indexOf("qtd_estoque");
      valorIdx = headers.indexOf("valor_estoque");
      continue;
    }
    if (lojaIdx < 0 || skuIdx < 0 || qtdIdx < 0 || valorIdx < 0) continue;
    const loja = items[lojaIdx] || "";
    const sku = items[skuIdx] || "";
    if (!sku || (stores.size && !stores.has(loja))) continue;
    const qtdLinha = number(items[qtdIdx]);
    const valorLinha = number(items[valorIdx]);
    linhas += 1;
    qtd += qtdLinha;
    valor += valorLinha;
    const current = rows.get(sku) || { sku, qtd: 0, valor: 0 };
    current.qtd += qtdLinha;
    current.valor += valorLinha;
    rows.set(sku, current);
  }

  const selection = { date: dateText, file: path.basename(filePath), linhas, qtd, valor, rows };
  if (indexPath) {
    await fs.mkdir(OFFICIAL_STOCK_INDEX_DIR, { recursive: true }).catch(() => {});
    const payload = JSON.stringify({
      date: dateText,
      file: path.basename(filePath),
      loja: singleStore,
      linhas,
      qtd,
      valor,
      rows: [...rows.values()].map((row) => [row.sku, row.qtd, row.valor]),
    });
    await fs.writeFile(`${indexPath}.tmp`, payload).then(() => fs.rename(`${indexPath}.tmp`, indexPath)).catch(() => {});
  }
  officialStockSelectionCache.set(cacheKey, selection);
  return selection;
}

async function officialStockTotals(dateText, runName, store = "") {
  if (!dateText) return null;
  const stores = selectedStoresFromRunName(runName, store);
  const cacheKey = `${dateText}|${[...stores].sort().join("-")}`;
  if (officialStockCache.has(cacheKey)) return officialStockCache.get(cacheKey);

  const selection = await readOfficialStockSelection(dateText, runName, store);
  if (!selection) {
    officialStockCache.set(cacheKey, null);
    return null;
  }

  const totals = {
    qtd: selection.qtd,
    valor: money(selection.valor),
    date: dateText,
    file: selection.file,
    linhas: selection.linhas,
  };
  officialStockCache.set(cacheKey, totals);
  return totals;
}

async function officialStockRows(dateText, runName, store = "") {
  if (!dateText) return null;
  const stores = selectedStoresFromRunName(runName, store);
  const cacheKey = `${dateText}|${[...stores].sort().join("-")}|rows`;
  if (officialStockRowsCache.has(cacheKey)) return officialStockRowsCache.get(cacheKey);

  const selection = await readOfficialStockSelection(dateText, runName, store);
  if (!selection) {
    officialStockRowsCache.set(cacheKey, null);
    return null;
  }

  const result = { date: dateText, file: selection.file, rows: selection.rows };
  officialStockRowsCache.set(cacheKey, result);
  return result;
}

async function stockDivergenceRows(runName, options = {}) {
  safeRunName(runName);
  const store = options.store || "";
  const parsedRun = parseAuditRunName(runName);
  const previousStockDate = previousDate(parsedRun.date);
  if (!previousStockDate || parsedRun.date <= MIN_AUDIT_DATE) return [];

  const runDir = path.join(AUDIT_DIR, runName);
  const [initialStock, finalStock, movimentos] = await Promise.all([
    officialStockRows(previousStockDate, runName, store),
    officialStockRows(parsedRun.date, runName, store),
    readCsv(path.join(runDir, "movimentos_estoque.csv")),
  ]);
  if (!initialStock || !finalStock) return [];

  const itemMap = new Map();
  const ensure = (sku) => {
    const key = String(sku || "").trim();
    if (!key) return null;
    if (!itemMap.has(key)) {
      itemMap.set(key, {
        sku: key,
        descricao: "",
        qtd_inicial: 0,
        valor_inicial: 0,
        qtd_movimento: 0,
        valor_movimento: 0,
        qtd_final_exportado: 0,
        valor_final_exportado: 0,
        origens: new Set(),
      });
    }
    return itemMap.get(key);
  };

  for (const row of initialStock.rows.values()) {
    const item = ensure(row.sku);
    if (!item) continue;
    item.qtd_inicial += row.qtd;
    item.valor_inicial += row.valor;
  }
  for (const row of finalStock.rows.values()) {
    const item = ensure(row.sku);
    if (!item) continue;
    item.qtd_final_exportado += row.qtd;
    item.valor_final_exportado += row.valor;
  }
  for (const row of filterRowsByStore(movimentos.rows, store)) {
    const origin = operationalOrigin(row);
    if (origin === "AUTOCONSUMO_ENTRADA") continue;
    const item = ensure(row.sku);
    if (!item) continue;
    const signed = operationalSignedMovement(row);
    item.descricao ||= row.descricao || "";
    item.qtd_movimento += signed.qtd;
    item.valor_movimento += signed.valor;
    item.origens.add(origin);
  }

  return [...itemMap.values()]
    .map((item) => {
      const qtdCalculada = item.qtd_inicial + item.qtd_movimento;
      const valorCalculado = item.valor_inicial + item.valor_movimento;
      const diferencaQtd = item.qtd_final_exportado - qtdCalculada;
      const diferencaValor = item.valor_final_exportado - valorCalculado;
      const custoInicial = item.qtd_inicial ? item.valor_inicial / item.qtd_inicial : 0;
      const custoFinal = item.qtd_final_exportado ? item.valor_final_exportado / item.qtd_final_exportado : 0;
      const motivo = Math.abs(diferencaQtd) <= 0.01 && Math.abs(diferencaValor) > 0.01
        ? "Quantidade fecha; diferenca vem de custo/valor"
        : Math.abs(diferencaQtd) > 0.01 && Math.abs(diferencaValor) <= 0.05
          ? "Valor fecha; diferenca de quantidade parece arredondamento/conversao do estoque exportado"
          : Math.abs(diferencaQtd) > 0.01
            ? "Quantidade nao fecha; revisar movimento faltante ou duplicado"
            : "Sem divergencia relevante";
      return {
        sku: item.sku,
        descricao: item.descricao,
        qtd_inicial: Number(item.qtd_inicial.toFixed(3)),
        custo_inicial: money(custoInicial),
        valor_inicial: money(item.valor_inicial),
        qtd_movimento: Number(item.qtd_movimento.toFixed(3)),
        valor_movimento: money(item.valor_movimento),
        qtd_final_calculado: Number(qtdCalculada.toFixed(3)),
        valor_final_calculado: money(valorCalculado),
        qtd_final_exportado: Number(item.qtd_final_exportado.toFixed(3)),
        custo_final: money(custoFinal),
        valor_final_exportado: money(item.valor_final_exportado),
        diferenca_qtd: Number(diferencaQtd.toFixed(3)),
        diferenca_valor: money(diferencaValor),
        motivo,
        origens: [...item.origens].sort().join(", "),
      };
    })
    .filter((row) => Math.abs(row.diferenca_qtd) > 0.01 || Math.abs(row.diferenca_valor) > 0.01)
    .sort((a, b) => Math.abs(b.diferenca_valor) - Math.abs(a.diferenca_valor));
}

function parseSnapshotRunName(name) {
  const match = name.match(/^(\d{4}-\d{2}-\d{2})_(\d{6})_(.+)_lojas_(.+)$/);
  return {
    date: match?.[1] || "",
    time: match?.[2] ? `${match[2].slice(0, 2)}:${match[2].slice(2, 4)}:${match[2].slice(4, 6)}` : "",
    label: match?.[3] || "",
    stores: match?.[4]?.replaceAll("-", ", ") || "",
  };
}

async function listDirectories(baseDir) {
  await fs.mkdir(baseDir, { recursive: true });
  const entries = await fs.readdir(baseDir, { withFileTypes: true });
  return entries.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort().reverse();
}

function pedidoNotaStatusOrder(status) {
  const text = String(status || "").trim().toUpperCase();
  if (text === "FALTOU_NA_NOTA") return 1;
  if (text === "VEIO_SEM_PEDIDO" || text === "NOTA_CD_SEM_PEDIDO") return 2;
  if (text === "DIVERGENCIA_QTD") return 3;
  if (text === "OK") return 4;
  return 5;
}

function sortPedidoNotaRows(rows) {
  return rows.slice().sort((a, b) => (
    String(a.loja || "").localeCompare(String(b.loja || ""), "pt-BR", { numeric: true })
    || String(a.data_entrada || "").localeCompare(String(b.data_entrada || ""))
    || String(a.nota || "").localeCompare(String(b.nota || ""), "pt-BR", { numeric: true })
    || String(a.pedido || "").localeCompare(String(b.pedido || ""), "pt-BR", { numeric: true })
    || pedidoNotaStatusOrder(a.situacao) - pedidoNotaStatusOrder(b.situacao)
    || String(a.sku || "").localeCompare(String(b.sku || ""), "pt-BR", { numeric: true })
  ));
}

async function auditSummary(runName, options = {}) {
  safeRunName(runName);
  const store = options.store || "";
  const runDir = path.join(AUDIT_DIR, runName);
  const parsedRun = parseAuditRunName(runName);
  const [manifest, estoqueRaw, vendasRaw, movResumo, movimentosRaw, entradasRaw, nfPendentesRaw, pedidosRaw, retificacoesRaw, inventariosRaw] = await Promise.all([
    readManifest(runDir),
    readCsv(path.join(runDir, "conciliacao_sku.csv")),
    readCsv(path.join(runDir, "vendas_sku.csv")),
    readCsv(path.join(runDir, "movimentos_resumo.csv")),
    readCsv(path.join(runDir, "movimentos_estoque.csv")),
    readCsv(path.join(runDir, "notas_entrada.csv")),
    readCsv(path.join(runDir, "notas_pendentes_entrada.csv")),
    readCsv(path.join(runDir, "pedidos_transferencia.csv")),
    readCsv(path.join(runDir, "retificacoes.csv")),
    readCsv(path.join(runDir, "inventarios.csv")),
  ]);
  const availableStores = storeListFromRunName(runName);
  if (!availableStores.length) {
    availableStores.push(...storeListFromRows(
      estoqueRaw.rows,
      vendasRaw.rows,
      movimentosRaw.rows,
      entradasRaw.rows,
      nfPendentesRaw.rows,
      pedidosRaw.rows,
      retificacoesRaw.rows,
      inventariosRaw.rows,
    ));
  }
  const estoque = { ...estoqueRaw, rows: filterRowsByStore(estoqueRaw.rows, store) };
  const vendas = { ...vendasRaw, rows: filterRowsByStore(vendasRaw.rows, store) };
  const movimentos = { ...movimentosRaw, rows: filterRowsByStore(movimentosRaw.rows, store) };
  const entradas = { ...entradasRaw, rows: filterRowsByStore(entradasRaw.rows, store) };
  const nfPendentes = { ...nfPendentesRaw, rows: filterRowsByStore(nfPendentesRaw.rows, store) };
  const pedidos = { ...pedidosRaw, rows: filterRowsByStore(pedidosRaw.rows, store) };
  const retificacoes = { ...retificacoesRaw, rows: filterRowsByStore(retificacoesRaw.rows, store) };
  const inventarios = { ...inventariosRaw, rows: filterRowsByStore(inventariosRaw.rows, store) };
  const movCausa = movimentos.rows.filter(tableFilters.mov_causa);
  const autoconsumo = movimentos.rows.filter(tableFilters.autoconsumo);
  const semCausa = movimentos.rows.filter(tableFilters.mov_sem_causa);
  const origins = normalizeMovementSummary(movimentos.rows);
  const inventorySummaries = inventorySummaryFromMovements(movimentos.rows);
  const estoqueRows = estoque.rows;
  const previousStockDate = previousDate(parsedRun.date);
  const [initialOfficial, finalOfficial] = await Promise.all([
    parsedRun.date > MIN_AUDIT_DATE ? officialStockTotals(previousStockDate, runName, store) : Promise.resolve(null),
    officialStockTotals(parsedRun.date, runName, store),
  ]);
  const initialQtd = initialOfficial?.qtd ?? 0;
  const initialValor = initialOfficial?.valor ?? 0;
  const movimentoQtd = sum(origins, "qtd_movimento");
  const movimentoValor = money(sum(origins, "valor_movimento_custo"));
  const finalQtd = finalOfficial?.qtd ?? sum(estoqueRows, "qtd_fim_pleno");
  const finalValor = finalOfficial?.valor ?? money(sum(estoqueRows, "valor_fim_pleno_custo"));
  const esperadoQtd = initialQtd + movimentoQtd;
  const esperadoValor = money(initialValor + movimentoValor);
  const divergenceRows = await stockDivergenceRows(runName, { store });
  const custoRows = divergenceRows.filter((row) => Math.abs(number(row.diferenca_qtd)) <= 0.01 && Math.abs(number(row.diferenca_valor)) > 0.01);
  const qtdRows = divergenceRows.filter((row) => Math.abs(number(row.diferenca_qtd)) > 0.01);
  const custoValor = money(sum(custoRows, "diferenca_valor"));
  const qtdValor = money(sum(qtdRows, "diferenca_valor"));
  const quantidadeFechada = Math.abs(finalQtd - esperadoQtd) <= SUMMARY_QTY_TOLERANCE;
  const totals = {
    estoqueInicialQtd: initialQtd,
    estoqueInicialValor: initialValor,
    movimentoQtd,
    movimentoValor,
    esperadoQtd,
    esperadoValor,
    finalQtd,
    finalValor,
    divergenciaQtd: finalQtd - esperadoQtd,
    divergenciaValor: money(finalValor - esperadoValor),
    vendasQtd: sum(vendas.rows, "qtd_vendida"),
    vendasValor: money(sum(vendas.rows, "valor_vendido")),
    entradasQtd: sum(entradas.rows, "qtd_nota"),
    entradasValor: money(sum(entradas.rows, "valor_item_nota")),
    pendentesEntrada: nfPendentes.rows.length,
    pendentesEntradaValor: money(sum(nfPendentes.rows, "valor_nf")),
    saidasCdQtd: sumAbs(movCausa, "qtd_movimento"),
    saidasCdValor: money(sumAbs(movCausa, "valor_movimento_custo")),
    autoconsumoQtd: sumAbs(autoconsumo, "qtd_movimento"),
    autoconsumoValor: money(sumAbs(autoconsumo, "valor_movimento_custo")),
    semCausaQtd: sum(semCausa, "qtd_movimento"),
    semCausaValor: money(sum(semCausa, "valor_movimento_custo")),
    pedidos: pedidos.rows.length,
    pedidosValor: money(sum(pedidos.rows, "valor_pedido_custo_atual")),
    retificacoes: retificacoes.rows.length,
    inventarios: inventorySummaries.length,
    divergenciaCustoValor: custoValor,
    divergenciaCustoItens: custoRows.length,
    divergenciaQtdValor: qtdValor,
    divergenciaQtdItens: qtdRows.length,
  };
  const tableCounts = {
    conciliacao_sku: estoqueRows.length,
    vendas_sku: vendas.rows.length,
    movimentos_resumo: origins.length,
    notas_entrada: entradas.rows.length,
    notas_pendentes_entrada: nfPendentes.rows.length,
    mov_causa: movCausa.length,
    autoconsumo: autoconsumo.length,
    mov_sem_causa: semCausa.length,
    pedidos_transferencia: pedidos.rows.length,
    retificacoes: retificacoes.rows.length,
    inventarios: inventorySummaries.length,
    divergencia_custo: divergenceRows.length,
  };
  return {
    name: runName,
    ...parsedRun,
    availableStores,
    selectedStore: store || "",
    storeScope: store && store !== "all" ? store : "all",
    stores: store && store !== "all" ? store : parsedRun.stores,
    stockDates: {
      initial: initialOfficial?.date || "",
      final: parsedRun.date,
    },
    stockSources: {
      initial: initialOfficial?.file || (parsedRun.date <= MIN_AUDIT_DATE ? "inicio_da_base" : "sem_exportacao_anterior"),
      final: finalOfficial?.file || "pacote_auditoria",
      finalLinhas: finalOfficial?.linhas || 0,
    },
    manifest,
    totals,
    divergenceExplanation: {
      status: quantidadeFechada
        ? "Quantidade fechada"
        : "Quantidade com diferenca",
      quantityClosed: quantidadeFechada,
      quantityTolerance: SUMMARY_QTY_TOLERANCE,
      message: quantidadeFechada && Math.abs(totals.divergenciaValor) > 0.01
        ? "A quantidade esta fechando dentro da tolerancia operacional. A diferenca em valor vem da mudanca de custo/valor dos itens entre o estoque inicial, os movimentos e o estoque final exportado."
        : !quantidadeFechada
          ? "Existe diferenca em quantidade. Primeiro investigue itens com movimento faltante, duplicado ou classificado com sinal incorreto."
          : "Estoque fechado em quantidade e valor.",
      custoValor,
      custoItens: custoRows.length,
      qtdValor,
      qtdItens: qtdRows.length,
      topCusto: custoRows.slice(0, 5).map((row) => ({
        sku: row.sku,
        descricao: row.descricao,
        diferenca_valor: row.diferenca_valor,
        diferenca_qtd: row.diferenca_qtd,
        custo_inicial: row.custo_inicial,
        custo_final: row.custo_final,
      })),
      topQtd: qtdRows
        .slice()
        .sort((a, b) => Math.abs(number(b.diferenca_qtd)) - Math.abs(number(a.diferenca_qtd)))
        .slice(0, 5)
        .map((row) => ({
          sku: row.sku,
          descricao: row.descricao,
          diferenca_qtd: row.diferenca_qtd,
          diferenca_valor: row.diferenca_valor,
          qtd_final_calculado: row.qtd_final_calculado,
          qtd_final_exportado: row.qtd_final_exportado,
          motivo: row.motivo,
        })),
    },
    origins,
    counts: tableCounts,
  };
}

async function listRuns() {
  const names = await listDirectories(AUDIT_DIR);
  const runs = await Promise.all(names
    .filter((name) => name.includes("_lojas_"))
    .map(async (name) => {
      const parsed = parseAuditRunName(name);
      return {
        name,
        ...parsed,
        availableStores: await availableStoresForRun(name),
        totals: null,
        origins: [],
      };
    }));
  return runs
    .filter((run) => !run.date || run.date >= MIN_AUDIT_DATE)
    .sort((a, b) => b.name.localeCompare(a.name));
}

async function listSnapshots() {
  const names = await listDirectories(SNAPSHOT_DIR);
  return Promise.all(names.filter((name) => {
    if (!name.includes("_lojas_")) return false;
    const parsed = parseSnapshotRunName(name);
    return !parsed.date || parsed.date >= MIN_AUDIT_DATE;
  }).map(async (name) => {
    const runDir = path.join(SNAPSHOT_DIR, name);
    const manifest = await readManifest(runDir);
    const csv = await readCsv(path.join(runDir, "estoque_atual_snapshot.csv"));
    return { name, ...parseSnapshotRunName(name), manifest, rows: csv.rows.length };
  }));
}

async function tableData(runName, key, options = {}) {
  safeRunName(runName);
  const store = options.store || "";
  const spec = auditTables.find(([tableKey]) => tableKey === key);
  if (!spec) throw new Error("Tabela invalida.");
  const [, title, file] = spec;
  if (key === "divergencia_custo") {
    const rows = await stockDivergenceRows(runName, { store });
    const headers = [
      "sku",
      "descricao",
      "diferenca_valor",
      "diferenca_qtd",
      "motivo",
      "qtd_inicial",
      "custo_inicial",
      "valor_inicial",
      "qtd_movimento",
      "valor_movimento",
      "qtd_final_calculado",
      "valor_final_calculado",
      "qtd_final_exportado",
      "custo_final",
      "valor_final_exportado",
      "origens",
    ];
    return { key, title, headers, rows: rows.slice(0, 1000), totalRows: rows.length };
  }
  const csv = await readCsv(path.join(AUDIT_DIR, runName, file));
  if (key === "notas_cd" && csv.rows.length === 0) {
    const movimentos = await readCsv(path.join(AUDIT_DIR, runName, "movimentos_estoque.csv"));
    const rows = filterRowsByStore(movimentos.rows, store).filter(tableFilters.notas_cd).map((row) => ({
      loja: row.loja,
      nome_loja: row.nome_loja,
      data_movimento: row.data_movimento,
      nota: row.nota,
      serie: row.serie,
      sku: row.sku,
      descricao: row.descricao,
      qtd_nota_cd: Math.abs(number(row.qtd_movimento)).toFixed(3),
      valor_nota_cd: Math.abs(number(row.valor_movimento_custo)).toFixed(2),
      movimento_id: row.movimento_id,
    }));
    return {
      key,
      title,
      headers: ["loja", "nome_loja", "data_movimento", "nota", "serie", "sku", "descricao", "qtd_nota_cd", "valor_nota_cd", "movimento_id"],
      rows: rows.slice(0, 1000),
      totalRows: rows.length,
    };
  }
  if (key === "notas_saida" && csv.rows.length === 0) {
    const movimentos = await readCsv(path.join(AUDIT_DIR, runName, "movimentos_estoque.csv"));
    const rows = notaSaidaRowsFromMovements(filterRowsByStore(movimentos.rows, store));
    return {
      key,
      title,
      headers: [
        "loja",
        "nome_loja",
        "data_movimento",
        "nota",
        "serie",
        "entrada_saida",
        "sku",
        "descricao",
        "qtd_nota_saida",
        "valor_nota_saida",
        "movimento_id",
        "devolucao_codigos",
        "devolucao_causa_codigos",
        "devolucao_causas",
        "retificacao_ids",
        "retificacao_albarans",
      ],
      rows: rows.slice(0, 1000),
      totalRows: rows.length,
    };
  }
  if (key === "movimentos_resumo") {
    const movimentos = await readCsv(path.join(AUDIT_DIR, runName, "movimentos_estoque.csv"));
    const rows = normalizeMovementSummary(filterRowsByStore(movimentos.rows, store));
    return { key, title, headers: csv.headers, rows: rows.slice(0, 1000), totalRows: rows.length };
  }
  if (key === "inventario_itens" && csv.rows.length === 0) {
    const movimentos = await readCsv(path.join(AUDIT_DIR, runName, "movimentos_estoque.csv"));
    const rows = filterRowsByStore(movimentos.rows, store).filter(tableFilters.inventario_itens).map((row) => ({
      loja: row.loja,
      nome_loja: row.nome_loja,
      inventario_id: row.inventario_id,
      data_inventario: row.data_movimento,
      sku: row.sku,
      descricao: row.descricao,
      qtd_sistema: "",
      valor_sistema_custo: "",
      qtd_contagem: "",
      valor_contado_custo: "",
      diferenca_qtd: "",
      diferenca_valor_custo: "",
      origem_pacote: "pacote_sem_contagem_por_item",
    }));
    return {
      key,
      title,
      headers: [
        "loja",
        "nome_loja",
        "inventario_id",
        "data_inventario",
        "sku",
        "descricao",
        "qtd_sistema",
        "valor_sistema_custo",
        "qtd_contagem",
        "valor_contado_custo",
        "diferenca_qtd",
        "diferenca_valor_custo",
        "origem_pacote",
      ],
      rows: rows.slice(0, 1000),
      totalRows: rows.length,
      warning: "Este pacote foi gerado antes do inventario_itens.csv; as quantidades contadas por item nao vieram no arquivo.",
    };
  }
  if (key === "inventarios") {
    const movimentos = await readCsv(path.join(AUDIT_DIR, runName, "movimentos_estoque.csv"));
    const rows = inventorySummaryFromMovements(filterRowsByStore(movimentos.rows, store));
    const headers = [
      "loja",
      "nome_loja",
      "inventario_id",
      "descricao_inventario",
      "data_inventario",
      "inicio",
      "fim",
      "fechado",
      "cancelado",
      "itens",
      "qtd_sistema",
      "valor_sistema_custo",
      "qtd_contagem",
      "valor_contagem_custo",
      "diferenca_qtd",
      "diferenca_valor_custo",
    ];
    return { key, title, headers, rows: rows.slice(0, 1000), totalRows: rows.length };
  }
  if (key === "pedido_nota_divergencia") {
    const rows = sortPedidoNotaRows(filterRowsByStore(csv.rows, store));
    return { key, title, headers: csv.headers, rows: rows.slice(0, 1000), totalRows: rows.length };
  }
  const scopedRows = filterRowsByStore(csv.rows, store);
  const rows = tableFilters[key] && file === "movimentos_estoque.csv" ? scopedRows.filter(tableFilters[key]) : scopedRows;
  return { key, title, headers: csv.headers, rows: rows.slice(0, 1000), totalRows: rows.length };
}

function runCommand(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: ROOT, ...options });
    let stdout = "";
    let stderr = "";
    child.stdout?.on("data", (data) => { stdout += data.toString(); });
    child.stderr?.on("data", (data) => { stderr += data.toString(); });
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolve({ stdout, stderr });
      else reject(new Error(stderr || stdout || `${command} saiu com codigo ${code}`));
    });
  });
}

let sapApiMonitorRunning = false;
let checkinNotasMonitorRunning = false;
let pedidosDiaflexRefreshPromise = null;
let pdvConsumoRefreshPromise = null;
let tesourariaCofreLaunchPromise = null;
let prevencaoPerdasLaunchPromise = null;

async function refreshPedidosDiaflexMonitor() {
  if (!pedidosDiaflexRefreshPromise) {
    const script = path.join(ROOT, "scripts", "run_pedidos_business_monitor_step.sh");
    pedidosDiaflexRefreshPromise = runCommand("sh", [script, "all"], {
      env: { ...process.env, PEDIDOS_MONITOR_STATUS_FILE: PEDIDOS_STATUS_FILE },
    }).finally(() => {
      pedidosDiaflexRefreshPromise = null;
    });
  }
  try {
    await pedidosDiaflexRefreshPromise;
  } catch (error) {
    const summary = await pedidosBusinessMonitorSummary();
    return { ...summary, refreshError: String(error.message || error), notice: "Reverificacao incompleta: consulte as etapas com erro da coleta atual." };
  }
  return pedidosBusinessMonitorSummary();
}

async function startTesourariaCofreRun() {
  if (tesourariaCofreLaunchPromise) return tesourariaCofreLaunchPromise;
  tesourariaCofreLaunchPromise = (async () => {
    const lockFile = process.env.TESOURARIA_LOCK_FILE || "/tmp/tesouraria-cofre-inteligente.lock";
    const execution = await tesourariaCofreExecution();
    try {
      await runCommand("flock", ["-n", lockFile, "true"]);
    } catch {
      return { started: false, execution, message: "O robô já está em execução." };
    }

    const startedAt = new Date().toISOString();
    const startedExecution = {
      status: "executando", message: "Execução manual iniciada.", currentStore: "",
      currentPlannedDate: "", processed: 0, completed: 0, failed: 0, updatedAt: startedAt,
    };
    await fs.mkdir(TESOURARIA_COFRE_DIR, { recursive: true });
    await fs.writeFile(path.join(TESOURARIA_COFRE_DIR, "execucao.json"), JSON.stringify(startedExecution));

    const runner = path.join(ROOT, "scripts", "run-tesouraria-cofre-cron.sh");
    const child = spawn("sh", [runner], {
      cwd: ROOT, detached: true, stdio: "ignore", env: { ...process.env },
    });
    child.unref();
    return { started: true, execution: startedExecution, message: "Execução iniciada." };
  })().finally(() => { tesourariaCofreLaunchPromise = null; });
  return tesourariaCofreLaunchPromise;
}

async function startPrevencaoPerdasRun() {
  if (prevencaoPerdasLaunchPromise) return prevencaoPerdasLaunchPromise;
  prevencaoPerdasLaunchPromise = (async () => {
    const lockFile = process.env.PREV_PERDAS_LOCK_FILE || "/tmp/prevencao-perdas.lock";
    const execution = await prevencaoPerdasExecution();
    try {
      await runCommand("flock", ["-n", lockFile, "true"]);
    } catch {
      return { started: false, execution, message: "O robo de prevencao e perdas ja esta em execucao." };
    }

    const startedAt = new Date().toISOString();
    const startedExecution = {
      status: "executando", message: "Execucao manual iniciada.", currentFilial: "",
      currentNota: "", processed: 0, completed: 0, failed: 0, updatedAt: startedAt,
    };
    await fs.mkdir(PREVENCAO_PERDAS_DIR, { recursive: true });
    await fs.writeFile(path.join(PREVENCAO_PERDAS_DIR, "execucao.json"), JSON.stringify(startedExecution));

    const runner = path.join(ROOT, "scripts", "run-prevencao-perdas-cron.sh");
    const child = spawn("sh", [runner], {
      cwd: ROOT, detached: true, stdio: "ignore", env: { ...process.env },
    });
    child.unref();
    return { started: true, execution: startedExecution, message: "Execucao iniciada." };
  })().finally(() => { prevencaoPerdasLaunchPromise = null; });
  return prevencaoPerdasLaunchPromise;
}

async function runSapApiMonitor(reason = "interval") {
  if (!SAP_API_MONITOR_ENABLED || sapApiMonitorRunning) return;
  sapApiMonitorRunning = true;
  try {
    const script = path.join(ROOT, "scripts", "update_sap_api_monitor.py");
    const result = await runCommand(PYTHON_BIN, [script], {
      env: {
        ...process.env,
        SAP_API_MONITOR_STATUS_FILE,
      },
    });
    const output = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join(" ");
    console.log(`Monitor APIs SAP (${reason}) OK.${output ? ` ${output}` : ""}`);
  } catch (error) {
    console.error(`Monitor APIs SAP (${reason}) falhou:`, error.message);
  } finally {
    sapApiMonitorRunning = false;
  }
}

function startSapApiMonitor() {
  if (!SAP_API_MONITOR_ENABLED) {
    console.log("Monitor APIs SAP desabilitado por SAP_API_MONITOR_ENABLED=0.");
    return;
  }
  runSapApiMonitor("startup");
  setInterval(() => runSapApiMonitor("interval"), SAP_API_MONITOR_INTERVAL_MS);
}

async function runCheckinNotasMonitor(reason = "interval") {
  if (!CHECKIN_NOTAS_MONITOR_ENABLED || checkinNotasMonitorRunning) return;
  checkinNotasMonitorRunning = true;
  try {
    const script = path.join(ROOT, "scripts", "update_checkin_notas_monitor.py");
    const result = await runCommand(PYTHON_BIN, [script], {
      env: {
        ...process.env,
        CHECKIN_NOTAS_STATUS_FILE,
      },
    });
    const output = [result.stdout.trim(), result.stderr.trim()].filter(Boolean).join(" ");
    console.log(`Monitor check-in notas (${reason}) OK.${output ? ` ${output}` : ""}`);
  } catch (error) {
    console.error(`Monitor check-in notas (${reason}) falhou:`, error.message);
  } finally {
    checkinNotasMonitorRunning = false;
  }
}

function startCheckinNotasMonitor() {
  if (!CHECKIN_NOTAS_MONITOR_ENABLED) {
    console.log("Monitor check-in notas desabilitado por CHECKIN_NOTAS_MONITOR_ENABLED=0.");
    return;
  }
  runCheckinNotasMonitor("startup");
  setInterval(() => runCheckinNotasMonitor("interval"), CHECKIN_NOTAS_MONITOR_INTERVAL_MS);
}

async function extractPackage(filePath) {
  const listing = await runCommand("tar", ["-tzf", filePath]);
  const first = listing.stdout.split("\n").find(Boolean) || "";
  const isAudit = first.includes("_lojas_") && /^\d{4}-\d{2}-\d{2}_lojas_/.test(first.replace(/\/$/, ""));
  const isSnapshot = first.includes("_lojas_") && /^\d{4}-\d{2}-\d{2}_\d{6}_/.test(first.replace(/\/$/, ""));
  const dest = isSnapshot ? SNAPSHOT_DIR : AUDIT_DIR;
  if (!isAudit && !isSnapshot) {
    throw new Error("Pacote nao reconhecido como auditoria ou snapshot.");
  }
  await fs.mkdir(dest, { recursive: true });
  await runCommand("tar", ["-xzf", filePath, "-C", dest]);
  return { type: isSnapshot ? "snapshot" : "audit", folder: first.replace(/\/$/, "") };
}

async function packageInfo(filePath) {
  const listing = await runCommand("tar", ["-tzf", filePath]);
  const first = listing.stdout.split("\n").find(Boolean) || "";
  const folder = first.replace(/\/$/, "");
  const isAudit = first.includes("_lojas_") && /^\d{4}-\d{2}-\d{2}_lojas_/.test(folder);
  const isSnapshot = first.includes("_lojas_") && /^\d{4}-\d{2}-\d{2}_\d{6}_/.test(folder);
  if (!isAudit && !isSnapshot) return null;
  return {
    type: isSnapshot ? "snapshot" : "audit",
    folder,
    dest: isSnapshot ? SNAPSHOT_DIR : AUDIT_DIR,
  };
}

async function clearExcelCache(runName) {
  await Promise.all([
    fs.unlink(path.join(EXCEL_DIR, `pleno_auditoria_${runName}.xlsx`)).catch(() => {}),
    fs.unlink(path.join(EXCEL_DIR, `pleno_auditoria_${runName}.xls`)).catch(() => {}),
  ]);
}

async function clearAllExcelCache() {
  const entries = await fs.readdir(EXCEL_DIR).catch(() => []);
  await Promise.all(entries
    .filter((name) => /^pleno_auditoria_.*\.xlsx?$/.test(name))
    .map((name) => fs.unlink(path.join(EXCEL_DIR, name)).catch(() => {})));
}

function clearOfficialStockCaches() {
  officialStockCache.clear();
  officialStockRowsCache.clear();
  officialStockDateCache.clear();
  officialStockSelectionCache.clear();
}

async function consumeOfficialStockFile(filePath) {
  await fs.mkdir(OFFICIAL_STOCK_DIR, { recursive: true });
  const destPath = path.join(OFFICIAL_STOCK_DIR, path.basename(filePath));
  if (path.resolve(filePath) === path.resolve(destPath)) return destPath;
  await fs.copyFile(filePath, destPath);
  await fs.unlink(filePath).catch(() => {});
  return destPath;
}

async function rebuildOfficialStockIndex() {
  const script = path.join(ROOT, "scripts", "build_pleno_stock_official_index.py");
  try {
    await fs.access(script);
  } catch {
    console.warn("Indexador de estoque oficial nao encontrado.");
    return;
  }
  try {
    const result = await runCommand(PYTHON_BIN, [script], {
      env: { ...process.env, PYTHONPATH: `${ROOT}/.python_packages${process.env.PYTHONPATH ? `:${process.env.PYTHONPATH}` : ""}` },
    });
    if (result.stdout.trim()) console.log(result.stdout.trim());
    if (result.stderr.trim()) console.warn(result.stderr.trim());
  } catch (error) {
    console.warn(`Falha ao gerar indice do estoque oficial: ${error.message}`);
  }
}

async function cleanupIndexedOfficialStockFiles() {
  const stockFiles = await fs.readdir(OFFICIAL_STOCK_DIR).catch(() => []);
  const indexFiles = await fs.readdir(OFFICIAL_STOCK_INDEX_DIR).catch(() => []);
  const removed = [];

  for (const name of stockFiles) {
    if (!/^estoque_\d{8}.*\.csv$/i.test(name)) continue;
    const prefix = path.basename(name, ".csv");
    const hasIndex = indexFiles.some((indexName) => indexName.startsWith(`${prefix}_loja_`) && indexName.endsWith(".json"));
    if (!hasIndex) continue;
    await fs.unlink(path.join(OFFICIAL_STOCK_DIR, name)).catch(() => {});
    removed.push(name);
  }

  if (removed.length) {
    console.log(`Estoque oficial: ${removed.length} CSV(s) bruto(s) removido(s) apos indexacao.`);
  }
  return removed;
}

async function scanReceivedServerFiles() {
  await fs.mkdir(RECEIVED_DIR, { recursive: true });
  const entries = await fs.readdir(RECEIVED_DIR, { withFileTypes: true }).catch(() => []);
  const imported = [];
  let stockCacheCleared = false;
  const now = Date.now();

  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const filePath = path.join(RECEIVED_DIR, entry.name);
    const stat = await fs.stat(filePath).catch(() => null);
    if (!stat || now - stat.mtimeMs < RECEIVED_FILE_STABLE_MS) continue;
    const signature = `${stat.size}:${Math.round(stat.mtimeMs)}`;
    if (receivedScanState.get(entry.name) === signature) continue;

    if (/^estoque_\d{8}.*\.csv$/i.test(entry.name)) {
      await consumeOfficialStockFile(filePath);
      clearOfficialStockCaches();
      await clearAllExcelCache();
      stockCacheCleared = true;
      receivedScanState.set(entry.name, signature);
      continue;
    }

    if (!entry.name.endsWith(".tar.gz")) continue;
    const info = await packageInfo(filePath).catch((error) => {
      console.warn(`Monitor: pacote ignorado ${entry.name}: ${error.message}`);
      return null;
    });
    if (!info) {
      receivedScanState.set(entry.name, signature);
      continue;
    }

    const destPath = path.join(info.dest, info.folder);
    const destStat = await fs.stat(destPath).catch(() => null);
    const shouldExtract = !destStat || stat.mtimeMs > destStat.mtimeMs + 1000;
    if (shouldExtract) {
      await extractPackage(filePath);
      if (info.type === "audit") await clearExcelCache(info.folder);
      imported.push({ file: entry.name, type: info.type, folder: info.folder });
    }
    await fs.unlink(filePath).catch(() => {});
    receivedScanState.set(entry.name, signature);
  }

  if (stockCacheCleared || imported.length) {
    await rebuildOfficialStockIndex();
    await cleanupIndexedOfficialStockFiles();
    console.log(`Monitor recebidos_servidor: ${imported.length} pacote(s) importado(s), cache estoque ${stockCacheCleared ? "limpo" : "inalterado"}.`);
  }
  return { imported, stockCacheCleared };
}

function startReceivedServerMonitor() {
  const runScan = () => {
    scanReceivedServerFiles().catch((error) => {
      console.error(`Monitor recebidos_servidor: ${error.message}`);
    });
  };
  runScan();
  setInterval(runScan, RECEIVED_SCAN_INTERVAL_MS);
}

async function importUploads(req) {
  await fs.mkdir(RECEIVED_DIR, { recursive: true });
  const contentType = req.headers["content-type"] || "";
  const match = contentType.match(/boundary=(.+)$/);
  if (!match) throw new Error("Upload multipart invalido.");
  const boundary = `--${match[1]}`;
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const buffer = Buffer.concat(chunks);
  const parts = buffer.toString("binary").split(boundary).filter((part) => part.includes("filename="));
  const imported = [];
  for (const part of parts) {
    const headerEnd = part.indexOf("\r\n\r\n");
    if (headerEnd < 0) continue;
    const header = part.slice(0, headerEnd);
    const fileMatch = header.match(/filename="([^"]+)"/);
    if (!fileMatch) continue;
    const original = path.basename(fileMatch[1]).replace(/[^\w.-]/g, "_");
    if (!original.endsWith(".tar.gz")) continue;
    const start = Buffer.byteLength(part.slice(0, headerEnd + 4), "binary");
    const end = Buffer.byteLength(part.replace(/\r\n$/, ""), "binary");
    const fileBuffer = Buffer.from(part, "binary").subarray(start, end);
    const filePath = path.join(RECEIVED_DIR, original);
    await fs.writeFile(filePath, fileBuffer);
    const result = await extractPackage(filePath);
    if (result.type === "audit") await clearExcelCache(result.folder);
    await fs.unlink(filePath).catch(() => {});
    receivedScanState.set(original, `${fileBuffer.length}:${Date.now()}`);
    imported.push({ file: original, ...result });
  }
  return imported;
}

async function ensureExcel(runName) {
  safeRunName(runName);
  await fs.mkdir(EXCEL_DIR, { recursive: true });
  const output = path.join(EXCEL_DIR, `pleno_auditoria_${runName}.xlsx`);
  try {
    await fs.access(output);
    return output;
  } catch {
    const builder = path.join(ROOT, "scripts", "build_pleno_stock_audit_excel.mjs");
    try {
      await runCommand(NODE_BIN, [builder, "--run-dir", path.join(AUDIT_DIR, runName), "--output-dir", EXCEL_DIR], {
        env: { ...process.env },
      });
      return output;
    } catch {
      return writeExcelFallback(runName);
    }
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function escapeXml(value) {
  return escapeHtml(value).replaceAll("'", "&apos;");
}

const brMoney = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const brNumber = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 3 });

function formatMoneyBr(value) {
  return brMoney.format(number(value));
}

function formatQtyBr(value) {
  return brNumber.format(number(value));
}

function valueColor(value) {
  const parsed = number(value);
  if (parsed < 0) return "#c93535";
  if (parsed > 0) return "#087443";
  return "#182230";
}

function wrapText(value, maxChars) {
  const words = String(value || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (next.length > maxChars && current) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  return lines;
}

function summaryImageSvg(summary) {
  const totals = summary.totals || {};
  const stockDates = summary.stockDates || {};
  const stockSources = summary.stockSources || {};
  const explanation = summary.divergenceExplanation || {};
  const origins = summary.origins || [];
  const width = 1900;
  const height = 1720;
  const parts = [];
  const add = (chunk) => parts.push(chunk);
  const text = (x, y, value, options = {}) => {
    const {
      size = 20,
      weight = 400,
      fill = "#182230",
      anchor = "start",
      family = "-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif",
    } = options;
    add(`<text x="${x}" y="${y}" font-family="${family}" font-size="${size}" font-weight="${weight}" fill="${fill}" text-anchor="${anchor}">${escapeXml(value)}</text>`);
  };
  const rect = (x, y, w, h, options = {}) => {
    const { fill = "#ffffff", stroke = "#d9e2ea", radius = 0 } = options;
    add(`<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${radius}" fill="${fill}" stroke="${stroke}"/>`);
  };
  const kpi = (x, y, w, title, value, detail, color = "#182230") => {
    rect(x, y, w, 84);
    text(x + 14, y + 28, title, { size: 15, fill: "#667085", weight: 600 });
    text(x + 14, y + 58, value, { size: 28, fill: color, weight: 800 });
    text(x + 14, y + 78, detail, { size: 14, fill: "#667085" });
  };
  const smallCard = (x, y, w, title, value, detail, color = "#182230") => {
    rect(x, y, w, 78, { stroke: "#edf2f6" });
    text(x + 14, y + 25, title, { size: 15, fill: "#667085", weight: 600 });
    text(x + 14, y + 55, value, { size: 25, fill: color, weight: 800 });
    text(x + 14, y + 72, detail, { size: 13, fill: "#667085" });
  };
  const table = (x, y, w, h, title, headers, rows, widths, aligns = []) => {
    rect(x, y, w, h);
    text(x + 16, y + 34, title, { size: 22, weight: 800, fill: "#17324d" });
    add(`<rect x="${x}" y="${y + 54}" width="${w}" height="38" fill="#eaf2f8" stroke="#eaf2f8"/>`);
    let cx = x + 14;
    headers.forEach((header, idx) => {
      const align = aligns[idx] || "start";
      const tx = align === "end" ? cx + widths[idx] - 8 : cx;
      text(tx, y + 79, header, { size: 15, weight: 800, fill: "#17324d", anchor: align });
      cx += widths[idx];
    });
    rows.forEach((row, rowIdx) => {
      const rowY = y + 116 + rowIdx * 34;
      add(`<line x1="${x}" y1="${rowY - 22}" x2="${x + w}" y2="${rowY - 22}" stroke="#edf2f6"/>`);
      let cellX = x + 14;
      row.forEach((cell, idx) => {
        const align = aligns[idx] || "start";
        const tx = align === "end" ? cellX + widths[idx] - 8 : cellX;
        text(tx, rowY, cell, { size: 15, fill: "#182230", anchor: align, weight: row[0] === "TOTAL" ? 800 : 400 });
        cellX += widths[idx];
      });
    });
  };

  add(`<?xml version="1.0" encoding="UTF-8"?>`);
  add(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`);
  rect(0, 0, width, height, { fill: "#f4f7f9", stroke: "#f4f7f9" });
  text(32, 52, `Auditoria ${summary.date || summary.name}`, { size: 32, weight: 800, fill: "#17324d" });
  text(32, 82, `Lojas ${summary.stores || "-"} · estoque inicial ${stockDates.initial || "-"} · estoque final ${stockDates.final || "-"} · carga ${summary.name}`, { size: 17, fill: "#667085", weight: 600 });
  rect(32, 110, 1836, 46, { fill: "#fff8e5", stroke: "#f0d891" });
  text(48, 139, "Regra operacional: o estoque inicial do dia deve ser o estoque final do dia anterior. A rotina diaria usa o snapshot do fechamento.", { size: 16, fill: "#513c06", weight: 700 });

  const gap = 12;
  const cardW = (1836 - gap * 4) / 5;
  const cardY1 = 178;
  [
    ["Estoque inicial", formatMoneyBr(totals.estoqueInicialValor), `${stockDates.initial || "-"} · ${formatQtyBr(totals.estoqueInicialQtd)} un.`, "#182230"],
    ["Movimento total", formatMoneyBr(totals.movimentoValor), `${formatQtyBr(totals.movimentoQtd)} un.`, valueColor(totals.movimentoValor)],
    ["Estoque final calculado", formatMoneyBr(totals.esperadoValor), `${formatQtyBr(totals.esperadoQtd)} un.`, "#182230"],
    ["Estoque final exportado", formatMoneyBr(totals.finalValor), `${stockDates.final || "-"} · ${formatQtyBr(totals.finalQtd)} un.`, "#182230"],
    ["Divergencia", formatMoneyBr(totals.divergenciaValor), `${formatQtyBr(totals.divergenciaQtd)} un.`, valueColor(totals.divergenciaValor)],
    ["Pedidos pendentes", formatMoneyBr(totals.pedidosValor), `${formatQtyBr(totals.pedidos)} itens`, number(totals.pedidos) ? "#c93535" : "#182230"],
    ["Vendas cupom", formatMoneyBr(totals.vendasValor), `${formatQtyBr(totals.vendasQtd)} un.`, "#182230"],
    ["Notas CD", formatMoneyBr(totals.saidasCdValor), `${formatQtyBr(totals.saidasCdQtd)} un.`, "#182230"],
    ["Autoconsumo", formatMoneyBr(totals.autoconsumoValor), `${formatQtyBr(totals.autoconsumoQtd)} un.`, "#182230"],
    ["Entradas NF", formatMoneyBr(totals.entradasValor), `${formatQtyBr(totals.entradasQtd)} un.`, "#182230"],
    ["NF pendente", formatMoneyBr(totals.pendentesEntradaValor), `${formatQtyBr(totals.pendentesEntrada)} notas`, number(totals.pendentesEntrada) ? "#c93535" : "#182230"],
    ["Inventarios", formatQtyBr(totals.inventarios), "registros no periodo", number(totals.inventarios) ? "#c93535" : "#182230"],
  ].forEach(([title, value, detail, color], idx) => {
    const row = Math.floor(idx / 5);
    const col = idx % 5;
    kpi(32 + col * (cardW + gap), cardY1 + row * 96, cardW, title, value, detail, color);
  });

  const explainY = 466;
  rect(32, explainY, 1836, 690);
  text(52, explainY + 34, "Leitura da divergencia", { size: 23, weight: 800, fill: "#17324d" });
  text(1828, explainY + 34, explanation.status || "", { size: 18, weight: 800, fill: explanation.quantityClosed ? "#087443" : "#c93535", anchor: "end" });
  wrapText(explanation.message || "", 175).slice(0, 2).forEach((line, idx) => text(52, explainY + 66 + idx * 22, line, { size: 17, fill: "#667085", weight: 600 }));
  const smallW = (1796 - gap * 3) / 4;
  [
    ["Saldo por quantidade", `${formatQtyBr(totals.divergenciaQtd)} un.`, `${formatQtyBr(totals.divergenciaQtdItens)} item(ns) com diferenca de quantidade.`, valueColor(totals.divergenciaQtd)],
    ["Saldo por valor", formatMoneyBr(totals.divergenciaValor), `${formatQtyBr(totals.divergenciaCustoItens)} item(ns) explicados por mudanca de custo.`, valueColor(totals.divergenciaValor)],
    ["Diferenca por custo", formatMoneyBr(totals.divergenciaCustoValor), "Valor com quantidade fechada e custo diferente.", valueColor(totals.divergenciaCustoValor)],
    ["Diferenca por quantidade", formatMoneyBr(totals.divergenciaQtdValor), "Valor ligado a item cuja quantidade ainda nao fechou.", valueColor(totals.divergenciaQtdValor)],
  ].forEach(([title, value, detail, color], idx) => smallCard(52 + idx * (smallW + gap), explainY + 100, smallW, title, value, detail, color));

  text(52, explainY + 214, "Maiores diferencas por custo", { size: 21, weight: 800, fill: "#17324d" });
  const costRows = (explanation.topCusto || []).slice(0, 5);
  add(`<rect x="52" y="${explainY + 236}" width="1796" height="36" fill="#eaf2f8" stroke="#eaf2f8"/>`);
  ["SKU", "Descricao", "Dif valor", "Dif qtd", "Custo inicial", "Custo final"].forEach((header, idx) => text([70, 250, 1000, 1190, 1460, 1720][idx], explainY + 260, header, { size: 16, weight: 800, fill: "#17324d" }));
  costRows.forEach((row, idx) => {
    const y = explainY + 304 + idx * 30;
    add(`<line x1="52" y1="${y - 22}" x2="1848" y2="${y - 22}" stroke="#edf2f6"/>`);
    text(70, y, row.sku || "", { size: 16 });
    text(250, y, String(row.descricao || "").slice(0, 58), { size: 16 });
    text(1065, y, formatMoneyBr(row.diferenca_valor), { size: 16, fill: valueColor(row.diferenca_valor), anchor: "end" });
    text(1245, y, formatQtyBr(row.diferenca_qtd), { size: 16, anchor: "end" });
    text(1545, y, formatMoneyBr(row.custo_inicial), { size: 16, anchor: "end" });
    text(1830, y, formatMoneyBr(row.custo_final), { size: 16, anchor: "end" });
  });
  text(52, explainY + 456, "Explicacao das diferencas de quantidade", { size: 21, weight: 800, fill: "#17324d" });
  const qtyRows = (explanation.topQtd || []).slice(0, 5);
  add(`<rect x="52" y="${explainY + 478}" width="1796" height="36" fill="#eaf2f8" stroke="#eaf2f8"/>`);
  ["SKU", "Descricao", "Qtd calc.", "Qtd export.", "Dif qtd", "Dif valor", "Motivo"].forEach((header, idx) => text([70, 190, 520, 660, 805, 930, 1060][idx], explainY + 502, header, { size: 16, weight: 800, fill: "#17324d" }));
  qtyRows.forEach((row, idx) => {
    const y = explainY + 548 + idx * 30;
    add(`<line x1="52" y1="${y - 22}" x2="1848" y2="${y - 22}" stroke="#edf2f6"/>`);
    text(70, y, row.sku || "", { size: 16 });
    text(190, y, String(row.descricao || "").slice(0, 30), { size: 16 });
    text(595, y, formatQtyBr(row.qtd_final_calculado), { size: 16, anchor: "end" });
    text(750, y, formatQtyBr(row.qtd_final_exportado), { size: 16, anchor: "end" });
    text(860, y, formatQtyBr(row.diferenca_qtd), { size: 16, fill: valueColor(row.diferenca_qtd), anchor: "end" });
    text(1015, y, formatMoneyBr(row.diferenca_valor), { size: 16, anchor: "end" });
    text(1060, y, String(row.motivo || "").slice(0, 88), { size: 15 });
  });

  const originRows = origins.map((row) => [
    ({ NOTAS_CD: "NOTAS CD", ENTRADAS_NF: "ENTRADAS NF", DEVOLUCAO_CD: "DEVOLUCAO CD", VENDA_CUPOM: "VENDAS CUPOM" }[row.origem] || row.origem || ""),
    formatQtyBr(row.linhas),
    formatQtyBr(row.qtd_movimento),
    formatMoneyBr(row.valor_movimento_custo),
  ]);
  if (origins.length) {
    originRows.push([
      "TOTAL",
      formatQtyBr(origins.reduce((total, row) => total + number(row.linhas), 0)),
      formatQtyBr(origins.reduce((total, row) => total + number(row.qtd_movimento), 0)),
      formatMoneyBr(origins.reduce((total, row) => total + number(row.valor_movimento_custo), 0)),
    ]);
  }
  table(32, 1184, 1010, 360, "Movimentos por origem", ["Origem", "Linhas", "Qtd Movimento", "Valor Movimento"], originRows, [360, 160, 230, 230], ["start", "end", "end", "end"]);
  table(1062, 1184, 806, 420, "Conferencia do estoque", ["Indicador", "Valor"], [
    ["Data estoque inicial", stockDates.initial || "-"],
    ["Data estoque final", stockDates.final || "-"],
    ["Estoque inicial", formatMoneyBr(totals.estoqueInicialValor)],
    ["Movimentos", formatMoneyBr(totals.movimentoValor)],
    ["Estoque esperado", formatMoneyBr(totals.esperadoValor)],
    ["Estoque final 22:30", formatMoneyBr(totals.finalValor)],
    ["Final - esperado", formatMoneyBr(totals.divergenciaValor)],
    ["Fonte inicial", stockSources.initial || "-"],
    ["Fonte final", stockSources.final || "-"],
  ], [380, 390], ["start", "end"]);
  text(1868, 1688, `Gerado em ${new Date().toLocaleString("pt-BR")}`, { size: 13, fill: "#667085", anchor: "end" });
  add("</svg>");
  return parts.join("");
}

async function writeExcelFallback(runName) {
  const output = path.join(EXCEL_DIR, `pleno_auditoria_${runName}.xls`);
  const sections = [];
  const summary = await auditSummary(runName);
  sections.push(`
    <h1>Resumo auditoria Pleno - ${escapeHtml(runName)}</h1>
    <table>
      <tr><th>Indicador</th><th>Quantidade</th><th>Valor</th></tr>
      <tr><td>Estoque inicial</td><td>${summary.totals.estoqueInicialQtd}</td><td>${summary.totals.estoqueInicialValor}</td></tr>
      <tr><td>Movimento total</td><td>${summary.totals.movimentoQtd}</td><td>${summary.totals.movimentoValor}</td></tr>
      <tr><td>Estoque final Pleno</td><td>${summary.totals.finalQtd}</td><td>${summary.totals.finalValor}</td></tr>
      <tr><td>Divergencia</td><td>${summary.totals.divergenciaQtd}</td><td>${summary.totals.divergenciaValor}</td></tr>
      <tr><td>Vendas cupom</td><td>${summary.totals.vendasQtd}</td><td>${summary.totals.vendasValor}</td></tr>
      <tr><td>Saidas loja/CD</td><td>${summary.totals.saidasCdQtd}</td><td>${summary.totals.saidasCdValor}</td></tr>
      <tr><td>Pedidos pendentes</td><td>${summary.totals.pedidos}</td><td>${summary.totals.pedidosValor}</td></tr>
    </table>
  `);
  for (const [key, title] of auditTables) {
    const data = await tableData(runName, key);
    const rows = data.rows;
    sections.push(`
      <h2>${escapeHtml(title)}</h2>
      <table>
        <tr>${data.headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr>
        ${rows.map((row) => `<tr>${data.headers.map((header) => `<td>${escapeHtml(row[header])}</td>`).join("")}</tr>`).join("")}
      </table>
    `);
  }
  const html = `<!doctype html><html><head><meta charset="utf-8"><style>
    body{font-family:Arial,sans-serif} table{border-collapse:collapse;margin-bottom:24px}
    th{background:#d9eaf7;color:#17324d} th,td{border:1px solid #d9e2ea;padding:4px 6px}
  </style></head><body>${sections.join("\n")}</body></html>`;
  await fs.writeFile(output, html, "utf8");
  return output;
}

async function sendFile(res, filePath, downloadName) {
  const stat = await fs.stat(filePath);
  res.writeHead(200, {
    "content-length": stat.size,
    "content-disposition": `attachment; filename="${downloadName}"`,
    "content-type": "application/octet-stream",
  });
  createReadStream(filePath).pipe(res);
}

async function sendInlineFile(res, filePath, downloadName, contentType) {
  const stat = await fs.stat(filePath);
  res.writeHead(200, {
    "content-length": stat.size,
    "content-disposition": `inline; filename="${downloadName}"`,
    "content-type": contentType,
  });
  createReadStream(filePath).pipe(res);
}

async function tesourariaCofreAnexo(searchParams) {
  const fileName = path.basename(searchParams.get("file") || "");
  const extension = path.extname(fileName).toLowerCase();
  const contentTypes = { ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png" };
  if (!fileName || !contentTypes[extension]) throw new Error("Arquivo anexo invalido.");
  const filePath = path.resolve(TESOURARIA_COFRE_DIR, fileName);
  if (!filePath.startsWith(`${TESOURARIA_COFRE_DIR}${path.sep}`)) throw new Error("Arquivo anexo invalido.");
  return { filePath, fileName, contentType: contentTypes[extension] };
}

async function tesourariaCofreSummary(searchParams) {
  const store = searchParams.get("store") || "all";
  const pendingOnly = searchParams.get("pendingOnly") === "1";
  const status = searchParams.get("status") || "all";
  const errorFilter = searchParams.get("error") || "all";
  const plenoSnapshotScript = path.join(ROOT, "scripts", "tesouraria_cofre_pleno.py");
  const statusScript = path.join(ROOT, "scripts", "tesouraria_cofre_status.py");
  let execution = null;
  try { execution = JSON.parse(await fs.readFile(path.join(TESOURARIA_COFRE_DIR, "execucao.json"), "utf8")); } catch {}
  const openTransfers = JSON.parse((await runCommand(PYTHON_BIN, [plenoSnapshotScript, "--db", TESOURARIA_COFRE_DB, "cached-open-transfers"])).stdout);
  // Keep the latest completed run visible until a new run updates its heartbeat.
  const lastRunAt = execution?.updatedAt ? new Date(execution.updatedAt) : null;
  const activityDate = lastRunAt && !Number.isNaN(lastRunAt.getTime())
    ? isoLocal(lastRunAt).slice(0, 10)
    : isoLocal(new Date()).slice(0, 10);
  const activity = JSON.parse((await runCommand(PYTHON_BIN, [statusScript, "--db", TESOURARIA_COFRE_DB, "recent-processes", "--closing-date", activityDate, "--limit", "500"])).stdout);
  const activityByTransaction = new Map(activity.map((row) => [Number(row.transaction_id), row]));
  const errorOrigin = (row) => {
    const text = `${row.errorStage || ""} ${row.errorMessage || ""}`.toLowerCase();
    if (/brinks|painel|sigla|relat|download|\.pdf/.test(text)) return "brinks";
    if (/\bocr\b|imagem|foto|comprovante/.test(text)) return "ocr";
    return "pleno";
  };
  const openTransactionIds = new Set(openTransfers.map((row) => Number(row.id)));
  let records = openTransfers.map((row) => {
    const activityRow = activityByTransaction.get(Number(row.id));
    return ({
    transactionId: row.id, storeCode: String(row.store).match(/^\d+/)?.[0] || "", storeName: String(row.store).replace(/^\d+\s*-\s*/, ""),
    plannedDate: String(row.planned).split("/").reverse().join("-"), performedDate: null, closingDate: null, closedAt: null,
    startedAt: null, value: row.value, ocrValue: null, brinksValue: null, status: activityRow?.status || "em_aberto", errorStage: activityRow?.error_stage || null,
    brinksStatus: null, errorMessage: activityRow?.error_message || null, updatedAt: activityRow?.updated_at || null, pdfFile: activityRow?.pdf_file || null, evidenceFile: activityRow?.evidence_file || null,
    plenoFile: activityRow?.pleno_file || null, brinksFile: activityRow?.brinks_file || null, validation: {},
  });
  });
  const historicalCards = activity
    .filter((row) => !openTransactionIds.has(Number(row.transaction_id)))
    .map((row) => ({
      transactionId: row.transaction_id,
      storeCode: String(row.store_code || ""),
      storeName: row.store_name || "",
      plannedDate: row.planned_date || null,
      performedDate: row.performed_date || null,
      closingDate: row.closing_date || null,
      closedAt: row.closed_at || null,
      startedAt: row.started_at || null,
      value: row.value || 0,
      ocrValue: row.ocr_value,
      brinksValue: row.brinks_value,
      brinksStatus: row.brinks_status || null,
      status: row.status,
      errorStage: row.error_stage || null,
      errorMessage: row.error_message || null,
      updatedAt: row.updated_at || null,
      pdfFile: row.pdf_file || null,
      evidenceFile: row.evidence_file || null,
      plenoFile: row.pleno_file || null,
      brinksFile: row.brinks_file || null,
      validation: {
        receiptDatesMatch: row.receipt_dates_match == null ? null : Boolean(row.receipt_dates_match),
        receiptValueMatch: row.receipt_value_match == null ? null : Boolean(row.receipt_value_match),
        brinksDatesMatch: row.brinks_dates_match == null ? null : Boolean(row.brinks_dates_match),
        brinksValueMatch: row.brinks_value_match == null ? null : Boolean(row.brinks_value_match),
      },
    }));
  records = [...records, ...historicalCards];
  if (store !== "all") records = records.filter((row) => row.storeCode === store);
  if (status !== "all") records = records.filter((row) => row.status === status);
  if (errorFilter !== "all") records = records.filter((row) => row.errorMessage && errorOrigin(row) === errorFilter);
  if (pendingOnly) records = records.filter((row) => row.status !== "concluido");
  const stores = [...new Map(records.map((row) => [row.storeCode, { code: row.storeCode, name: row.storeName }])).values()].sort((a, b) => Number(a.code) - Number(b.code));
  const approved = records.filter((row) => ["concluido", "cancelado_duplicidade", "ja_liquidada"].includes(row.status)).length;
  return {
    plannedDate: null, startDate: null, endDate: null, store, stores, records, activity,
    totals: {
      processed: records.length,
      approved,
      attention: records.length - approved,
      totalValue: records.filter((row) => row.status === "concluido").reduce((sum, row) => sum + Number(row.value || 0), 0),
    },
    execution,
  };
}

async function tesourariaCofreExecution() {
  try { return JSON.parse(await fs.readFile(path.join(TESOURARIA_COFRE_DIR, "execucao.json"), "utf8")); } catch { return null; }
}

async function prevencaoPerdasExecution() {
  try { return JSON.parse(await fs.readFile(path.join(PREVENCAO_PERDAS_DIR, "execucao.json"), "utf8")); } catch { return null; }
}

async function prevencaoPerdasAnexo(searchParams) {
  const fileName = path.basename(searchParams.get("file") || "");
  if (!fileName || !/\.(png|jpe?g)$/i.test(fileName)) throw new Error("Arquivo anexo invalido.");
  const filePath = path.resolve(PREVENCAO_PERDAS_DIR, fileName);
  if (!filePath.startsWith(`${PREVENCAO_PERDAS_DIR}${path.sep}`)) throw new Error("Arquivo anexo invalido.");
  const contentType = /\.png$/i.test(fileName) ? "image/png" : "image/jpeg";
  return { filePath, fileName, contentType };
}

async function prevencaoPerdasSummary(searchParams) {
  const status = searchParams.get("status") || "all";
  const filial = searchParams.get("filial") || "all";
  const runDate = searchParams.get("runDate") || null;
  const statusScript = path.join(ROOT, "scripts", "prevencao_perdas_status.py");
  const result = await runCommand(PYTHON_BIN, [statusScript, "--db", PREVENCAO_PERDAS_DB, "summary", "--status", status, "--filial", filial, ...(runDate ? ["--run-date", runDate] : [])]);
  let execution = null;
  try { execution = JSON.parse(await fs.readFile(path.join(PREVENCAO_PERDAS_DIR, "execucao.json"), "utf8")); } catch {}
  return { ...JSON.parse(result.stdout), execution };
}

async function tesourariaCofreAnalytics(searchParams) {
  const plannedDate = searchParams.get("plannedDate") || new Date().toISOString().slice(0, 10);
  const startDate = searchParams.get("startDate") || plannedDate;
  const endDate = searchParams.get("endDate") || plannedDate;
  const snapshotScript = path.join(ROOT, "scripts", "tesouraria_cofre_pleno.py");
  const statusScript = path.join(ROOT, "scripts", "tesouraria_cofre_status.py");
  const result = await runCommand(PYTHON_BIN, [statusScript, "--db", TESOURARIA_COFRE_DB, "analytics", "--start-date", startDate, "--end-date", endDate]);
  const openDates = await runCommand(PYTHON_BIN, [snapshotScript, "--db", TESOURARIA_COFRE_DB, "cached-open-dates", "--start-date", startDate, "--end-date", endDate]);
  const pendingDates = JSON.parse(openDates.stdout);
  const ranking = await runCommand(PYTHON_BIN, [statusScript, "--db", TESOURARIA_COFRE_DB, "problem-ranking", "--dates", pendingDates.map((item) => item.plannedDate).join(",")]);
  return { ...JSON.parse(result.stdout), openDates: pendingDates, problemRanking: JSON.parse(ranking.stdout) };
}

function sendBuffer(res, buffer, downloadName, contentType) {
  res.writeHead(200, {
    "content-length": buffer.length,
    "content-disposition": `attachment; filename="${downloadName}"`,
    "content-type": contentType,
  });
  res.end(buffer);
}

async function route(req, res) {
  const requestUrl = String(req.url || "/").replace(/^\/{2,}/, "/");
  const url = new URL(requestUrl, `http://${req.headers.host}`);
  if (url.pathname === "/cws-consumo-monitor.html") {
    res.writeHead(302, { location: "/pdv-consumo-monitor.html", "cache-control": "no-store" });
    return res.end();
  }
  if (url.pathname === "/api/business-monitor/cws-consumo" && req.method === "GET") {
    res.writeHead(308, { location: "/api/business-monitor/pdv-consumo", "cache-control": "no-store" });
    return res.end();
  }

  url.pathname = url.pathname.replace(/\/{2,}/g, "/");
  if (await exportRoutes(req, res, url)) return;
  if (url.pathname === "/api/runs") return sendJson(res, 200, { runs: await listRuns(), snapshots: await listSnapshots() });
  if (url.pathname === "/api/tesouraria/cofre-inteligente/execution") return sendJson(res, 200, await tesourariaCofreExecution());
  if (url.pathname === "/api/tesouraria/cofre-inteligente/run" && req.method === "POST") {
    const result = await startTesourariaCofreRun();
    return sendJson(res, result.started ? 202 : 409, result);
  }
  if (url.pathname === "/api/tesouraria/cofre-inteligente/anexo") {
    const anexo = await tesourariaCofreAnexo(url.searchParams);
    return sendInlineFile(res, anexo.filePath, anexo.fileName, anexo.contentType);
  }
  if (url.pathname === "/api/tesouraria/cofre-inteligente") return sendJson(res, 200, await tesourariaCofreSummary(url.searchParams));
  if (url.pathname === "/api/tesouraria/cofre-inteligente/indicadores") return sendJson(res, 200, await tesourariaCofreAnalytics(url.searchParams));
  if (url.pathname === "/api/prevencao-perdas/execution") return sendJson(res, 200, await prevencaoPerdasExecution());
  if (url.pathname === "/api/prevencao-perdas/run" && req.method === "POST") {
    const result = await startPrevencaoPerdasRun();
    return sendJson(res, result.started ? 202 : 409, result);
  }
  if (url.pathname === "/api/prevencao-perdas/anexo") {
    const anexo = await prevencaoPerdasAnexo(url.searchParams);
    return sendInlineFile(res, anexo.filePath, anexo.fileName, anexo.contentType);
  }
  if (url.pathname === "/api/prevencao-perdas") return sendJson(res, 200, await prevencaoPerdasSummary(url.searchParams));
  if (url.pathname === "/api/cron-monitor") return sendJson(res, 200, await cronMonitorSummary());
  if (url.pathname === "/api/business-monitor/pedidos") return sendJson(res, 200, await pedidosBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/pedidos/refresh" && req.method === "POST") return sendJson(res, 200, await refreshPedidosDiaflexMonitor());
  if (url.pathname === "/api/business-monitor/promopreco") return sendJson(res, 200, await promoprecoBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/estoque-relex") return sendJson(res, 200, await estoqueRelexBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/retificacao-ret") return sendJson(res, 200, await retificacaoRetBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/notas-rejeitadas") return sendJson(res, 200, await notasRejeitadasBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/notas-rejeitadas/xml") return sendJson(res, 200, await notaRejeitadaXml(url.searchParams));
  if (url.pathname === "/api/business-monitor/devolucao-as400") return sendJson(res, 200, await devolucaoAs400BusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/mercadoria-filial") return sendJson(res, 200, await mercadoriaFilialBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/sg-estoque-custo") return sendJson(res, 200, await sgEstoqueCustoBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/pdv-processes") return sendJson(res, 200, await pdvProcessBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/pdv-queue") return sendJson(res, 200, await pdvQueueBusinessMonitorSummary());
  if (["/api/business-monitor/pdv-consumo/refresh", "/api/business-monitor/cws-consumo/refresh"].includes(url.pathname) && req.method === "POST") {
    try {
      if (!pdvConsumoRefreshPromise) {
        pdvConsumoRefreshPromise = runCommand("python3", [path.join(ROOT, "scripts", "update_pdv_consumo_monitor.py")], {
          timeout: 55000, killSignal: "SIGKILL",
        }).finally(() => { pdvConsumoRefreshPromise = null; });
      }
      await pdvConsumoRefreshPromise;
      const snapshot = await pdvConsumoBusinessMonitorSummary();
      return sendJson(res, 200, { ...snapshot, refreshed: snapshot.status === "ok" });
    } catch {
      const snapshot = await pdvConsumoBusinessMonitorSummary();
      return sendJson(res, 503, { ...snapshot, refreshed: false,
        error: "Não foi possível concluir a coleta ARIUS. Tente novamente após a coleta em andamento." });
    }
  }
  if (url.pathname === "/api/business-monitor/pdv-consumo" && req.method === "GET") return sendJson(res, 200, await pdvConsumoBusinessMonitorSummary());
  if (url.pathname === "/api/business-monitor/alert-policy" && req.method === "GET") return sendJson(res, 200, await nocAlertPolicyConfig());
  if (url.pathname === "/api/business-monitor/alert-policy" && req.method === "POST") return sendJson(res, 200, await saveNocAlertPolicy(req));
  if (url.pathname === "/api/business-monitor/alert-acknowledgements" && req.method === "GET") return sendJson(res, 200, await nocAlertAcknowledgements());
  if (url.pathname === "/api/business-monitor/alert-acknowledgements" && req.method === "POST") return sendJson(res, 200, await saveNocAlertAcknowledgement(req));
  if (url.pathname === "/api/business-monitor/process-resources") return sendJson(res, 200, await processResourcesMonitorSummary());
  if (url.pathname === "/api/business-monitor/sap-api") return sendJson(res, 200, await sapApiMonitorSummary());
  if (url.pathname === "/api/business-monitor/sap-api/routing" && req.method === "GET") return sendJson(res, 200, await sapApiRoutingRules());
  if (url.pathname === "/api/business-monitor/sap-api/routing" && req.method === "POST") return sendJson(res, 200, await saveSapApiRouting(req));
  if (url.pathname === "/api/business-monitor/sap-api/google-chat" && req.method === "GET") return sendJson(res, 200, await sapApiGoogleChatConfig());
  if (url.pathname === "/api/business-monitor/sap-api/google-chat" && req.method === "POST") return sendJson(res, 200, await saveSapApiGoogleChatConfig(req));
  if (url.pathname === "/api/business-monitor/sap-api/google-chat/send" && req.method === "POST") return sendJson(res, 200, await sendSapApiGoogleChatMemo(req));
  if (url.pathname === "/api/business-monitor/sap-api/details") return sendJson(res, 200, await sapApiTransactionDetails(url.searchParams));
  if (url.pathname === "/api/business-monitor/sap-api/manual-search") return sendJson(res, 200, await sapApiManualErrorSearch(url.searchParams));
  if (url.pathname === "/api/business-monitor/checkin-notas") return sendJson(res, 200, await checkinNotasMonitorSummary());
  if (url.pathname === "/api/business-monitor/inventario-contagem") return sendJson(res, 200, await inventarioContagemMonitorSummary(url.searchParams));
  if (url.pathname.startsWith("/api/runs/")) {
    const store = url.searchParams.get("store") || "";
    const [, , , runName, resource, key] = url.pathname.split("/");
    if (resource === "tables") return sendJson(res, 200, await tableData(decodeURIComponent(runName), key, { store }));
    return sendJson(res, 200, await auditSummary(decodeURIComponent(runName), { store }));
  }
  if (url.pathname === "/api/import" && req.method === "POST") {
    return sendJson(res, 200, { imported: await importUploads(req) });
  }
  if (url.pathname.startsWith("/api/export/excel/")) {
    const runName = decodeURIComponent(url.pathname.split("/").pop());
    const file = await ensureExcel(runName);
    return sendFile(res, file, path.basename(file));
  }
  if (url.pathname.startsWith("/api/export/summary-image/")) {
    const runName = safeRunName(decodeURIComponent(url.pathname.split("/").pop()));
    const store = url.searchParams.get("store") || "";
    const svg = summaryImageSvg(await auditSummary(runName, { store }));
    return sendBuffer(
      res,
      Buffer.from(svg, "utf8"),
      `resumo_auditoria_${runName}${store && store !== "all" ? `_loja_${store}` : ""}.svg`,
      "image/svg+xml; charset=utf-8",
    );
  }
  if (url.pathname.startsWith("/api/export/package/")) {
    const runName = safeRunName(decodeURIComponent(url.pathname.split("/").pop()));
    const packagePath = path.join(RECEIVED_DIR, `${runName}.tar.gz`);
    try {
      await fs.access(packagePath);
      return sendFile(res, packagePath, path.basename(packagePath));
    } catch {
      const tempPath = path.join(RECEIVED_DIR, `${runName}.tar.gz`);
      await runCommand("tar", ["-czf", tempPath, "-C", AUDIT_DIR, runName]);
      return sendFile(res, tempPath, path.basename(tempPath));
    }
  }

  // API misses must never fall through to static files or expose filesystem paths.
  if (url.pathname === "/api" || url.pathname.startsWith("/api/")) {
    return sendJson(res, 404, { error: "Rota de API não encontrada.", errorCode: "API_NOT_FOUND" });
  }

  const pageAliases = new Map([
    ["/auditoria-pleno", "index.html"],
    ["/auditoria-pleno/", "index.html"],
    ["/auditoria-pleno/inventario-contagem", "inventario-contagem-monitor.html"],
    ["/auditoria-pleno/inventario-contagem/", "inventario-contagem-monitor.html"],
  ]);
  const file = pageAliases.get(url.pathname) || (url.pathname === "/" ? "index.html" : url.pathname.slice(1));
  const filePath = path.resolve(PUBLIC_DIR, file);
  if (!filePath.startsWith(PUBLIC_DIR)) throw new Error("Arquivo invalido.");
  const ext = path.extname(filePath);
  const contentType = ext === ".css" ? "text/css" : ext === ".js" ? "text/javascript" : "text/html";
  const content = await fs.readFile(filePath);
  res.writeHead(200, {
    "content-type": `${contentType}; charset=utf-8`,
    "cache-control": "no-store, no-cache, must-revalidate, proxy-revalidate",
    "pragma": "no-cache",
    "expires": "0",
  });
  res.end(content);
}

const server = createServer((req, res) => {
  route(req, res).catch((error) => {
    console.error(error);
    sendJson(res, 500, { error: error.message });
  });
});

server.listen(PORT, HOST, () => {
  console.log(`Auditoria Pleno: http://${HOST}:${PORT}`);
  console.log(`Monitor recebidos_servidor: varredura a cada ${Math.round(RECEIVED_SCAN_INTERVAL_MS / 60000)} minuto(s).`);
  startReceivedServerMonitor();
startSapApiMonitor();
startSapApiGoogleChatDispatch();
startCheckinNotasMonitor();
});

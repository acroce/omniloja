#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const DEFAULT_RUN_DIR = path.join(ROOT, "outputs", "pleno_stock_audit", "2026-07-06_lojas_259");
const DEFAULT_OUTPUT_DIR = path.join(ROOT, "outputs", "pleno_stock_audit_excel");

const expectedHeaders = {
  notas_entrada: [
    "loja",
    "nome_loja",
    "nota_id",
    "nota",
    "serie",
    "data_emissao",
    "data_entrada",
    "valor_nf",
    "sku",
    "descricao",
    "qtd_nota",
    "valor_item_nota",
    "movimentos_estoque",
  ],
  notas_pendentes_entrada: [
    "loja",
    "nome_loja",
    "nota_id",
    "nota",
    "serie",
    "data_emissao",
    "data_entrada",
    "dias_pendente",
    "valor_nf",
    "itens",
    "qtd_total",
    "valor_itens",
    "movimentos_estoque",
    "situacao",
  ],
  notas_saida: [
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
  inventarios: [
    "loja",
    "nome_loja",
    "inventario_id",
    "descricao_inventario",
    "data_inventario",
    "data_criacao",
    "inicio",
    "fim",
    "fechado",
    "cancelado",
    "itens",
    "qtd_sistema",
    "valor_sistema_custo",
    "qtd_contagem",
    "valor_contagem_custo",
    "valor_contado_custo",
    "diferenca_qtd",
    "diferenca_valor_custo",
  ],
  inventario_itens: [
    "loja",
    "nome_loja",
    "inventario_id",
    "data_inventario",
    "data_criacao",
    "sku",
    "descricao",
    "qtd_sistema",
    "valor_sistema_custo",
    "qtd_contagem",
    "valor_contagem_custo",
    "valor_contado_custo",
    "diferenca_qtd",
    "diferenca_valor_custo",
    "origem_pacote",
  ],
  retificacoes: [
    "loja",
    "nome_loja",
    "retificacao_id",
    "nota",
    "data_nf",
    "albaran",
    "data_albaran",
    "tipo_operacao",
    "aprovado",
    "exportacao_pleno",
    "importacao_pleno",
    "sku",
    "descricao",
    "qtd_embalagem",
    "qtd_unidade",
    "nota_item_id",
    "nota_pleno",
    "serie_pleno",
    "data_emissao_pleno",
    "data_entrada_pleno",
  ],
};

const sheetSpecs = [
  {
    key: "conciliacao_sku",
    file: "conciliacao_sku.csv",
    sheet: "Estoque Final",
    title: "Conferencia de estoque final por SKU",
  },
  {
    key: "vendas_sku",
    file: "vendas_sku.csv",
    sheet: "Vendas",
    title: "Vendas por item",
  },
  {
    key: "movimentos_resumo",
    file: "movimentos_resumo.csv",
    sheet: "Resumo Mov",
    title: "Resumo de movimentos por origem",
  },
  {
    key: "notas_entrada",
    file: "notas_entrada.csv",
    sheet: "Entradas NF",
    title: "Entradas de notas por item",
  },
  {
    key: "notas_cd",
    file: "notas_cd.csv",
    sheet: "Notas CD",
    title: "Notas emitidas pelo CD por item",
  },
  {
    key: "notas_saida",
    file: "notas_saida.csv",
    sheet: "NF Saida",
    title: "Notas fiscais de saida da loja por item",
  },
  {
    key: "notas_pendentes_entrada",
    file: "notas_pendentes_entrada.csv",
    sheet: "NF Pendente",
    title: "Notas no Pleno sem check-in de entrada",
  },
  {
    key: "movimentos_causa",
    file: "movimentos_estoque.csv",
    sheet: "Mov Causa",
    title: "Notas de saida da loja para o CD",
    filter: (row) => row.origem === "NF_S",
  },
  {
    key: "autoconsumo",
    file: "movimentos_estoque.csv",
    sheet: "Autoconsumo",
    title: "Autoconsumo da loja",
    filter: (row) =>
      (row.origem === "BOLETIM" || row.origem === "AUTOCONSUMO")
      && Number(row.qtd_movimento || 0) < 0,
  },
  {
    key: "movimentos_sem_causa",
    file: "movimentos_estoque.csv",
    sheet: "Mov Sem Causa",
    title: "Movimentacoes sem causa classificada",
    filter: (row) => row.origem === "SEM_CAUSA",
  },
  {
    key: "top_movimentos",
    file: "top_movimentos.csv",
    sheet: "Top Mov",
    title: "Maiores movimentos por valor",
  },
  {
    key: "pedidos_transferencia",
    file: "pedidos_transferencia.csv",
    sheet: "Pedidos",
    title: "Pedidos de transferencia",
  },
  {
    key: "pedido_nota_divergencia",
    file: "pedido_nota_divergencia.csv",
    sheet: "Pedido x Nota",
    title: "Divergencias entre pedido e nota recebida",
  },
  {
    key: "retificacoes",
    file: "retificacoes.csv",
    sheet: "Retificacoes",
    title: "Retificacoes de recebimento",
  },
  {
    key: "inventarios",
    file: "inventarios.csv",
    sheet: "Inventario",
    title: "Inventarios do periodo",
  },
  {
    key: "inventario_itens",
    file: "inventario_itens.csv",
    sheet: "Itens Inventario",
    title: "Itens contados no inventario",
  },
];

const numericHeaders = new Set([
  "itens",
  "dias_pendente",
  "retificacao_id",
  "albaran",
  "nota_item_id",
  "nota_pleno",
  "linhas",
  "cupons",
  "qtd_inicio",
  "qtd_fim",
  "qtd_fim_esperado",
  "qtd_fim_pleno",
  "qtd_movimento",
  "qtd_movimento_auditoria",
  "qtd_inventario_ja_no_inicio",
  "qtd_vendida",
  "qtd_vendida_cupom",
  "qtd_venda_movimento",
  "qtd_nf_entrada_movimento",
  "qtd_inventario_movimento",
  "qtd_sem_causa_movimento",
  "qtd_vendida_estoque_diario",
  "qtd_nota",
  "qtd_nota_cd",
  "qtd_nota_saida",
  "qtd_total",
  "qtd_embalagem",
  "qtd_unidade",
  "qtd_pedida",
  "qtd_confirmada",
  "qtd_nf",
  "qtd_ruptura_pedido",
  "qtd_extra_nota",
  "qtd_sistema",
  "qtd_contagem",
  "divergencia_qtd",
  "diferenca_qtd",
  "variacao_qtd",
  "custo_inicio",
  "custo_fim",
]);

const moneyHeaders = new Set([
  "valor_inicio_custo",
  "valor_fim_custo",
  "valor_movimento_custo",
  "valor_movimento_auditoria",
  "valor_inventario_ja_no_inicio",
  "valor_fim_esperado_custo",
  "valor_fim_pleno_custo",
  "valor_vendido",
  "valor_vendido_cupom",
  "valor_venda_movimento_custo",
  "valor_nf_entrada_movimento",
  "valor_inventario_movimento",
  "valor_sem_causa_movimento",
  "valor_venda_estoque_diario",
  "valor_nf",
  "valor_item_nota",
  "valor_nota_cd",
  "valor_nota_saida",
  "valor_itens",
  "valor_pedido_custo_atual",
  "valor_confirmado_custo_atual",
  "valor_nf_custo_atual",
  "valor_ruptura_pedido",
  "valor_sistema_custo",
  "valor_contagem_custo",
  "valor_contado_custo",
  "valor_inicio_custo",
  "valor_fim_custo",
  "divergencia_valor_custo",
  "diferenca_valor_custo",
  "variacao_valor_custo",
]);

const dateHeaders = new Set([
  "data_movimento",
  "data_emissao",
  "data_entrada",
  "data_pedido",
  "data_inventario",
  "data_nf",
  "data_albaran",
  "exportacao_pleno",
  "importacao_pleno",
  "data_emissao_pleno",
  "data_entrada_pleno",
  "inicio",
  "fim",
]);

function parseArgs() {
  const args = process.argv.slice(2);
  const result = {
    runDir: DEFAULT_RUN_DIR,
    outputDir: DEFAULT_OUTPUT_DIR,
  };
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === "--run-dir") {
      result.runDir = path.resolve(args[++i]);
    } else if (args[i] === "--output-dir") {
      result.outputDir = path.resolve(args[++i]);
    } else {
      throw new Error(`Opcao desconhecida: ${args[i]}`);
    }
  }
  return result;
}

function parseCsv(text) {
  if (!text.trim()) {
    return { headers: [], rows: [] };
  }
  const rows = [];
  let row = [];
  let cell = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(cell);
      cell = "";
    } else if (ch === "\n") {
      row.push(cell.replace(/\r$/, ""));
      rows.push(row);
      row = [];
      cell = "";
    } else {
      cell += ch;
    }
  }
  if (cell.length > 0 || row.length > 0) {
    row.push(cell.replace(/\r$/, ""));
    rows.push(row);
  }
  if (rows.length === 0) {
    return { headers: [], rows: [] };
  }
  const headers = rows[0];
  const objects = rows.slice(1).filter((items) => items.some((value) => value !== "")).map((items) => {
    const out = {};
    headers.forEach((header, idx) => {
      out[header] = items[idx] ?? "";
    });
    return out;
  });
  return { headers, rows: objects };
}

function toNumber(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function normalizeMovementSummary(rows, movementRows) {
  const normalized = rows.filter((row) => !["BOLETIM", "AUTOCONSUMO", "AUTOCONSUMO_ENTRADA"].includes(row.origem));
  const autoconsumoRows = movementRows.filter((row) =>
    (row.origem === "BOLETIM" || row.origem === "AUTOCONSUMO")
    && (toNumber(row.qtd_movimento) ?? 0) < 0
  );
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
    current.qtd_movimento += Math.abs(toNumber(row.qtd_movimento) ?? 0);
    current.valor_movimento_custo += Math.abs(toNumber(row.valor_movimento_custo) ?? 0);
    groups.set(key, current);
  }
  return [
    ...[...groups.values()].map((row) => ({
      ...row,
      qtd_movimento: Number(row.qtd_movimento.toFixed(3)),
      valor_movimento_custo: Number(row.valor_movimento_custo.toFixed(2)),
    })),
    ...normalized,
  ];
}

function notaSaidaRowsFromMovements(rows) {
  return rows
    .filter((row) => row.origem === "NF_S" && String(row.serie || "").trim() !== "1")
    .map((row) => ({
      loja: row.loja,
      nome_loja: row.nome_loja,
      data_movimento: row.data_movimento,
      nota: row.nota,
      serie: row.serie,
      entrada_saida: row.nota_entrada_saida || "S",
      sku: row.sku,
      descricao: row.descricao,
      qtd_nota_saida: Math.abs(toNumber(row.qtd_movimento) ?? 0).toFixed(3),
      valor_nota_saida: Math.abs(toNumber(row.valor_movimento_custo) ?? 0).toFixed(2),
      movimento_id: row.movimento_id,
      devolucao_codigos: row.devolucao_codigos,
      devolucao_causa_codigos: row.devolucao_causa_codigos,
      devolucao_causas: row.devolucao_causas,
      retificacao_ids: row.retificacao_ids,
      retificacao_albarans: row.retificacao_albarans,
    }));
}

function toTypedValue(header, value) {
  if (numericHeaders.has(header) || moneyHeaders.has(header)) {
    return toNumber(value);
  }
  if (dateHeaders.has(header) && value) {
    const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
    if (dateOnly) {
      return new Date(`${value}T00:00:00`);
    }
    return value;
  }
  return value === "" ? null : value;
}

function colLetter(index) {
  let n = index + 1;
  let letters = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    letters = String.fromCharCode(65 + rem) + letters;
    n = Math.floor((n - 1) / 26);
  }
  return letters;
}

function rangeFor(row, col, rowCount, colCount) {
  const start = `${colLetter(col)}${row}`;
  const end = `${colLetter(col + colCount - 1)}${row + rowCount - 1}`;
  return `${start}:${end}`;
}

function sumFormula(sheetName, columnLetter, firstRow, lastRow) {
  if (lastRow < firstRow) {
    return "=0";
  }
  return `=SUM('${sheetName}'!${columnLetter}${firstRow}:${columnLetter}${lastRow})`;
}

function sumDatasetHeaderFormula(dataBySheet, sheetName, header, firstRow, lastRow) {
  const dataset = dataBySheet.get(sheetName);
  const index = dataset?.headers.indexOf(header) ?? -1;
  if (index < 0) {
    return "=0";
  }
  return sumFormula(sheetName, colLetter(index), firstRow, lastRow);
}

function sumAbsDatasetHeaderFormula(dataBySheet, sheetName, header, firstRow, lastRow) {
  const dataset = dataBySheet.get(sheetName);
  const index = dataset?.headers.indexOf(header) ?? -1;
  if (!dataset || index < 0 || lastRow < firstRow) {
    return "=0";
  }
  const total = dataset.rows.reduce((acc, row) => acc + Math.abs(toNumber(row[header]) ?? 0), 0);
  return `=${Number(total.toFixed(6))}`;
}

function sumIfFormula(sheetName, criteriaCol, sumCol, firstRow, lastRow, criteria) {
  if (lastRow < firstRow) {
    return "=0";
  }
  return `=SUMIF('${sheetName}'!${criteriaCol}${firstRow}:${criteriaCol}${lastRow},"${criteria}",'${sheetName}'!${sumCol}${firstRow}:${sumCol}${lastRow})`;
}

async function readDataset(runDir, spec) {
  const csvPath = path.join(runDir, spec.file);
  const text = await fs.readFile(csvPath, "utf8").catch(() => "");
  let { headers, rows } = parseCsv(text);
  if (spec.key === "movimentos_resumo") {
    const movimentosText = await fs.readFile(path.join(runDir, "movimentos_estoque.csv"), "utf8").catch(() => "");
    const movimentos = parseCsv(movimentosText);
    rows = normalizeMovementSummary(rows, movimentos.rows);
  }
  if (spec.key === "inventario_itens" && rows.length === 0) {
    const movimentosText = await fs.readFile(path.join(runDir, "movimentos_estoque.csv"), "utf8").catch(() => "");
    const movimentos = parseCsv(movimentosText);
    headers = expectedHeaders.inventario_itens;
    rows = movimentos.rows.filter((row) => row.origem === "INVENTARIO").map((row) => ({
      loja: row.loja,
      nome_loja: row.nome_loja,
      inventario_id: row.inventario_id,
      data_inventario: row.data_movimento,
      sku: row.sku,
      descricao: row.descricao,
      qtd_sistema: "",
      valor_sistema_custo: "",
      qtd_contagem: "",
      valor_contagem_custo: "",
      valor_contado_custo: "",
      diferenca_qtd: "",
      diferenca_valor_custo: "",
      origem_pacote: "pacote_sem_contagem_por_item",
    }));
  }
  if (spec.key === "notas_saida" && rows.length === 0) {
    const movimentosText = await fs.readFile(path.join(runDir, "movimentos_estoque.csv"), "utf8").catch(() => "");
    const movimentos = parseCsv(movimentosText);
    headers = expectedHeaders.notas_saida;
    rows = notaSaidaRowsFromMovements(movimentos.rows);
  }
  if (headers.length === 0 && expectedHeaders[spec.key]) {
    headers = expectedHeaders[spec.key];
  }
  if (spec.filter) {
    rows = rows.filter(spec.filter);
  }
  return { ...spec, headers, rows };
}

function writeTitle(sheet, title, columnCount) {
  const titleRange = sheet.getRange("A1");
  titleRange.values = [[title]];
  titleRange.format.font = { color: "#17324D", bold: true, size: 14 };
  titleRange.format.rowHeight = 28;
}

function writeDatasetSheet(sheet, dataset) {
  sheet.showGridLines = false;
  writeTitle(sheet, dataset.title, dataset.headers.length || 6);

  const headers = dataset.headers;
  if (headers.length === 0) {
    sheet.getRange("A3").values = [["Sem dados no periodo"]];
    return;
  }

  const headerRange = sheet.getRange(rangeFor(3, 0, 1, headers.length));
  headerRange.values = [headers];
  headerRange.format.fill = { color: "#D9EAF7" };
  headerRange.format.font = { bold: true, color: "#17324D" };
  headerRange.format.borders = { preset: "outside", style: "thin", color: "#9FB7C9" };

  if (dataset.rows.length > 0) {
    const values = dataset.rows.map((row) => headers.map((header) => toTypedValue(header, row[header])));
    const dataRange = sheet.getRange(rangeFor(4, 0, values.length, headers.length));
    dataRange.values = values;
    dataRange.format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };
  } else {
    const emptyRange = sheet.getRange("A4:C4");
    emptyRange.values = [["Sem dados no periodo", null, null]];
    emptyRange.format.font = { italic: true, color: "#667085" };
  }

  headers.forEach((header, idx) => {
    const colRange = sheet.getRange(`${colLetter(idx)}4:${colLetter(idx)}${Math.max(4, dataset.rows.length + 3)}`);
    if (moneyHeaders.has(header)) {
      colRange.setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');
    } else if (numericHeaders.has(header)) {
      colRange.setNumberFormat('#,##0.000;[Red]-#,##0.000');
    } else if (dateHeaders.has(header) && header !== "data_pedido") {
      colRange.setNumberFormat("yyyy-mm-dd");
    }
  });

  sheet.freezePanes.freezeRows(3);
  const used = sheet.getUsedRange();
  used.format.autofitColumns();
  used.format.autofitRows();
}

function writeSummary(sheet, datasets, runName) {
  sheet.showGridLines = false;
  writeTitle(sheet, `Resumo auditoria Pleno - ${runName}`, 8);

  const dataBySheet = new Map(datasets.map((dataset) => [dataset.sheet, dataset]));
  const estoqueRows = dataBySheet.get("Estoque Final")?.rows.length ?? 0;
  const vendasRows = dataBySheet.get("Vendas")?.rows.length ?? 0;
  const entradasRows = dataBySheet.get("Entradas NF")?.rows.length ?? 0;
  const nfPendenteRows = dataBySheet.get("NF Pendente")?.rows.length ?? 0;
  const resumoMovRows = dataBySheet.get("Resumo Mov")?.rows.length ?? 0;
  const movCausaRows = dataBySheet.get("Mov Causa")?.rows.length ?? 0;
  const autoconsumoRows = dataBySheet.get("Autoconsumo")?.rows.length ?? 0;
  const movSemCausaRows = dataBySheet.get("Mov Sem Causa")?.rows.length ?? 0;
  const pedidosRows = dataBySheet.get("Pedidos")?.rows.length ?? 0;
  const retificacaoRows = dataBySheet.get("Retificacoes")?.rows.length ?? 0;
  const inventarioRows = dataBySheet.get("Inventario")?.rows.length ?? 0;

  const summaryRows = [
    ["Indicador", "Qtd", "Valor", "Observacao"],
    ["Estoque inicial", null, null, "Soma do estoque inicial por SKU"],
    ["Movimento total", null, null, "Soma assinada dos movimentos classificados"],
    ["Estoque esperado", null, null, "Estoque inicial + movimentos"],
    ["Estoque final Pleno", null, null, "Estoque final gravado no Pleno"],
    ["Divergencia", null, null, "Final Pleno - esperado"],
    ["Vendas cupom", null, null, "Quantidade e valor vendido"],
    ["Entradas de NF", null, null, "Notas de entrada por item"],
    ["NF pendente entrada", null, null, "Notas no Pleno sem check-in/entrada"],
    ["Saidas loja/CD", null, null, "Notas de saida da loja para o CD"],
    ["Autoconsumo", null, null, "Autoconsumo da loja com entrada/saida"],
    ["Movimentos sem causa", null, null, "Movimentos do est05 sem vinculo claro"],
    ["Pedidos pendentes", null, null, "Itens com situacao pendente"],
    ["Retificacoes", null, null, "Ajustes/retificacoes de recebimento no Pleno"],
    ["Inventarios", null, null, "Quantidade de inventarios/itens no periodo"],
  ];
  sheet.getRange("A3:D17").values = summaryRows;
  sheet.getRange("A3:D3").format.fill = { color: "#D9EAF7" };
  sheet.getRange("A3:D3").format.font = { bold: true, color: "#17324D" };
  sheet.getRange("A4:A17").format.font = { bold: true };
  sheet.getRange("A3:D17").format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };

  const estoqueLast = estoqueRows + 3;
  const vendasLast = vendasRows + 3;
  const entradasLast = entradasRows + 3;
  const nfPendenteLast = nfPendenteRows + 3;
  const resumoMovLast = resumoMovRows + 3;
  const movCausaLast = movCausaRows + 3;
  const autoconsumoLast = autoconsumoRows + 3;
  const movSemCausaLast = movSemCausaRows + 3;

  sheet.getRange("B4:C17").formulas = [
    [
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "qtd_inicio", 4, estoqueLast),
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "valor_inicio_custo", 4, estoqueLast),
    ],
    [
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "qtd_movimento", 4, estoqueLast),
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "valor_movimento_custo", 4, estoqueLast),
    ],
    ["=B4+B5", "=C4+C5"],
    [
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "qtd_fim_pleno", 4, estoqueLast),
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "valor_fim_pleno_custo", 4, estoqueLast),
    ],
    [
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "divergencia_qtd", 4, estoqueLast),
      sumDatasetHeaderFormula(dataBySheet, "Estoque Final", "divergencia_valor_custo", 4, estoqueLast),
    ],
    [sumFormula("Vendas", "F", 4, vendasLast), sumFormula("Vendas", "G", 4, vendasLast)],
    [sumFormula("Entradas NF", "K", 4, entradasLast), sumFormula("Entradas NF", "L", 4, entradasLast)],
    [`=${nfPendenteRows}`, sumFormula("NF Pendente", "I", 4, nfPendenteLast)],
    [
      sumDatasetHeaderFormula(dataBySheet, "Mov Causa", "qtd_movimento", 4, movCausaLast),
      sumDatasetHeaderFormula(dataBySheet, "Mov Causa", "valor_movimento_custo", 4, movCausaLast),
    ],
    [
      sumAbsDatasetHeaderFormula(dataBySheet, "Autoconsumo", "qtd_movimento", 4, autoconsumoLast),
      sumAbsDatasetHeaderFormula(dataBySheet, "Autoconsumo", "valor_movimento_custo", 4, autoconsumoLast),
    ],
    [
      sumDatasetHeaderFormula(dataBySheet, "Mov Sem Causa", "qtd_movimento", 4, movSemCausaLast),
      sumDatasetHeaderFormula(dataBySheet, "Mov Sem Causa", "valor_movimento_custo", 4, movSemCausaLast),
    ],
    [`=${pedidosRows}`, sumFormula("Pedidos", "I", 4, pedidosRows + 3)],
    [`=${retificacaoRows}`, "=0"],
    [`=${inventarioRows}`, sumFormula("Inventario", "P", 4, inventarioRows + 3)],
  ];
  sheet.getRange("B4:B17").setNumberFormat('#,##0.000;[Red]-#,##0.000');
  sheet.getRange("C4:C17").setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');

  const origemHeader = [["Origem", "Linhas", "Qtd Movimento", "Valor Movimento"]];
  sheet.getRange("F3:I3").values = origemHeader;
  sheet.getRange("F3:I3").format.fill = { color: "#D9EAF7" };
  sheet.getRange("F3:I3").format.font = { bold: true, color: "#17324D" };
  const origens = ["AUTOCONSUMO", "NF_E", "NF_S", "VENDA_CUPOM", "INVENTARIO", "SEM_CAUSA"];
  sheet.getRange(`F4:F${origens.length + 3}`).values = origens.map((origem) => [origem]);
  sheet.getRange(`G4:I${origens.length + 3}`).formulas = origens.map((origem) => {
    if (origem === "AUTOCONSUMO") {
      return [
        `=${autoconsumoRows}`,
        sumAbsDatasetHeaderFormula(dataBySheet, "Autoconsumo", "qtd_movimento", 4, autoconsumoLast),
        sumAbsDatasetHeaderFormula(dataBySheet, "Autoconsumo", "valor_movimento_custo", 4, autoconsumoLast),
      ];
    }
    return [
      sumIfFormula("Resumo Mov", "D", "E", 4, resumoMovLast, origem),
      sumIfFormula("Resumo Mov", "D", "F", 4, resumoMovLast, origem),
      sumIfFormula("Resumo Mov", "D", "G", 4, resumoMovLast, origem),
    ];
  });
  sheet.getRange(`F3:I${origens.length + 3}`).format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };
  sheet.getRange(`H4:H${origens.length + 3}`).setNumberFormat('#,##0.000;[Red]-#,##0.000');
  sheet.getRange(`I4:I${origens.length + 3}`).setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');

  const topRows = dataBySheet.get("Top Mov")?.rows.slice(0, 10) ?? [];
  sheet.getRange("F16:J16").values = [["Top movimentos", "SKU", "Descricao", "Qtd", "Valor"]];
  sheet.getRange("F16:J16").format.fill = { color: "#F8E5B9" };
  sheet.getRange("F16:J16").format.font = { bold: true, color: "#5C4300" };
  if (topRows.length > 0) {
    sheet.getRange(`F17:J${topRows.length + 16}`).values = topRows.map((row) => [
      row.origem,
      row.sku,
      row.descricao,
      toNumber(row.qtd_movimento),
      toNumber(row.valor_movimento_custo),
    ]);
    sheet.getRange(`I17:I${topRows.length + 16}`).setNumberFormat('#,##0.000;[Red]-#,##0.000');
    sheet.getRange(`J17:J${topRows.length + 16}`).setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');
  }
  sheet.getRange(`F16:J${Math.max(17, topRows.length + 16)}`).format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };

  sheet.freezePanes.freezeRows(3);
  const used = sheet.getUsedRange();
  used.format.autofitRows();
  sheet.getRange("A:A").format.columnWidthPx = 190;
  sheet.getRange("B:B").format.columnWidthPx = 120;
  sheet.getRange("C:C").format.columnWidthPx = 120;
  sheet.getRange("D:D").format.columnWidthPx = 360;
  sheet.getRange("F:F").format.columnWidthPx = 130;
  sheet.getRange("G:G").format.columnWidthPx = 90;
  sheet.getRange("H:H").format.columnWidthPx = 220;
  sheet.getRange("I:I").format.columnWidthPx = 120;
  sheet.getRange("J:J").format.columnWidthPx = 130;
  sheet.getRange("A1:J1").format.rowHeight = 28;
}

function datasetBySheet(datasets, sheetName) {
  return datasets.find((dataset) => dataset.sheet === sheetName) || { headers: [], rows: [] };
}

function explainDivergence(row) {
  const divergenceQty = toNumber(row.divergencia_qtd) ?? 0;
  const divergenceValue = toNumber(row.divergencia_valor_custo) ?? 0;
  const inventoryAlreadyOpen = Math.abs(toNumber(row.qtd_inventario_ja_no_inicio) ?? 0) > 0.001;
  const nfEntrada = Math.abs(toNumber(row.qtd_nf_entrada_movimento) ?? 0) > 0.001;
  const semCausa = Math.abs(toNumber(row.qtd_sem_causa_movimento) ?? 0) > 0.001;

  if (Math.abs(divergenceQty) < 0.001 && Math.abs(divergenceValue) < 0.01) {
    return {
      motivo: "Fechado",
      explicacao: "O estoque final do Pleno bate com o estoque esperado pela auditoria.",
      acao: "Nao precisa acao para este item.",
    };
  }

  if (divergenceQty > 0) {
    const base = "O estoque final do Pleno ficou maior que o esperado.";
    const complement = inventoryAlreadyOpen
      ? " O inventario ja estava aplicado no estoque inicial, entao a sobra restante indica entrada ou aumento posterior sem trilha capturada."
      : " Isso normalmente indica entrada, ajuste positivo ou aumento de estoque sem trilha capturada.";
    return {
      motivo: "Entrada/aumento sem trilha",
      explicacao: `${base}${complement}`,
      acao: "Conferir recebimentos, notas, ajustes positivos e processos internos do SKU nesta data.",
    };
  }

  if (semCausa) {
    return {
      motivo: "Movimento sem causa",
      explicacao: "Ha movimento de estoque sem vinculo claro com venda, nota, inventario ou autoconsumo.",
      acao: "Abrir a aba Mov Sem Causa e validar a origem do movimento no Pleno.",
    };
  }

  if (!nfEntrada && divergenceQty < 0) {
    return {
      motivo: "Saida/baixa sem trilha",
      explicacao: "O estoque final do Pleno ficou menor que o esperado. Isso indica uma baixa, saida ou ajuste negativo que nao apareceu nas trilhas exportadas.",
      acao: "Conferir baixas manuais, perdas, cancelamentos, reprocessamentos e movimentacoes do SKU no Pleno.",
    };
  }

  return {
    motivo: "Divergencia a investigar",
    explicacao: "Existe diferenca entre estoque esperado e estoque final, mas as trilhas atuais nao explicam totalmente o saldo.",
    acao: "Priorizar este item pelo valor da divergencia e cruzar com as abas de movimentos, notas, pedidos e inventario.",
  };
}

function buildDivergenceExplanationRows(datasets) {
  const estoque = datasetBySheet(datasets, "Estoque Final");
  return estoque.rows
    .map((row) => {
      const explanation = explainDivergence(row);
      return {
        loja: row.loja,
        data: row.data_movimento,
        sku: row.sku,
        descricao: row.descricao,
        motivo_provavel: explanation.motivo,
        explicacao_clara: explanation.explicacao,
        acao_recomendada: explanation.acao,
        divergencia_qtd: toNumber(row.divergencia_qtd) ?? 0,
        divergencia_valor_custo: toNumber(row.divergencia_valor_custo) ?? 0,
        estoque_inicial_qtd: toNumber(row.qtd_inicio) ?? 0,
        movimentos_usados_qtd: toNumber(row.qtd_movimento) ?? 0,
        estoque_esperado_qtd: toNumber(row.qtd_fim_esperado) ?? 0,
        estoque_final_qtd: toNumber(row.qtd_fim_pleno) ?? 0,
        inventario_ja_no_inicio_qtd: toNumber(row.qtd_inventario_ja_no_inicio) ?? 0,
        movimento_auditoria_qtd: toNumber(row.qtd_movimento_auditoria) ?? 0,
        venda_qtd: toNumber(row.qtd_venda_movimento) ?? 0,
        nf_entrada_qtd: toNumber(row.qtd_nf_entrada_movimento) ?? 0,
        inventario_movimento_qtd: toNumber(row.qtd_inventario_movimento) ?? 0,
        sem_causa_qtd: toNumber(row.qtd_sem_causa_movimento) ?? 0,
      };
    })
    .filter((row) => Math.abs(row.divergencia_qtd) >= 0.001 || Math.abs(row.divergencia_valor_custo) >= 0.01)
    .sort((a, b) => Math.abs(b.divergencia_valor_custo) - Math.abs(a.divergencia_valor_custo));
}

function writeDivergenceExplanation(sheet, datasets) {
  sheet.showGridLines = false;
  writeTitle(sheet, "Explicacao das divergencias", 19);

  const rows = buildDivergenceExplanationRows(datasets);
  const totalValue = rows.reduce((acc, row) => acc + row.divergencia_valor_custo, 0);
  const positiveValue = rows.filter((row) => row.divergencia_valor_custo > 0).reduce((acc, row) => acc + row.divergencia_valor_custo, 0);
  const negativeValue = rows.filter((row) => row.divergencia_valor_custo < 0).reduce((acc, row) => acc + row.divergencia_valor_custo, 0);

  sheet.getRange("A3:D6").values = [
    ["Como ler", "Final maior que esperado", "Faltou entrada/aumento na trilha exportada.", null],
    ["Como ler", "Final menor que esperado", "Faltou saida/baixa na trilha exportada.", null],
    ["Inventario", "Ja aplicado na abertura", "Quando o estoque inicial ja e igual a contagem, o inventario nao deve ser somado de novo.", null],
    ["Saldo divergente", rows.length, totalValue, "Soma dos itens que ainda nao fecharam 0 x 0."],
  ];
  sheet.getRange("A3:D6").format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };
  sheet.getRange("A3:A6").format.font = { bold: true, color: "#17324D" };
  sheet.getRange("A3:D6").format.wrapText = true;
  sheet.getRange("C6:C6").setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');

  sheet.getRange("F3:H6").values = [
    ["Resumo", "Valor", "Leitura"],
    ["Divergencia positiva", positiveValue, "Estoque final maior que esperado"],
    ["Divergencia negativa", negativeValue, "Estoque final menor que esperado"],
    ["Divergencia liquida", totalValue, "Soma final da diferenca"],
  ];
  sheet.getRange("F3:H3").format.fill = { color: "#D9EAF7" };
  sheet.getRange("F3:H3").format.font = { bold: true, color: "#17324D" };
  sheet.getRange("F3:H6").format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };
  sheet.getRange("F3:H6").format.wrapText = true;
  sheet.getRange("G4:G6").setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');

  const headers = [
    "loja",
    "data",
    "sku",
    "descricao",
    "motivo_provavel",
    "explicacao_clara",
    "acao_recomendada",
    "divergencia_qtd",
    "divergencia_valor_custo",
    "estoque_inicial_qtd",
    "movimentos_usados_qtd",
    "estoque_esperado_qtd",
    "estoque_final_qtd",
    "inventario_ja_no_inicio_qtd",
    "movimento_auditoria_qtd",
    "venda_qtd",
    "nf_entrada_qtd",
    "inventario_movimento_qtd",
    "sem_causa_qtd",
  ];

  const headerRow = 9;
  sheet.getRange(rangeFor(headerRow, 0, 1, headers.length)).values = [headers];
  sheet.getRange(rangeFor(headerRow, 0, 1, headers.length)).format.fill = { color: "#D9EAF7" };
  sheet.getRange(rangeFor(headerRow, 0, 1, headers.length)).format.font = { bold: true, color: "#17324D" };
  sheet.getRange(rangeFor(headerRow, 0, 1, headers.length)).format.borders = { preset: "outside", style: "thin", color: "#9FB7C9" };

  if (rows.length > 0) {
    const values = rows.map((row) => headers.map((header) => row[header]));
    sheet.getRange(rangeFor(headerRow + 1, 0, values.length, headers.length)).values = values;
    sheet.getRange(rangeFor(headerRow + 1, 0, values.length, headers.length)).format.borders = { preset: "inside", style: "thin", color: "#E5EDF3" };
    sheet.getRange(`E10:G${rows.length + 9}`).format.wrapText = true;
  } else {
    sheet.getRange("A10:C10").values = [["Todas as divergencias fecharam 0 x 0.", null, null]];
  }

  for (let idx = 7; idx < headers.length; idx += 1) {
    const header = headers[idx];
    const range = `${colLetter(idx)}10:${colLetter(idx)}${Math.max(10, rows.length + 9)}`;
    if (header.includes("valor")) {
      sheet.getRange(range).setNumberFormat('"R$" #,##0.00;[Red]-"R$" #,##0.00');
    } else {
      sheet.getRange(range).setNumberFormat('#,##0.000;[Red]-#,##0.000');
    }
  }

  sheet.freezePanes.freezeRows(9);
  sheet.getRange("A:A").format.columnWidthPx = 70;
  sheet.getRange("B:B").format.columnWidthPx = 105;
  sheet.getRange("C:C").format.columnWidthPx = 90;
  sheet.getRange("D:D").format.columnWidthPx = 260;
  sheet.getRange("E:E").format.columnWidthPx = 210;
  sheet.getRange("F:F").format.columnWidthPx = 520;
  sheet.getRange("G:G").format.columnWidthPx = 430;
  sheet.getRange("A3:A6").format.columnWidthPx = 95;
  sheet.getRange("B:B").format.columnWidthPx = 160;
  sheet.getRange("C:C").format.columnWidthPx = 130;
  sheet.getRange("C3:C6").format.columnWidthPx = 420;
  sheet.getRange("H:H").format.columnWidthPx = 125;
  sheet.getRange("I:I").format.columnWidthPx = 140;
  sheet.getRange("J:J").format.columnWidthPx = 125;
  for (let idx = 7; idx < headers.length; idx += 1) {
    sheet.getRange(`${colLetter(idx)}:${colLetter(idx)}`).format.columnWidthPx = 130;
  }
  sheet.getRange("H:H").format.columnWidthPx = 125;
  sheet.getRange("I:I").format.columnWidthPx = 140;
  sheet.getRange("J:J").format.columnWidthPx = 125;
  sheet.getUsedRange().format.autofitRows();
}

async function main() {
  const args = parseArgs();
  const runName = path.basename(args.runDir);
  await fs.mkdir(args.outputDir, { recursive: true });
  const workbook = Workbook.create();
  const datasets = [];

  for (const spec of sheetSpecs) {
    datasets.push(await readDataset(args.runDir, spec));
  }

  const summarySheet = workbook.worksheets.add("Resumo");
  for (const dataset of datasets) {
    const sheet = workbook.worksheets.add(dataset.sheet);
    writeDatasetSheet(sheet, dataset);
  }
  writeSummary(summarySheet, datasets, runName);
  const divergenceSheet = workbook.worksheets.add("Explicacao Diverg");
  writeDivergenceExplanation(divergenceSheet, datasets);

  const summaryInspect = await workbook.inspect({
    kind: "table",
    sheetId: "Resumo",
    range: "A1:J24",
    include: "values,formulas",
    tableMaxRows: 24,
    tableMaxCols: 10,
    maxChars: 6000,
  });
  console.log(summaryInspect.ndjson);

  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 300 },
    summary: "final formula error scan",
  });
  console.log(errors.ndjson);

  const previewDir = path.join(args.outputDir, "previews", runName);
  await fs.mkdir(previewDir, { recursive: true });
  const previewSheets = [
    { name: "Resumo", range: "A1:J24" },
    ...datasets.map((dataset) => ({
      name: dataset.sheet,
      range: rangeFor(1, 0, Math.max(5, Math.min(dataset.rows.length + 4, 25)), Math.min(Math.max(dataset.headers.length, 1), 10)),
    })),
    { name: "Explicacao Diverg", range: "A1:J30" },
  ];
  for (const sheet of previewSheets) {
    const blob = await workbook.render({ sheetName: sheet.name, range: sheet.range, scale: 1, format: "png" });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    await fs.writeFile(path.join(previewDir, `${sheet.name.replaceAll(" ", "_")}.png`), bytes);
  }

  const outputPath = path.join(args.outputDir, `pleno_auditoria_${runName}.xlsx`);
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(outputPath);
  console.log(`XLSX: ${outputPath}`);
  console.log(`PREVIEWS: ${previewDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

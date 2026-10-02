import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = path.resolve(new URL('..', import.meta.url).pathname);
const out = path.join(root, 'outputs', 'tesouraria_cofre_inteligente');
const db = path.join(out, 'acompanhamento.sqlite');
const limit = Number(process.env.TESOURARIA_OCR_AUDIT_LIMIT || 100);
const env = fs.existsSync(path.join(root, '.env')) ? Object.fromEntries(fs.readFileSync(path.join(root, '.env'), 'utf8').split(/\r?\n/).flatMap((line) => {
  const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
  return match ? [[match[1], match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '')]] : [];
})) : {};
const startedAt = new Date().toISOString();
const statusFile = path.join(out, 'auditoria_ocr_execucao.json');
const resultFile = path.join(out, 'auditoria_ocr_resultado.json');

function money(value) {
  const raw = String(value ?? '').replace(/[^\d,.-]/g, '');
  if (!raw) return 0;
  const decimal = Math.max(raw.lastIndexOf(','), raw.lastIndexOf('.'));
  const normalized = decimal < 0 ? raw.replace(/[.,]/g, '') : `${raw.slice(0, decimal).replace(/[.,]/g, '')}.${raw.slice(decimal + 1).replace(/[.,]/g, '')}`;
  return Math.round(Number(normalized) * 100) / 100;
}

// Reusa exatamente a mesma leitura do lote, mas nunca abre Pleno ou Brinks.
const lote = fs.readFileSync(path.join(root, 'scripts', 'tesouraria-cofre-lote.mjs'), 'utf8');
const ocrStart = lote.indexOf('function ocrReceipt');
const ocrEnd = lote.indexOf('function existingConcluded');
if (ocrStart < 0 || ocrEnd < 0) throw new Error('Funcoes de OCR nao encontradas no lote.');
const { selectOcr } = eval(`${lote.slice(ocrStart, ocrEnd)}; ({ selectOcr })`);

const rows = JSON.parse(execFileSync('python3', ['-c', `
import json, sqlite3, sys
db, limit = sys.argv[1], int(sys.argv[2])
con = sqlite3.connect(db)
con.row_factory = sqlite3.Row
rows = con.execute('''
  select transaction_id, store_code, store_name, planned_date, value, pleno_file, updated_at
  from tesouraria_cofre_processos
  where status = 'erro' and error_stage = 'ocr' and pleno_file is not null
  order by updated_at desc
  limit ?
''', (limit,)).fetchall()
print(json.dumps([dict(row) for row in rows]))
`, db, String(limit)], { encoding: 'utf8' }));

const results = [];
function writeStatus(current = null) {
  const recovered = results.filter((item) => item.recovered).length;
  fs.writeFileSync(statusFile, JSON.stringify({
    status: current ? 'executando' : 'finalizado', startedAt, updatedAt: new Date().toISOString(),
    selected: rows.length, processed: results.length, recovered, failed: results.length - recovered, current,
  }));
  fs.writeFileSync(resultFile, JSON.stringify({ startedAt, finishedAt: current ? null : new Date().toISOString(), results }, null, 2));
}

for (const row of rows) {
  const current = `${row.store_code} - ${row.store_name}`;
  writeStatus(current);
  const file = path.join(out, row.pleno_file);
  try {
    if (!fs.existsSync(file)) throw new Error('Evidencia nao encontrada no servidor.');
    const planned = String(row.planned_date).split('-').reverse().join('/');
    const ocr = selectOcr(file, { planned, value: Number(row.value) });
    results.push({ transactionId: row.transaction_id, storeCode: row.store_code, storeName: row.store_name, plannedDate: row.planned_date, value: Number(row.value), file: row.pleno_file, recovered: Boolean(ocr.matches), engine: ocr.engine, ocrValue: money(ocr.value), from: ocr.from || null, to: ocr.to || null });
  } catch (error) {
    results.push({ transactionId: row.transaction_id, storeCode: row.store_code, storeName: row.store_name, plannedDate: row.planned_date, value: Number(row.value), file: row.pleno_file, recovered: false, error: error.message });
  }
}

writeStatus();
const recovered = results.filter((item) => item.recovered).length;
console.log(`Auditoria OCR concluida: ${results.length} caso(s), ${recovered} recuperavel(is), ${results.length - recovered} sem leitura confiavel.`);

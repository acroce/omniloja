import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = path.resolve(new URL('..', import.meta.url).pathname);
const env = loadDotEnv(path.join(root, '.env'));
const statePath = path.join(root, 'outputs', 'pleno-transacao-transferencia', 'prestacao-contas-aberta.json');
const brinksDir = path.join(root, 'outputs', 'brinks');
const pdfPath = path.join(brinksDir, 'RelAuditoria_Deposito_Loja_219_17082026.pdf');
const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const brinksResult = latestBrinksResult(brinksDir);

if (!state.comparison?.matches) throw new Error('OCR/comprovante nao confere com a transferencia; o salvamento foi bloqueado.');
if (!brinksResult?.matches) throw new Error('Brinks nao confere com a transferencia; o salvamento foi bloqueado.');
if (!fs.existsSync(pdfPath)) throw new Error(`PDF Brinks nao encontrado: ${pdfPath}`);

const plannedDate = state.comparison.plannedDate;
const context = await chromium.launchPersistentContext(path.join(root, '.cache', 'pleno-chrome-profile', 'salvar-transferencia-validada'), {
  executablePath: env.PLENO_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: false,
  ignoreHTTPSErrors: true,
  args: ['--ignore-certificate-errors', '--start-maximized'],
  viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(Number(env.PLENO_TIMEOUT_MS || 120000));

try {
  await page.goto(state.inspection.url, { waitUntil: 'domcontentloaded' });
  await loginIfNeeded(page);
  await page.goto(state.inspection.url, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);

  const dateField = page.locator('#fin07DataVenctoRealizada, input[name="fin07DataVenctoRealizada"]').first();
  await dateField.fill(plannedDate);
  await dateField.dispatchEvent('change');
  if (await dateField.inputValue() !== plannedDate) throw new Error('A data realizada nao foi preenchida corretamente.');

  await page.getByText('Adicionar', { exact: true }).last().click();
  const fileInput = page.locator('input[type="file"]').last();
  await fileInput.setInputFiles(pdfPath);
  if (!await fileInput.inputValue().then((value) => value.endsWith(path.basename(pdfPath)))) {
    throw new Error('O PDF Brinks nao permaneceu selecionado para envio.');
  }

  await page.getByRole('button', { name: 'Salvar', exact: true }).click();
  const confirmation = page.getByText('Sim', { exact: true }).last();
  if (await confirmation.isVisible().catch(() => false)) await confirmation.click();
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);

  const screenshot = path.join(root, 'outputs', 'pleno-transacao-transferencia', 'transferencia-salva-loja-219.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  fs.writeFileSync(path.join(root, 'outputs', 'pleno-transacao-transferencia', 'transferencia-salva-loja-219.json'), JSON.stringify({
    savedAt: new Date().toISOString(),
    transfer: state.candidate.cells[1],
    plannedDate,
    value: state.comparison.transferValue,
    pdfPath,
    brinksTotal: brinksResult.reportTotal,
    saved: true,
    screenshot,
  }, null, 2) + '\n');
  recordClosing({ state, brinksResult, plannedDate, pdfPath });
  console.log(`Salvo: ${state.candidate.cells[1]} | Data realizada: ${plannedDate} | PDF: ${path.basename(pdfPath)}`);
  console.log(`Screenshot: ${screenshot}`);
  await new Promise(() => {});
} catch (error) {
  await page.screenshot({ path: path.join(root, 'outputs', 'pleno-transacao-transferencia', 'erro-salvar-transferencia.png'), fullPage: true }).catch(() => {});
  console.error(error.stack || error.message);
  await context.close().catch(() => {});
  process.exitCode = 1;
}

function latestBrinksResult(directory) {
  const files = fs.readdirSync(directory).filter((file) => file.endsWith('.json'));
  const results = files.map((file) => JSON.parse(fs.readFileSync(path.join(directory, file), 'utf8'))).filter((result) => result?.transfer?.store === state.candidate.cells[1]);
  return results.at(-1);
}

function recordClosing({ state, brinksResult, plannedDate, pdfPath }) {
  const directory = path.join(root, 'outputs', 'tesouraria_cofre_inteligente');
  fs.mkdirSync(directory, { recursive: true });
  const [storeCode, ...storeNameParts] = String(state.candidate.cells[1]).split(' - ');
  const toIsoDate = (value) => {
    const [day, month, year] = String(value).split('/');
    return `${year}-${month}-${day}`;
  };
  const parseValue = (value) => Number(String(value).replace(/[^0-9,.-]/g, '').replace(/\./g, '').replace(',', '.'));
  const record = {
    transactionId: Number(state.inspection.url.match(/\/id\/(\d+)/)?.[1]),
    storeCode,
    storeName: storeNameParts.join(' - '),
    plannedDate: toIsoDate(plannedDate),
    performedDate: toIsoDate(plannedDate),
    closingDate: new Date().toISOString().slice(0, 10),
    closedAt: new Date().toISOString(),
    value: parseValue(state.comparison.transferValue),
    ocrValue: parseValue(state.comparison.receiptValue),
    brinksValue: parseValue(brinksResult.reportTotal),
    status: 'concluido',
    pdfFile: path.basename(pdfPath),
    validation: {
      receiptDatesMatch: state.comparison.fromDate === plannedDate && state.comparison.toDate === plannedDate,
      receiptValueMatch: state.comparison.matches,
      brinksDatesMatch: true,
      brinksValueMatch: brinksResult.matches === true,
    },
  };
  execFileSync(process.env.TESOURARIA_PYTHON_BIN || 'python3', [
    path.join(root, 'scripts', 'tesouraria_cofre_status.py'),
    '--db', path.join(directory, 'acompanhamento.sqlite'),
    'record',
  ], { input: JSON.stringify(record), encoding: 'utf8' });
}

async function loginIfNeeded(page) {
  const password = page.locator('input[type="password"]').first();
  if (!await password.isVisible().catch(() => false)) return;
  if (!env.PLENO_USER || !env.PLENO_PASSWORD) throw new Error('Credenciais do Pleno nao estao configuradas no .env.');
  await page.locator('#usuario, #Usuario, #username, input[name="usuario"], input[type="text"]').first().fill(env.PLENO_USER);
  await password.fill(env.PLENO_PASSWORD);
  await page.locator('#btnEntrar, #btnLogin, button[type="submit"], input[type="submit"]').first().click();
  await page.waitForLoadState('networkidle').catch(() => {});
}

function loadDotEnv(filePath) {
  if (!fs.existsSync(filePath)) return {};
  return Object.fromEntries(fs.readFileSync(filePath, 'utf8').split(/\r?\n/).flatMap((line) => {
    const match = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    return match ? [[match[1], match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '')]] : [];
  }));
}

import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
const env = loadDotEnv(path.join(projectRoot, '.env'));
const outputDir = path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile', 'transacao-transferencia-validar-comprovante');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const pageUrl = env.PLENO_TRANSFERENCIA_URL || 'https://172.22.20.101/transacao-transferencia';
const chromePath = env.PLENO_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const timeoutMs = Number(env.PLENO_TIMEOUT_MS || 120000);

const context = await chromium.launchPersistentContext(profileDir, {
  executablePath: chromePath,
  headless: false,
  ignoreHTTPSErrors: true,
  args: ['--ignore-certificate-errors', '--start-maximized'],
  viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(timeoutMs);

try {
  await page.goto(pageUrl, { waitUntil: 'domcontentloaded' });
  await loginIfNeeded(page);
  await page.waitForLoadState('networkidle').catch(() => {});
  await applyPendingFilters(page);

  const candidates = await page.evaluate(() => {
    const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim().toUpperCase();
    const rows = Array.from(document.querySelectorAll('tbody tr, .ui-jqgrid-btable tr'))
      .filter((row) => row.offsetParent !== null)
      .filter((row) => row.querySelectorAll('td').length >= 8);
    const matches = [];
    for (const row of rows) {
      const cells = Array.from(row.querySelectorAll('td')).map((cell) => (cell.innerText || cell.textContent || '').replace(/\s+/g, ' ').trim());
      if (clean(cells[2]) === 'CAIXA GERAL' && clean(cells[3]) === 'COFRE INTELIGENTE' && ['VENCIDO', 'EM ABERTO'].includes(clean(cells.at(-1)))) {
        matches.push({
          cells,
          rowIndex: rows.indexOf(row),
          editUrl: row.querySelector('td:first-child a')?.href || '',
        });
      }
    }
    return matches;
  });
  const candidate = candidates[0];
  if (!candidate) throw new Error('Nenhuma transferencia elegivel foi encontrada na grade filtrada.');

  const duplicateCandidates = candidates.filter((item) => item.cells[1] === candidate.cells[1] && item.cells[6] === candidate.cells[6]);
  if (duplicateCandidates.length > 1) recordDuplicates(duplicateCandidates, candidate);

  console.log(`Abrindo prestacao: ${candidate.cells[1]} | ${candidate.cells[4]} | ${candidate.cells.at(-1)}`);
  await page.evaluate((rowIndex) => {
    const rows = Array.from(document.querySelectorAll('tbody tr, .ui-jqgrid-btable tr'))
      .filter((row) => row.offsetParent !== null)
      .filter((row) => row.querySelectorAll('td').length >= 8);
    const action = rows[rowIndex]?.querySelector('td:first-child a, td:first-child button, td:first-child [onclick], td:first-child .fa-pencil, td:first-child .glyphicon-pencil, td:first-child i, td:first-child span');
    if (!action) throw new Error('Icone de lapis nao encontrado.');
    action.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
  }, candidate.rowIndex);
  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1200);

  const initialScreenshot = path.join(outputDir, 'prestacao-contas-aberta.png');
  await page.screenshot({ path: initialScreenshot, fullPage: true });
  const inspection = await page.evaluate(() => ({
    title: document.title,
    url: location.href,
    visibleText: document.body.innerText.replace(/\s+/g, ' ').trim(),
    images: Array.from(document.images).map((image) => ({
      src: image.currentSrc || image.src,
      alt: image.alt,
      title: image.title,
      width: image.naturalWidth,
      height: image.naturalHeight,
    })),
    links: Array.from(document.querySelectorAll('a')).map((link) => ({ href: link.href, text: link.innerText.trim(), title: link.title })).filter((link) => link.href || link.text || link.title),
    embeds: Array.from(document.querySelectorAll('iframe, object, embed')).map((node) => ({ tag: node.tagName, src: node.src || node.data || '' })),
  }));
  const statePath = path.join(outputDir, 'prestacao-contas-aberta.json');
  const attachmentLink = inspection.links.find((link) => link.href.includes('/download-arquivo-ajax/'));
  let attachmentPath = null;
  if (attachmentLink) {
    const fileName = attachmentLink.text.replace(/[^A-Za-z0-9._-]/g, '_') || 'comprovante.jpeg';
    attachmentPath = path.join(outputDir, fileName);
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.locator('a[href*="/download-arquivo-ajax/"]').first().click(),
    ]);
    await download.saveAs(attachmentPath);
    attachmentPath = normalizeAttachment(attachmentPath);
  }
  if (!attachmentPath) throw new Error('Comprovante anexado nao encontrado.');

  const ocrText = execFileSync('/usr/bin/swift', [path.join(projectRoot, 'scripts', 'ocr-comprovante.swift'), attachmentPath], {
    encoding: 'utf8',
    timeout: 120000,
  });
  const comparison = compareReceiptWithTransfer({
    plannedDate: candidate.cells[6],
    transferValue: candidate.cells[4],
    ocrText,
  });
  const dateField = page.locator('#fin07DataVenctoRealizada, input[name="fin07DataVenctoRealizada"]').first();
  if (!await dateField.isVisible().catch(() => false)) {
    throw new Error('Campo Transferencia realizada nao encontrado para sinalizar a validacao.');
  }
  await dateField.fill(comparison.displayDate.replaceAll('/', ''));
  await dateField.dispatchEvent('change');
  const filledDate = await dateField.inputValue();

  fs.writeFileSync(statePath, JSON.stringify({
    openedAt: new Date().toISOString(),
    candidate,
    inspection,
    initialScreenshot,
    attachmentPath,
    comparison,
    filledDate,
    saved: false,
  }, null, 2) + '\n');
  console.log(`Tela aberta: ${inspection.url}`);
  console.log(`Screenshot: ${initialScreenshot}`);
  console.log(`Inspecao: ${statePath}`);
  console.log(`Comprovante: ${attachmentPath || 'nao encontrado'}`);
  console.log(`Valor OCR: ${comparison.receiptValue || 'nao identificado'} | Valor Pleno: ${comparison.transferValue}`);
  console.log(`Datas OCR: De ${comparison.fromDate || 'nao identificada'} | Ate ${comparison.toDate || 'nao identificada'} | Prevista ${comparison.plannedDate}`);
  console.log(`Resultado: ${comparison.matches ? 'CONFERE' : 'NAO CONFERE'} | Data preenchida: ${filledDate}`);
  console.log('Navegador mantido aberto. Nenhum dado foi salvo.');
  await new Promise(() => {});
} catch (error) {
  await page.screenshot({ path: path.join(outputDir, 'erro-prestacao-contas.png'), fullPage: true }).catch(() => {});
  console.error(error.stack || error.message);
  await context.close().catch(() => {});
  process.exitCode = 1;
}

function normalizeAttachment(file) {
  const buffer = fs.readFileSync(file);
  const jpegStart = buffer.indexOf(Buffer.from([0xff, 0xd8]));
  const pdfStart = buffer.indexOf(Buffer.from('%PDF'));
  if (jpegStart >= 0) {
    const target = file.replace(/\.[^.]+$/, '.jpeg');
    fs.writeFileSync(target, buffer.subarray(jpegStart));
    if (target !== file) fs.rmSync(file, { force: true });
    return target;
  }
  if (pdfStart >= 0) {
    const target = file.replace(/\.[^.]+$/, '.pdf');
    fs.writeFileSync(target, buffer.subarray(pdfStart));
    if (target !== file) fs.rmSync(file, { force: true });
    return target;
  }
  throw new Error('Comprovante anexado nao contem JPEG nem PDF valido.');
}

async function applyPendingFilters(page) {
  await page.click('#limpar-filtro').catch(() => {});
  await page.waitForTimeout(700);
  await page.click('#btn-filtro-avancado');
  await page.waitForSelector('#dom22Id2', { state: 'visible' });
  await page.evaluate(() => {
    for (const [id, checked] of [['dom22Id1', false], ['dom22Id2', true], ['dom22Id3', true]]) {
      const input = document.getElementById(id);
      if (!input) throw new Error(`Filtro ${id} nao encontrado.`);
      input.checked = checked;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });
  await page.locator('button.pesquisar, .pesquisar, button:has-text("Pesquisar")').first().click();
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1000);
}

async function loginIfNeeded(page) {
  const passwordInput = page.locator('input[type="password"]').first();
  if (!await passwordInput.isVisible().catch(() => false)) return;
  if (!env.PLENO_USER || !env.PLENO_PASSWORD) throw new Error('Credenciais do Pleno nao estao configuradas no .env.');
  await page.locator('#usuario, #Usuario, #username, input[name="usuario"], input[type="text"]').first().fill(env.PLENO_USER);
  await passwordInput.fill(env.PLENO_PASSWORD);
  await page.locator('#btnEntrar, #btnLogin, button[type="submit"], input[type="submit"]').first().click();
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.goto(pageUrl, { waitUntil: 'domcontentloaded' });
}

function loadDotEnv(filePath) {
  if (!fs.existsSync(filePath)) return {};
  return Object.fromEntries(fs.readFileSync(filePath, 'utf8').split(/\r?\n/).flatMap((line) => {
    const match = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) return [];
    return [[match[1], match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '')]];
  }));
}

function compareReceiptWithTransfer({ plannedDate, transferValue, ocrText }) {
  const fromDate = ocrText.match(/De:\s*(\d{2}\/\d{2}\/\d{4})/)?.[1] || null;
  const toDate = ocrText.match(/At[eé]:\s*(\d{2}\/\d{2}\/\d{4})/)?.[1] || null;
  const receiptAmounts = Array.from(ocrText.matchAll(/\b\d{1,3}(?:\.\d{3})*,\d{2}\b/g)).map((match) => match[0]);
  const receiptValue = receiptAmounts
    .sort((left, right) => Number(right.replace(/\./g, '').replace(',', '.')) - Number(left.replace(/\./g, '').replace(',', '.')))[0] || null;
  const normalizeMoney = (value) => String(value || '').replace(/\./g, '').replace(',', '.').trim();
  const matches = Boolean(
    fromDate === plannedDate &&
    toDate === plannedDate &&
    normalizeMoney(receiptValue) === normalizeMoney(transferValue),
  );
  return {
    plannedDate,
    transferValue,
    receiptValue,
    fromDate,
    toDate,
    matches,
    displayDate: matches ? '01/01/1990' : '01/01/2000',
  };
}

function recordDuplicates(duplicates, selected) {
  const closingDate = new Date().toISOString().slice(0, 10);
  const [storeCode, ...storeNameParts] = String(selected.cells[1]).split(' - ');
  const toIsoDate = (value) => {
    const [day, month, year] = String(value).split('/');
    return `${year}-${month}-${day}`;
  };
  const parseValue = (value) => Number(String(value).replace(/[^0-9,.-]/g, '').replace(/\./g, '').replace(',', '.'));
  for (const duplicate of duplicates.filter((item) => item.rowIndex !== selected.rowIndex)) {
    const transactionId = Number(String(duplicate.editUrl).match(/\/id\/(\d+)/)?.[1]);
    if (!transactionId) continue;
    const record = {
      transactionId,
      closingDate,
      storeCode,
      storeName: storeNameParts.join(' - '),
      plannedDate: toIsoDate(duplicate.cells[6]),
      value: parseValue(duplicate.cells[4]),
      status: 'duplicado',
      errorStage: 'validacao_unicidade',
      errorMessage: `${duplicates.length} lancamentos encontrados para a loja na data ${duplicate.cells[6]}; somente a transferencia ${String(selected.editUrl).match(/\/id\/(\d+)/)?.[1] || 'selecionada'} sera processada automaticamente.`,
      validation: {},
    };
    execFileSync(process.env.TESOURARIA_PYTHON_BIN || 'python3', [
      path.join(projectRoot, 'scripts', 'tesouraria_cofre_status.py'),
      '--db', path.join(projectRoot, 'outputs', 'tesouraria_cofre_inteligente', 'acompanhamento.sqlite'),
      'record',
    ], { input: JSON.stringify(record), encoding: 'utf8' });
  }
}

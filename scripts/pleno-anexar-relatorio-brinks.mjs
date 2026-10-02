import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
const env = loadDotEnv(path.join(projectRoot, '.env'));
const statePath = path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia', 'prestacao-contas-aberta.json');
const pdfPath = path.join(projectRoot, 'outputs', 'brinks', 'RelAuditoria_Deposito_Loja_219_17082026.pdf');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile', 'anexar-relatorio-brinks');

if (!fs.existsSync(statePath)) throw new Error(`Estado da prestacao nao encontrado: ${statePath}`);
if (!fs.existsSync(pdfPath)) throw new Error(`PDF Brinks nao encontrado: ${pdfPath}`);

const state = JSON.parse(fs.readFileSync(statePath, 'utf8'));
const transferUrl = state.inspection.url;
const context = await chromium.launchPersistentContext(profileDir, {
  executablePath: env.PLENO_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: false,
  ignoreHTTPSErrors: true,
  args: ['--ignore-certificate-errors', '--start-maximized'],
  viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(Number(env.PLENO_TIMEOUT_MS || 120000));

try {
  await page.goto(transferUrl, { waitUntil: 'domcontentloaded' });
  await loginIfNeeded(page);
  await page.goto(transferUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);

  const dateField = page.locator('#fin07DataVenctoRealizada, input[name="fin07DataVenctoRealizada"]').first();
  await dateField.fill('01011990');
  await dateField.dispatchEvent('change');

  const addButton = page.getByText('Adicionar', { exact: true }).last();
  await addButton.scrollIntoViewIfNeeded();
  await addButton.click();
  const fileInput = page.locator('input[type="file"]').last();
  await fileInput.waitFor({ state: 'attached' });
  await fileInput.setInputFiles(pdfPath);
  await page.waitForTimeout(1500);

  const selectedFile = await fileInput.inputValue();
  if (!selectedFile.endsWith('RelAuditoria_Deposito_Loja_219_17082026.pdf')) {
    throw new Error(`O PDF nao permaneceu selecionado no campo de arquivo: ${selectedFile || 'vazio'}`);
  }

  const screenshotPath = path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia', 'prestacao-com-relatorio-brinks-anexado.png');
  await page.screenshot({ path: screenshotPath, fullPage: true });
  console.log(`PDF anexado: ${pdfPath}`);
  console.log(`Screenshot: ${screenshotPath}`);
  console.log('Tela mantida aberta. O botao Salvar nao foi acionado.');
  await new Promise(() => {});
} catch (error) {
  await page.screenshot({ path: path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia', 'erro-anexar-relatorio-brinks.png'), fullPage: true }).catch(() => {});
  console.error(error.stack || error.message);
  await context.close().catch(() => {});
  process.exitCode = 1;
}

async function loginIfNeeded(page) {
  const passwordInput = page.locator('input[type="password"]').first();
  if (!await passwordInput.isVisible().catch(() => false)) return;
  if (!env.PLENO_USER || !env.PLENO_PASSWORD) throw new Error('Credenciais do Pleno nao estao configuradas no .env.');
  await page.locator('#usuario, #Usuario, #username, input[name="usuario"], input[type="text"]').first().fill(env.PLENO_USER);
  await passwordInput.fill(env.PLENO_PASSWORD);
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

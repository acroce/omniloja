import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(new URL('..', import.meta.url).pathname);
const plenoStatePath = path.join(root, 'outputs', 'pleno-transacao-transferencia', 'prestacao-contas-aberta.json');
const outputDir = path.join(root, 'outputs', 'brinks');
const profileDir = path.join(root, '.cache', 'brinks-chrome-profile');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const user = process.env.BRINKS_USER;
const password = process.env.BRINKS_PASSWORD;
if (!user || !password) throw new Error('Defina BRINKS_USER e BRINKS_PASSWORD apenas para esta execucao.');
if (!fs.existsSync(plenoStatePath)) throw new Error(`Estado do Pleno nao encontrado: ${plenoStatePath}`);

const pleno = JSON.parse(fs.readFileSync(plenoStatePath, 'utf8'));
const transfer = {
  store: pleno.candidate?.cells?.[1] || '',
  value: pleno.candidate?.cells?.[4] || '',
  plannedDate: pleno.candidate?.cells?.[6] || '',
};
const storeNumber = transfer.store.match(/^(\d+)/)?.[1];
if (!storeNumber || !transfer.value || !transfer.plannedDate) throw new Error('Dados da transferencia atual do Pleno estao incompletos.');

const context = await chromium.launchPersistentContext(profileDir, {
  executablePath: process.env.BRINKS_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: false,
  acceptDownloads: true,
  viewport: null,
  args: ['--start-maximized'],
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(30000);

try {
  await page.goto('https://www.brinks24seven.com.br/pt/login', { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => { document.documentElement.style.zoom = '0.8'; });
  await loginIfNeeded(page);
  const account = await findAccountForStore(page, storeNumber);
  console.log(`Conta Brinks localizada para loja ${storeNumber}: ${account}`);
  await page.goto('https://www.brinks24seven.com.br/pt/static-report/audit-report', { waitUntil: 'domcontentloaded' });
  await page.getByText('Relatório de Auditoria', { exact: true }).last().waitFor({ state: 'visible' });
  await applyAuditFilter(page, account, transfer.plannedDate);

  const rows = await page.locator('tbody tr').allTextContents();
  const amounts = rows.map((row) => row.match(/R\$\s*([\d.,]+)/)?.[1]).filter(Boolean);
  const reportTotal = amounts.reduce((sum, amount) => sum + parseMoney(amount), 0);
  const expectedTotal = parseMoney(transfer.value);
  const pdfPath = path.join(outputDir, `RelAuditoria_Deposito_Loja_${storeNumber}_${transfer.plannedDate.replaceAll('/', '')}.pdf`);
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'PDF', exact: true }).click(),
  ]);
  await download.saveAs(pdfPath);

  const result = {
    checkedAt: new Date().toISOString(),
    transfer,
    brinksAccount: account,
    reportTotal: formatMoney(reportTotal),
    matches: reportTotal === expectedTotal,
    pdfPath,
    rows: amounts.length,
  };
  fs.writeFileSync(path.join(outputDir, `validacao-loja-${storeNumber}.json`), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result));
} catch (error) {
  await page.screenshot({ path: path.join(outputDir, 'erro-consulta-brinks.png'), fullPage: true }).catch(() => {});
  console.error(`URL no erro: ${page.url()}`);
  console.error(`Tela no erro: ${(await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 1200)}`);
  throw error;
} finally {
  await context.close().catch(() => {});
}

async function loginIfNeeded(page) {
  const passwordInput = page.getByRole('textbox', { name: 'Senha', exact: true });
  if (!await passwordInput.isVisible().catch(() => false)) return;
  await page.getByRole('textbox', { name: 'Usuário', exact: true }).fill(user);
  await passwordInput.fill(password);
  await page.getByRole('button', { name: 'Login', exact: true }).click();
  await page.waitForTimeout(1500);
  if (await passwordInput.isVisible().catch(() => false)) {
    throw new Error('Login Brinks nao foi concluido; a tela de autenticacao permaneceu aberta.');
  }
}

async function findAccountForStore(page, storeNumber) {
  await page.getByRole('button', { name: 'Filtros', exact: true }).click();
  await page.waitForTimeout(300);
  const clientSearch = page.locator('input[placeholder="Digite o nome do cliente"]');
  await clientSearch.fill(`DIA BRASIL ${storeNumber}`);
  await page.getByRole('button', { name: 'Aplicar filtro', exact: true }).click();
  await page.waitForTimeout(1200);
  const cards = await page.locator('body').innerText();
  const customerPattern = new RegExp(`N[úu]mero da conta\\s*(\\d+)[\\s\\S]{0,500}?Cliente\\s*DIA BRASIL[^\\n]*${storeNumber}`, 'i');
  const match = cards.match(customerPattern);
  if (!match) throw new Error(`Conta Brinks nao encontrada para a loja ${storeNumber}.`);
  return match[1];
}

async function applyAuditFilter(page, account, date) {
  await selectCalendarDate(page, 0, '#dateStart', date);
  if (await page.locator('#dateStart').inputValue() !== date) throw new Error('Data inicial nao foi aplicada no relatorio Brinks.');
  await selectCalendarDate(page, 1, '#dateEnd', date);
  if (await page.locator('#dateEnd').inputValue() !== date) throw new Error('Data final nao foi aplicada no relatorio Brinks.');
  await page.getByRole('combobox').first().selectOption({ label: 'Depósito' });
  await page.getByRole('textbox', { name: 'Digite o número da conta', exact: true }).fill(account);
  await page.getByRole('button', { name: 'Aplicar filtro', exact: true }).click();
  await page.waitForTimeout(1000);
}

async function selectCalendarDate(page, buttonIndex, selector, value) {
  await page.keyboard.press('Escape').catch(() => {});
  const buttons = await page.getByRole('button', { name: 'Open calendar', exact: true }).all();
  await buttons[buttonIndex].click();
  await page.locator(`td[aria-label="${dateLabel(value)}"]`).last().click({ force: true });
  await page.keyboard.press('Escape').catch(() => {});
  await page.waitForTimeout(300);
  if (await page.locator(selector).inputValue() !== value) {
    throw new Error(`Calendario nao confirmou ${value} para ${selector}.`);
  }
}

function parseMoney(value) {
  return Math.round(Number(String(value).replace(/\./g, '').replace(',', '.')) * 100);
}

function dateLabel(value) {
  const [day, month, year] = value.split('/').map(Number);
  const months = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho', 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];
  return `${day} de ${months[month - 1]} de ${year}`;
}

function formatMoney(value) {
  return (value / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

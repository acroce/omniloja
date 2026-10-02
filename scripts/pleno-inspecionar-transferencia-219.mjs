import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(new URL('..', import.meta.url).pathname);
const env = loadDotEnv(path.join(root, '.env'));
const state = JSON.parse(fs.readFileSync(path.join(root, 'outputs', 'pleno-transacao-transferencia', 'prestacao-contas-aberta.json'), 'utf8'));
const context = await chromium.launchPersistentContext(path.join(root, '.cache', 'pleno-chrome-profile', 'inspecionar-transferencia-219'), {
  executablePath: env.PLENO_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: false,
  ignoreHTTPSErrors: true,
  args: ['--ignore-certificate-errors'],
  viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(Number(env.PLENO_TIMEOUT_MS || 120000));

try {
  await page.goto(state.inspection.url, { waitUntil: 'domcontentloaded' });
  const password = page.locator('input[type="password"]').first();
  if (await password.isVisible().catch(() => false)) {
    await page.locator('#usuario, #Usuario, #username, input[name="usuario"], input[type="text"]').first().fill(env.PLENO_USER);
    await password.fill(env.PLENO_PASSWORD);
    await page.locator('#btnEntrar, #btnLogin, button[type="submit"], input[type="submit"]').first().click();
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.goto(state.inspection.url, { waitUntil: 'domcontentloaded' });
  }
  await page.waitForTimeout(1000);
  const details = await page.evaluate(() => ({
    status: document.querySelector('#fin07Situacao, select[name="fin07Situacao"]')?.value || '',
    plannedDate: document.querySelector('#fin07DataVenctoPrevista, input[name="fin07DataVenctoPrevista"]')?.value || '',
    performedDate: document.querySelector('#fin07DataVenctoRealizada, input[name="fin07DataVenctoRealizada"]')?.value || '',
    documents: Array.from(document.querySelectorAll('a')).map((a) => a.textContent.trim()).filter((text) => /RelAuditoria|Deposito/i.test(text)),
    messages: Array.from(document.querySelectorAll('.alert, .toast, .notification')).map((node) => node.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean),
  }));
  const screenshot = path.join(root, 'outputs', 'pleno-transacao-transferencia', 'inspecao-apos-salvar-loja-219.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  console.log(JSON.stringify({ ...details, screenshot }, null, 2));
} finally {
  await context.close();
}

function loadDotEnv(filePath) {
  if (!fs.existsSync(filePath)) return {};
  return Object.fromEntries(fs.readFileSync(filePath, 'utf8').split(/\r?\n/).flatMap((line) => {
    const match = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    return match ? [[match[1], match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '')]] : [];
  }));
}

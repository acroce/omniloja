import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
const env = loadDotEnv(path.join(projectRoot, '.env'));

const config = {
  url: env.PLENO_TRANSFERENCIA_URL || 'https://172.22.20.101/transacao-transferencia',
  user: env.PLENO_USER,
  password: env.PLENO_PASSWORD,
  chromePath: env.PLENO_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  timeoutMs: Number(env.PLENO_TIMEOUT_MS || 120000),
  navigationTimeoutMs: Number(env.PLENO_NAVIGATION_TIMEOUT_MS || env.PLENO_TIMEOUT_MS || 120000),
};

if (!config.user || !config.password) {
  console.error('Configure PLENO_USER e PLENO_PASSWORD no arquivo .env antes de rodar o robo.');
  process.exit(1);
}

const outputDir = path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile', 'transacao-transferencia-filtros-pendentes-situacao');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const context = await chromium.launchPersistentContext(profileDir, {
  executablePath: config.chromePath,
  headless: false,
  ignoreHTTPSErrors: true,
  args: ['--ignore-certificate-errors', '--start-maximized'],
  viewport: null,
});

const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(config.timeoutMs);
page.setDefaultNavigationTimeout(config.navigationTimeoutMs);

try {
  await openTransferenciaPage(page);
  await applyPendingTransferFilters(page);
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);

  const snapshot = await readGridSnapshot(page);
  const screenshotPath = path.join(outputDir, 'filtro-pendentes-aplicado.png');
  const statePath = path.join(outputDir, 'filtro-pendentes-aplicado.json');
  await page.screenshot({ path: screenshotPath, fullPage: true });
  fs.writeFileSync(
    statePath,
    JSON.stringify(
      {
        filteredAt: new Date().toISOString(),
        url: page.url(),
        filters: {
          situacoes: ['EM ABERTO', 'VENCIDO'],
        },
        snapshot,
        screenshot: screenshotPath,
      },
      null,
      2,
    ) + '\n',
    'utf8',
  );

  console.log('Filtro aplicado e navegador mantido aberto.');
  console.log(`URL atual: ${page.url()}`);
  console.log(`Primeira linha visivel: ${snapshot.firstRowText || 'sem linha visivel'}`);
  console.log(`Screenshot: ${screenshotPath}`);
  console.log(`Estado: ${statePath}`);
  console.log('Pode fechar o navegador por aqui quando terminar de olhar.');
  await new Promise(() => {});
} catch (error) {
  const errorPath = path.join(outputDir, 'erro-filtro-pendentes.png');
  await page.screenshot({ path: errorPath, fullPage: true }).catch(() => {});
  console.error(`Falha ao aplicar filtro de pendentes: ${error.message}`);
  console.error(`Screenshot de erro: ${errorPath}`);
  await context.close().catch(() => {});
  process.exitCode = 1;
}

async function openTransferenciaPage(page) {
  await page.goto(config.url, { waitUntil: 'domcontentloaded' });

  if (await page.locator('input[type="password"]').first().isVisible().catch(() => false)) {
    await page.locator('#usuario, #Usuario, #username, input[name="usuario"], input[type="text"]').first().fill(config.user);
    await page.locator('#senha, #Senha, #password, input[name="senha"], input[type="password"]').first().fill(config.password);
    await page.locator('#btnEntrar, #btnLogin, button[type="submit"], input[type="submit"]').first().click();
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.goto(config.url, { waitUntil: 'domcontentloaded' });
  }

  await page.waitForLoadState('networkidle').catch(() => {});
}

async function applyPendingTransferFilters(page) {
  await page.click('#limpar-filtro').catch(() => {});
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(800);

  await page.click('#btn-filtro-avancado');
  await page.waitForSelector('#dom22Id2, input[name="dom22Id[]"]', { state: 'visible' });

  await page.evaluate(() => {
    const normalize = (value) =>
      String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .toUpperCase();

    setCheckbox('dom22Id1', false);
    setCheckbox('dom22Id2', true);
    setCheckbox('dom22Id3', true);

    function setCheckbox(id, checked) {
      const input = document.getElementById(id);
      if (!input) {
        throw new Error(`Checkbox nao encontrado: ${id}`);
      }
      input.checked = checked;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }
  });

  await page.screenshot({ path: path.join(outputDir, 'filtro-pendentes-pre-pesquisar.png'), fullPage: true });
  await page.click('button.pesquisar, .pesquisar, button:has-text("Pesquisar")');
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function readGridSnapshot(page) {
  return page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('#dataTables tbody tr, table.dataTable tbody tr, tbody tr'))
      .filter((row) => row.offsetParent !== null)
      .map((row) => (row.innerText || row.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    return {
      rowCountVisible: rows.length,
      firstRowText: rows[0] || '',
      firstRows: rows.slice(0, 5),
    };
  });
}

function loadDotEnv(filePath) {
  const values = {};
  if (!fs.existsSync(filePath)) return values;
  for (const line of fs.readFileSync(filePath, 'utf8').split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

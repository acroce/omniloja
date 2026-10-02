import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
loadDotEnv(path.join(projectRoot, '.env'));

const config = {
  transferenciaUrl: process.env.PLENO_TRANSFERENCIA_URL || 'https://172.22.20.101/transacao-transferencia',
  user: process.env.PLENO_USER,
  password: process.env.PLENO_PASSWORD,
  userSelector: process.env.PLENO_USER_SELECTOR,
  passwordSelector: process.env.PLENO_PASSWORD_SELECTOR,
  submitSelector: process.env.PLENO_SUBMIT_SELECTOR,
  chromePath: process.env.PLENO_CHROME_PATH,
  browserChannel: process.env.PLENO_BROWSER_CHANNEL || 'chrome',
  timeoutMs: Number(process.env.PLENO_TIMEOUT_MS || 120000),
  navigationTimeoutMs: Number(process.env.PLENO_NAVIGATION_TIMEOUT_MS || process.env.PLENO_TIMEOUT_MS || 120000),
};

if (!config.user || !config.password) {
  console.error('Configure PLENO_USER e PLENO_PASSWORD no arquivo .env antes de rodar o robo.');
  process.exit(1);
}

const outputDir = path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile', 'transacao-transferencia-primeira-pendente');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const context = await launchChromeProfile(profileDir);
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(config.timeoutMs);
page.setDefaultNavigationTimeout(config.navigationTimeoutMs);

try {
  await openTransferenciaPage(page);
  await page.screenshot({ path: path.join(outputDir, 'antes-abrir-primeira-pendente.png'), fullPage: true });

  const candidate = await findFirstEligibleRow(page);
  if (!candidate) {
    throw new Error('Nao encontrei linha com Origem=CAIXA GERAL, Destino=COFRE INTELIGENTE e Situacao=VENCIDO/EM ABERTO.');
  }

  console.log(`Linha selecionada: filial=${candidate.filial} situacao=${candidate.situacao} valor=${candidate.valorPrevisto}`);
  await clickFirstEligibleRow(page, candidate.rowIndex);
  await page.waitForLoadState('domcontentloaded').catch(() => {});
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);

  const screenshotPath = path.join(outputDir, 'primeira-pendente-aberta.png');
  const statePath = path.join(outputDir, 'primeira-pendente-aberta.json');
  await page.screenshot({ path: screenshotPath, fullPage: true });
  fs.writeFileSync(
    statePath,
    JSON.stringify(
      {
        openedAt: new Date().toISOString(),
        url: page.url(),
        candidate,
        screenshot: screenshotPath,
      },
      null,
      2,
    ) + '\n',
    'utf8',
  );

  console.log(`URL aberta: ${page.url()}`);
  console.log(`Screenshot: ${screenshotPath}`);
  console.log(`Estado: ${statePath}`);
} catch (error) {
  const errorPath = path.join(outputDir, 'erro-abrir-primeira-pendente.png');
  await page.screenshot({ path: errorPath, fullPage: true }).catch(() => {});
  console.error(`Falha ao abrir primeira transferencia pendente: ${error.message}`);
  console.error(`Screenshot de erro: ${errorPath}`);
  process.exitCode = 1;
} finally {
  await context.close().catch(() => {});
}

async function openTransferenciaPage(page) {
  await page.goto(config.transferenciaUrl, { waitUntil: 'domcontentloaded' });

  if (await hasVisiblePasswordField(page)) {
    await fillFirstVisible(page, userLocators(page), config.user, 'usuario');
    await fillFirstVisible(page, passwordLocators(page), config.password, 'senha');
    await clickFirstVisible(page, loginButtonLocators(page), 'botao de login');
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.goto(config.transferenciaUrl, { waitUntil: 'domcontentloaded' });
  }

  await page.waitForLoadState('networkidle').catch(() => {});
}

async function findFirstEligibleRow(page) {
  await page.waitForSelector('table tbody tr, .ui-jqgrid-btable tr, tr', { timeout: config.timeoutMs });

  return page.evaluate(() => {
    const normalize = (value) =>
      String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .toUpperCase();

    const rows = Array.from(document.querySelectorAll('tbody tr, .ui-jqgrid-btable tr')).filter((row) => {
      const cells = Array.from(row.querySelectorAll('td'));
      return cells.length >= 8 && row.offsetParent !== null;
    });

    for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
      const row = rows[rowIndex];
      const cells = Array.from(row.querySelectorAll('td')).map((cell) => cell.innerText || cell.textContent || '');
      const origem = normalize(cells[2]);
      const destino = normalize(cells[3]);
      const situacao = normalize(cells[cells.length - 1]);

      if (
        origem === 'CAIXA GERAL' &&
        destino === 'COFRE INTELIGENTE' &&
        (situacao === 'VENCIDO' || situacao === 'EM ABERTO')
      ) {
        return {
          rowIndex,
          filial: cells[1]?.replace(/\s+/g, ' ').trim() || '',
          origem: cells[2]?.replace(/\s+/g, ' ').trim() || '',
          destino: cells[3]?.replace(/\s+/g, ' ').trim() || '',
          valorPrevisto: cells[4]?.replace(/\s+/g, ' ').trim() || '',
          valorRealizado: cells[5]?.replace(/\s+/g, ' ').trim() || '',
          transfPrevista: cells[6]?.replace(/\s+/g, ' ').trim() || '',
          transfRealizada: cells[7]?.replace(/\s+/g, ' ').trim() || '',
          categoria: cells[cells.length - 2]?.replace(/\s+/g, ' ').trim() || '',
          situacao: cells[cells.length - 1]?.replace(/\s+/g, ' ').trim() || '',
        };
      }
    }

    return null;
  });
}

async function clickFirstEligibleRow(page, rowIndex) {
  const clicked = await page.evaluate((targetRowIndex) => {
    const normalize = (value) =>
      String(value || '')
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
        .toUpperCase();

    const rows = Array.from(document.querySelectorAll('tbody tr, .ui-jqgrid-btable tr')).filter((row) => {
      const cells = Array.from(row.querySelectorAll('td'));
      return cells.length >= 8 && row.offsetParent !== null;
    });
    const row = rows[targetRowIndex];
    if (!row) {
      return false;
    }

    const cells = Array.from(row.querySelectorAll('td'));
    const origem = normalize(cells[2]?.innerText || cells[2]?.textContent);
    const destino = normalize(cells[3]?.innerText || cells[3]?.textContent);
    const situacao = normalize(cells[cells.length - 1]?.innerText || cells[cells.length - 1]?.textContent);
    if (
      origem !== 'CAIXA GERAL' ||
      destino !== 'COFRE INTELIGENTE' ||
      (situacao !== 'VENCIDO' && situacao !== 'EM ABERTO')
    ) {
      return false;
    }

    const actionCell = cells[0];
    const clickable =
      actionCell.querySelector('a, button, input[type="button"], input[type="submit"], [onclick], .fa-pencil, .glyphicon-pencil, img') ||
      actionCell;
    clickable.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
    clickable.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    clickable.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
    clickable.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return true;
  }, rowIndex);

  if (!clicked) {
    throw new Error('A linha elegivel mudou antes do clique; parei para evitar abrir a transferencia errada.');
  }
}

async function launchChromeProfile(userDataDir) {
  const executablePath = config.chromePath || findLocalChrome();
  const options = {
    channel: executablePath ? undefined : config.browserChannel,
    executablePath,
    headless: false,
    ignoreHTTPSErrors: true,
    args: ['--ignore-certificate-errors', '--start-maximized'],
    viewport: null,
  };

  try {
    return await chromium.launchPersistentContext(userDataDir, options);
  } catch (error) {
    if (!executablePath && config.browserChannel === 'chrome') {
      console.warn('Google Chrome nao foi encontrado pelo Playwright. Tentando Chromium embutido.');
      return chromium.launchPersistentContext(userDataDir, {
        ...options,
        channel: undefined,
        executablePath: undefined,
      });
    }
    throw error;
  }
}

async function hasVisiblePasswordField(page) {
  return hasVisibleLocator(passwordLocators(page));
}

async function hasVisibleLocator(locators) {
  for (const locator of locators) {
    if (await locator.count() && await locator.first().isVisible().catch(() => false)) {
      return true;
    }
  }
  return false;
}

async function fillFirstVisible(page, locators, value, fieldName) {
  for (const locator of locators) {
    const target = locator.first();
    if (await target.count() && await target.isVisible().catch(() => false)) {
      await target.fill('');
      await target.fill(value);
      return;
    }
  }

  throw new Error(`Nao encontrei o campo de ${fieldName}. Ajuste o seletor no .env.`);
}

async function clickFirstVisible(page, locators, fieldName) {
  for (const locator of locators) {
    const target = locator.first();
    if (await target.count() && await target.isVisible().catch(() => false)) {
      await target.click();
      return;
    }
  }

  throw new Error(`Nao encontrei ${fieldName}. Ajuste o seletor no .env.`);
}

function userLocators(page) {
  return compact([
    bySelector(page, config.userSelector),
    page.locator('#usuario'),
    page.locator('#Usuario'),
    page.locator('#username'),
    page.locator('#UserName'),
    page.locator('input[name="usuario"]'),
    page.locator('input[name="Usuario"]'),
    page.locator('input[name="username"]'),
    page.locator('input[name="UserName"]'),
    page.locator('input[type="text"]'),
    page.locator('input:not([type])'),
  ]);
}

function passwordLocators(page) {
  return compact([
    bySelector(page, config.passwordSelector),
    page.locator('#senha'),
    page.locator('#Senha'),
    page.locator('#password'),
    page.locator('#Password'),
    page.locator('input[name="senha"]'),
    page.locator('input[name="Senha"]'),
    page.locator('input[name="password"]'),
    page.locator('input[name="Password"]'),
    page.locator('input[type="password"]'),
  ]);
}

function loginButtonLocators(page) {
  return compact([
    bySelector(page, config.submitSelector),
    page.locator('#btnEntrar'),
    page.locator('#btnLogin'),
    page.locator('button[type="submit"]'),
    page.locator('input[type="submit"]'),
    page.getByRole('button', { name: /entrar|login/i }),
    page.locator('input[value="Entrar"]'),
    page.locator('input[value="Login"]'),
  ]);
}

function bySelector(page, selector) {
  return selector ? page.locator(selector) : null;
}

function compact(values) {
  return values.filter(Boolean);
}

function findLocalChrome() {
  const candidates = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    path.join(process.env.HOME || '', 'Applications', 'Google Chrome.app', 'Contents', 'MacOS', 'Google Chrome'),
  ];

  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || undefined;
}

function loadDotEnv(filePath) {
  if (!fs.existsSync(filePath)) {
    return;
  }

  const lines = fs.readFileSync(filePath, 'utf8').split(/\r?\n/);
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) {
      continue;
    }

    const [, key, rawValue] = match;
    if (process.env[key] !== undefined) {
      continue;
    }

    process.env[key] = unquote(rawValue.trim());
  }
}

function unquote(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }

  return value;
}

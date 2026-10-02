import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
loadDotEnv(path.join(projectRoot, '.env'));

const config = {
  loginUrl: process.env.PLENO_URL || 'https://172.22.20.101/Index',
  transferenciaUrl: process.env.PLENO_TRANSFERENCIA_URL || 'https://172.22.20.101/transacao-transferencia',
  user: process.env.PLENO_USER,
  password: process.env.PLENO_PASSWORD,
  userSelector: process.env.PLENO_USER_SELECTOR,
  passwordSelector: process.env.PLENO_PASSWORD_SELECTOR,
  submitSelector: process.env.PLENO_SUBMIT_SELECTOR,
  chromePath: process.env.PLENO_CHROME_PATH,
  browserChannel: process.env.PLENO_BROWSER_CHANNEL || 'chrome',
  keepOpen: process.env.PLENO_TRANSFERENCIA_KEEP_OPEN !== 'false',
  timeoutMs: Number(process.env.PLENO_TIMEOUT_MS || 120000),
  navigationTimeoutMs: Number(process.env.PLENO_NAVIGATION_TIMEOUT_MS || process.env.PLENO_TIMEOUT_MS || 120000),
};

if (!config.user || !config.password) {
  console.error('Configure PLENO_USER e PLENO_PASSWORD no arquivo .env antes de rodar o robo.');
  process.exit(1);
}

const outputDir = path.join(projectRoot, 'outputs', 'pleno-transacao-transferencia');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile', 'transacao-transferencia');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const context = await launchChromeProfile(profileDir);
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(config.timeoutMs);
page.setDefaultNavigationTimeout(config.navigationTimeoutMs);

try {
  await openTransferenciaPage(page);

  const screenshotPath = path.join(outputDir, 'pagina-transacao-transferencia.png');
  await page.screenshot({ path: screenshotPath, fullPage: true });

  console.log('Pagina de transacao/transferencia aberta com sucesso.');
  console.log(`URL atual: ${page.url()}`);
  console.log(`Screenshot: ${screenshotPath}`);

  if (config.keepOpen) {
    console.log('Chrome mantido aberto na pagina. Pressione Ctrl+C neste terminal para encerrar o robo.');
    await new Promise(() => {});
  } else {
    await context.close();
  }
} catch (error) {
  const errorPath = path.join(outputDir, 'erro-transacao-transferencia.png');
  await page.screenshot({ path: errorPath, fullPage: true }).catch(() => {});
  console.error(`Falha ao abrir a pagina de transferencia: ${error.message}`);
  console.error(`Screenshot de erro: ${errorPath}`);
  await context.close().catch(() => {});
  process.exitCode = 1;
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

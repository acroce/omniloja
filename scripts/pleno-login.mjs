import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
loadDotEnv(path.join(projectRoot, '.env'));

const config = {
  url: process.env.PLENO_URL || 'https://172.22.20.101/Index',
  user: process.env.PLENO_USER,
  password: process.env.PLENO_PASSWORD,
  userSelector: process.env.PLENO_USER_SELECTOR,
  passwordSelector: process.env.PLENO_PASSWORD_SELECTOR,
  submitSelector: process.env.PLENO_SUBMIT_SELECTOR,
  browserChannel: process.env.PLENO_BROWSER_CHANNEL || 'chrome',
  keepOpen: process.env.PLENO_KEEP_OPEN !== 'false',
};

if (!config.user || !config.password) {
  console.error('Configure PLENO_USER e PLENO_PASSWORD no arquivo .env antes de rodar o robo.');
  console.error('Exemplo: cp .env.pleno.example .env');
  process.exit(1);
}

const outputDir = path.join(projectRoot, 'outputs', 'pleno-login');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const context = await launchChromeProfile(profileDir);
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(Number(process.env.PLENO_TIMEOUT_MS || 30000));

try {
  await page.goto(config.url, { waitUntil: 'domcontentloaded' });

  await fillFirstVisible(page, userSelectors(), config.user, 'usuario');
  await fillFirstVisible(page, passwordSelectors(), config.password, 'senha');
  await submitLogin(page, submitSelectors());

  await page.waitForLoadState('networkidle').catch(() => {});
  await page.screenshot({ path: path.join(outputDir, 'apos-login.png'), fullPage: true });

  console.log('Login enviado com sucesso.');
  console.log(`Screenshot: ${path.join(outputDir, 'apos-login.png')}`);

  if (config.keepOpen) {
    console.log('Chrome mantido aberto. Pressione Ctrl+C neste terminal para encerrar o robo.');
    await new Promise(() => {});
  }
} catch (error) {
  await page.screenshot({ path: path.join(outputDir, 'erro-login.png'), fullPage: true }).catch(() => {});
  console.error(`Falha no login: ${error.message}`);
  console.error(`Screenshot de erro: ${path.join(outputDir, 'erro-login.png')}`);
  await context.close();
  process.exitCode = 1;
}

async function launchChromeProfile(userDataDir) {
  const options = {
    channel: config.browserChannel,
    headless: false,
    ignoreHTTPSErrors: true,
    args: ['--ignore-certificate-errors', '--start-maximized'],
    viewport: null,
  };

  try {
    return await chromium.launchPersistentContext(userDataDir, options);
  } catch (error) {
    if (config.browserChannel === 'chrome') {
      console.warn('Google Chrome nao foi encontrado pelo Playwright. Tentando Chromium embutido.');
      return chromium.launchPersistentContext(userDataDir, { ...options, channel: undefined });
    }
    throw error;
  }
}

async function fillFirstVisible(page, selectors, value, fieldName) {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (await locator.count() && await locator.isVisible().catch(() => false)) {
      await locator.fill(value);
      return;
    }
  }

  throw new Error(`Nao encontrei o campo de ${fieldName}. Ajuste o seletor no .env.`);
}

async function submitLogin(page, selectors) {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (await locator.count() && await locator.isVisible().catch(() => false)) {
      await Promise.all([
        page.waitForLoadState('domcontentloaded').catch(() => {}),
        locator.click(),
      ]);
      return;
    }
  }

  await page.keyboard.press('Enter');
}

function userSelectors() {
  return compact([
    config.userSelector,
    '#usuario',
    '#Usuario',
    '#username',
    '#UserName',
    'input[name="usuario"]',
    'input[name="Usuario"]',
    'input[name="username"]',
    'input[name="UserName"]',
    'input[type="text"]',
    'input:not([type])',
  ]);
}

function passwordSelectors() {
  return compact([
    config.passwordSelector,
    '#senha',
    '#Senha',
    '#password',
    '#Password',
    'input[name="senha"]',
    'input[name="Senha"]',
    'input[name="password"]',
    'input[name="Password"]',
    'input[type="password"]',
  ]);
}

function submitSelectors() {
  return compact([
    config.submitSelector,
    '#btnEntrar',
    '#btnLogin',
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Entrar")',
    'button:has-text("Login")',
    'input[value="Entrar"]',
    'input[value="Login"]',
  ]);
}

function compact(values) {
  return values.filter(Boolean);
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

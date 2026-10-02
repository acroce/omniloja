import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
loadDotEnv(path.join(projectRoot, '.env'));

const config = {
  loginUrl: process.env.PLENO_URL || 'https://172.22.20.101/Index',
  checkinUrl: process.env.PLENO_CHECKIN_URL || 'https://172.22.20.101/notafiscal-transf-checkin',
  keysFile: process.env.PLENO_CHECKIN_KEYS_FILE || path.join(projectRoot, 'data', 'pleno-checkin-chaves.txt'),
  user: process.env.PLENO_USER,
  password: process.env.PLENO_PASSWORD,
  userSelector: process.env.PLENO_USER_SELECTOR,
  passwordSelector: process.env.PLENO_PASSWORD_SELECTOR,
  submitSelector: process.env.PLENO_SUBMIT_SELECTOR,
  keySelector: process.env.PLENO_CHECKIN_CHAVE_SELECTOR,
  checkinButtonSelector: process.env.PLENO_CHECKIN_BUTTON_SELECTOR,
  chromePath: process.env.PLENO_CHROME_PATH,
  browserChannel: process.env.PLENO_BROWSER_CHANNEL || 'chrome',
  keepOpen: process.env.PLENO_KEEP_OPEN !== 'false',
  afterResultDelayMs: Number(process.env.PLENO_CHECKIN_AFTER_RESULT_DELAY_MS || 0),
  readAfterClickDelayMs: Number(process.env.PLENO_CHECKIN_READ_AFTER_CLICK_MS || 0),
  messageReadDelayMs: Number(process.env.PLENO_CHECKIN_MESSAGE_READ_DELAY_MS || 0),
  resultPollMs: Number(process.env.PLENO_CHECKIN_RESULT_POLL_MS || 200),
  useGenericFeedbackFallback: process.env.PLENO_CHECKIN_USE_GENERIC_FEEDBACK === 'true',
  timeoutMs: Number(process.env.PLENO_TIMEOUT_MS || 120000),
  navigationTimeoutMs: Number(process.env.PLENO_NAVIGATION_TIMEOUT_MS || process.env.PLENO_TIMEOUT_MS || 120000),
  resultTimeoutMs: Number(process.env.PLENO_CHECKIN_RESULT_TIMEOUT_MS || 120000),
  reloadBetweenKeys: process.env.PLENO_CHECKIN_RELOAD_BETWEEN_KEYS !== 'false',
  workers: Math.min(Math.max(Number(process.env.PLENO_CHECKIN_WORKERS || 1), 1), 25),
};

if (!config.user || !config.password) {
  console.error('Configure PLENO_USER e PLENO_PASSWORD no arquivo .env antes de rodar o robo.');
  process.exit(1);
}

const chaves = readNfeKeys(config.keysFile);
if (!chaves.length) {
  console.error(`Nenhuma chave NF-e de 44 digitos encontrada em: ${config.keysFile}`);
  console.error('Preencha uma chave por linha ou use um CSV contendo as chaves.');
  process.exit(1);
}

const outputDir = path.join(projectRoot, 'outputs', 'pleno-checkin-nf');
const profileDir = path.join(projectRoot, '.cache', 'pleno-chrome-profile');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const runTimestamp = new Date().toISOString().replace(/[:.]/g, '-');
const reportPath = path.join(outputDir, `relatorio-checkin-${runTimestamp}.csv`);
const errorPath = path.join(outputDir, `chaves-erro-checkin-${runTimestamp}.csv`);
const errorTxtPath = path.join(outputDir, 'chaves-erro-checkin.txt');
const reportHeader = ['chave', 'status', 'mensagem', 'startedAt', 'finishedAt'];
initializeLiveReports();

const results = [];
let nextKeyIndex = 0;
const dialogMessages = new WeakMap();

try {
  console.log(`Iniciando ${config.workers} instancia(s) para ${chaves.length} chave(s).`);
  await Promise.all(Array.from({ length: config.workers }, (_, index) => runWorker(index + 1)));

  const { reportPath: finalReportPath, errorPath: finalErrorPath } = writeReports(results);
  console.log(`Processamento finalizado. Relatorio: ${finalReportPath}`);
  if (finalErrorPath) {
    console.log(`Chaves com erro/sem confirmacao: ${finalErrorPath}`);
  } else {
    console.log('Nenhuma chave ficou em erro ou sem confirmacao.');
  }

} catch (error) {
  console.error(`Falha geral no check-in: ${error.message}`);
  process.exitCode = 1;
}

async function runWorker(workerId) {
  const workerProfileDir = path.join(profileDir, `worker-${workerId}`);
  fs.mkdirSync(workerProfileDir, { recursive: true });

  const context = await launchChromeProfile(workerProfileDir, workerId);
  const page = context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(config.timeoutMs);
  page.setDefaultNavigationTimeout(config.navigationTimeoutMs);
  setupDialogCapture(page);

  try {
    await openCheckinPage(page);

    while (true) {
      const item = claimNextKey();
      if (!item) {
        break;
      }

      await processKey(page, item.chave, item.index, workerId);
    }
  } catch (error) {
    await page.screenshot({ path: path.join(outputDir, `erro-geral-worker-${workerId}.png`), fullPage: true }).catch(() => {});
    console.error(`[W${workerId}] Falha geral: ${error.message}`);
  } finally {
    if (config.keepOpen) {
      console.log(`[W${workerId}] Chrome mantido aberto. Pressione Ctrl+C neste terminal para encerrar.`);
      await new Promise(() => {});
    } else {
      await context.close().catch(() => {});
    }
  }
}

function claimNextKey() {
  if (nextKeyIndex >= chaves.length) {
    return null;
  }

  const index = nextKeyIndex;
  nextKeyIndex += 1;
  return { index, chave: chaves[index] };
}

async function processKey(page, chave, index, workerId) {
  const startedAt = new Date().toISOString();
  dialogMessages.set(page, '');

  try {
    console.log(`[W${workerId}] [${index + 1}/${chaves.length}] Check-in da chave ${chave}`);
    await ensureCheckinPageReady(page);
    await fillFirstVisible(page, keyLocators(page), chave, 'chave NF');
    await clickFirstVisible(page, checkinButtonLocators(page), 'botao Checkin');
    const pageMessage = await waitForCheckinResult(page);
    const result = classifyCheckinResult(getDialogMessage(page) || pageMessage);

    const row = {
      chave,
      status: result.status,
      mensagem: result.message,
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    results.push(row);
    appendResult(row);

    if (result.isOk) {
      console.log(`[W${workerId}] OK: ${result.message || 'check-in confirmado'}`);
    } else {
      console.error(`[W${workerId}] Pendente/erro: ${result.message || 'sem confirmacao da tela'}`);
    }
  } catch (error) {
    const pageErrorMessage = await readCurrentPageError(page);
    const screenshotPath = path.join(outputDir, `erro-worker-${workerId}-${chave}.png`);
    const message = pageErrorMessage
      ? `${error.message} | retorno pagina: ${pageErrorMessage}`
      : error.message;
    const row = {
      chave,
      status: 'ERRO',
      mensagem: message,
      startedAt,
      finishedAt: new Date().toISOString(),
    };
    results.push(row);
    appendResult(row);
    await page.screenshot({ path: screenshotPath, fullPage: true }).catch(() => {});
    console.error(`[W${workerId}] Erro na chave ${chave}: ${message}`);
  } finally {
    await waitAfterResult();
    await prepareNextKey(page).catch(() => {});
  }
}

function setupDialogCapture(page) {
  dialogMessages.set(page, '');
  page.on('dialog', async (dialog) => {
    dialogMessages.set(page, dialog.message());
    await dialog.accept().catch(() => {});
  });
}

function getDialogMessage(page) {
  return dialogMessages.get(page) || '';
}

async function openCheckinPage(page) {
  await page.goto(config.checkinUrl, { waitUntil: 'domcontentloaded' });

  if (await hasVisiblePasswordField(page)) {
    await fillFirstVisible(page, userLocators(page), config.user, 'usuario');
    await fillFirstVisible(page, passwordLocators(page), config.password, 'senha');
    await clickFirstVisible(page, loginButtonLocators(page), 'botao de login');
    await page.waitForLoadState('networkidle').catch(() => {});
    await page.goto(config.checkinUrl, { waitUntil: 'domcontentloaded' });
  }

  await page.waitForLoadState('networkidle').catch(() => {});
}

async function ensureCheckinPageReady(page) {
  const hasKeyField = await hasVisibleLocator(keyLocators(page));
  const hasCheckinButton = await hasVisibleLocator(checkinButtonLocators(page));

  if (hasKeyField && hasCheckinButton) {
    return;
  }

  await page.goto(config.checkinUrl, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
}

async function prepareNextKey(page) {
  if (config.reloadBetweenKeys) {
    await page.goto(config.checkinUrl, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => {});
    return;
  }

  await clearFirstVisible(page, keyLocators(page));
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

async function launchChromeProfile(userDataDir, workerId = 1) {
  const executablePath = config.chromePath || findLocalChrome();
  const options = {
    channel: executablePath ? undefined : config.browserChannel,
    executablePath,
    headless: false,
    ignoreHTTPSErrors: true,
    args: ['--ignore-certificate-errors', `--window-position=${(workerId - 1) * 35},${(workerId - 1) * 25}`],
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

async function clearFirstVisible(page, locators) {
  for (const locator of locators) {
    const target = locator.first();
    if (await target.count() && await target.isVisible().catch(() => false)) {
      await target.fill('').catch(() => {});
      return;
    }
  }
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

async function waitForCheckinResult(page) {
  const startedAt = Date.now();

  if (config.readAfterClickDelayMs > 0) {
    await page.waitForTimeout(config.readAfterClickDelayMs);
  }

  while (Date.now() - startedAt < config.resultTimeoutMs) {
    const dialogMessage = getDialogMessage(page);
    if (dialogMessage) {
      return cleanCsvValue(dialogMessage);
    }

    await page.waitForLoadState('networkidle', { timeout: 1500 }).catch(() => {});

    const currentMessage = await readStableMensagemRetorno(page);
    if (currentMessage) {
      return currentMessage;
    }

    if (config.useGenericFeedbackFallback) {
      const genericMessage = await readStableFeedback(page);
      if (genericMessage) {
        return genericMessage;
      }
    }

    await page.waitForTimeout(config.resultPollMs);
  }

  const diagnosticsPath = await writePageDiagnostics(page, 'sem-confirmacao');
  return `sem retorno da tela apos ${config.resultTimeoutMs} ms. Diagnostico: ${diagnosticsPath}`;
}

async function waitAfterResult() {
  if (config.afterResultDelayMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, config.afterResultDelayMs));
  }
}

async function readStableFeedback(page) {
  const firstMessage = await readLikelyFeedback(page);
  if (!firstMessage) {
    return '';
  }

  if (config.messageReadDelayMs > 0) {
    await page.waitForTimeout(config.messageReadDelayMs);
  }

  const secondMessage = await readLikelyFeedback(page);
  return secondMessage || firstMessage;
}

async function readStableMensagemRetorno(page) {
  const firstMessage = await readMensagemRetorno(page);
  if (!firstMessage) {
    return '';
  }

  if (config.messageReadDelayMs > 0) {
    await page.waitForTimeout(config.messageReadDelayMs);
  }

  const secondMessage = await readMensagemRetorno(page);
  return secondMessage || firstMessage;
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

function keyLocators(page) {
  return compact([
    bySelector(page, config.keySelector),
    page.locator('#chaveNf'),
    page.locator('#chaveNF'),
    page.locator('#chave'),
    page.locator('#chave_nf'),
    page.locator('input[name="chaveNf"]'),
    page.locator('input[name="chaveNF"]'),
    page.locator('input[name="chave"]'),
    page.locator('input[name="chave_nf"]'),
    page.locator('input[name*="chave" i]'),
    page.getByLabel(/chave\s*nf/i),
    page.getByPlaceholder(/chave\s*nf/i),
    page.locator('input[type="text"]'),
  ]);
}

function checkinButtonLocators(page) {
  return compact([
    bySelector(page, config.checkinButtonSelector),
    page.locator('#btnCheckin'),
    page.locator('#btnCheckIn'),
    page.locator('#checkin'),
    page.locator('#checkIn'),
    page.getByRole('button', { name: /check-?in/i }),
    page.locator('button:has-text("Check-in")'),
    page.locator('button:has-text("Checkin")'),
    page.locator('input[value="Check-in"]'),
    page.locator('input[value="Checkin"]'),
    page.locator('button[type="submit"]'),
    page.locator('input[type="submit"]'),
  ]);
}

async function readLikelyFeedback(page) {
  const mensagemRetorno = await readMensagemRetorno(page);
  if (mensagemRetorno) {
    return mensagemRetorno;
  }

  const coloredMessage = await readColoredPageMessage(page);
  if (coloredMessage) {
    return coloredMessage;
  }

  const candidates = [
    '.alert-danger',
    '.alert-success',
    '.alert-warning',
    '.alert-info',
    '.alert',
    '.alert-dismissible',
    '.message',
    '.msg',
    '.validation-summary-errors',
    '.field-validation-error',
    '.text-danger',
    '.toast',
    '.toast-message',
    '.notify',
    '.notification',
    '.swal-text',
    '.bootbox-body',
    '.modal-body',
    '[role="alert"]',
  ];

  for (const selector of candidates) {
    const locator = page.locator(selector).first();
    if (await locator.count() && await locator.isVisible().catch(() => false)) {
      return cleanCsvValue(await locator.textContent());
    }
  }

  return '';
}

async function readMensagemRetorno(page) {
  return page
    .locator('#mensagem-retorno')
    .evaluate((container) => {
      const alerts = Array.from(container.querySelectorAll(':scope > .alert, :scope > div'));
      return alerts
        .map((node) => (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim())
        .filter(Boolean)
        .join(' | ');
    })
    .then(cleanCsvValue)
    .catch(() => '');
}

async function readColoredPageMessage(page) {
  return page
    .locator('body *')
    .evaluateAll((nodes) => {
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 1000;
      const candidates = [];

      for (const node of nodes) {
        const element = node instanceof HTMLElement ? node : null;
        if (!element) {
          continue;
        }

        const text = (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim();
        if (!text || text.length < 3 || text.length > 400) {
          continue;
        }

        const rect = element.getBoundingClientRect();
        if (rect.width < 120 || rect.height < 20 || rect.bottom < 0 || rect.top > viewportHeight) {
          continue;
        }

        const style = window.getComputedStyle(element);
        const colors = [
          style.backgroundColor,
          style.borderTopColor,
          style.borderRightColor,
          style.borderBottomColor,
          style.borderLeftColor,
          style.color,
        ];
        const colorKind = colors.map(classifyColor).find(Boolean);
        if (!colorKind) {
          continue;
        }

        candidates.push({
          text,
          top: rect.top,
          area: rect.width * rect.height,
          colorKind,
        });
      }

      candidates.sort((a, b) => a.top - b.top || b.area - a.area);
      return candidates[0]?.text || '';

      function classifyColor(value) {
        const match = String(value || '').match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/i);
        if (!match) {
          return '';
        }

        const red = Number(match[1]);
        const green = Number(match[2]);
        const blue = Number(match[3]);

        if (red > 150 && green < 120 && blue < 120) return 'red';
        if (green > 120 && red < 160 && blue < 160) return 'green';
        if (red > 150 && green > 120 && blue < 120) return 'yellow';
        if (blue > 140 && red < 150) return 'blue';
        if (red > 220 && green > 170 && green < 230 && blue > 170 && blue < 230) return 'light-red';
        if (green > 180 && red > 170 && red < 230 && blue > 170 && blue < 230) return 'light-green';
        return '';
      }
    })
    .catch(() => '');
}

async function readCurrentPageError(page) {
  const feedback = await readMensagemRetorno(page);
  if (feedback) {
    return feedback;
  }

  if (config.useGenericFeedbackFallback) {
    const genericFeedback = await readLikelyFeedback(page);
    if (genericFeedback) {
      return genericFeedback;
    }
  }

  return '';
}

async function writePageDiagnostics(page, name) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const basePath = path.join(outputDir, `${name}-${timestamp}`);
  const textPath = `${basePath}.txt`;

  const visibleText = await page.locator('body').innerText().catch(() => '');
  const alerts = await page
    .locator('.alert, .alert-danger, .alert-success, .alert-warning, [role="alert"], .text-danger')
    .evaluateAll((nodes) => nodes.map((node) => node.textContent?.trim()).filter(Boolean))
    .catch(() => []);

  fs.writeFileSync(
    textPath,
    [
      `URL: ${page.url()}`,
      '',
      'ALERTAS:',
      ...alerts,
      '',
      'TEXTO VISIVEL:',
      visibleText,
    ].join('\n'),
    'utf8',
  );
  await page.screenshot({ path: `${basePath}.png`, fullPage: true }).catch(() => {});
  console.error(`Diagnostico da pagina salvo em: ${textPath}`);
  return textPath;
}

function classifyCheckinResult(rawMessage) {
  const message = cleanCsvValue(rawMessage);
  const normalized = normalizeText(message);

  if (
    normalized.includes('nf ja fechada') ||
    normalized.includes('nota ja fechada') ||
    normalized.includes('ja fechada') ||
    normalized.includes('ja fechado') ||
    normalized.includes('ja tem checkin') ||
    normalized.includes('ja possui checkin') ||
    normalized.includes('checkin ja realizado') ||
    normalized.includes('check in ja realizado') ||
    normalized.includes('check-in ja realizado')
  ) {
    return { status: 'OK_JA_FECHADA', message: message || 'NF ja fechada / check-in ja existente', isOk: true };
  }

  if (
    normalized.includes('sucesso') ||
    normalized.includes('realizado') ||
    normalized.includes('efetuado') ||
    normalized.includes('confirmado') ||
    normalized.includes('salvo') ||
    normalized === 'ok'
  ) {
    return { status: 'OK', message: message || 'check-in confirmado', isOk: true };
  }

  if (
    normalized.includes('erro') ||
    normalized.includes('falha') ||
    normalized.includes('sem retorno da tela') ||
    normalized.includes('inval') ||
    normalized.includes('nao encontr') ||
    normalized.includes('nao existe') ||
    normalized.includes('inexistente') ||
    normalized.includes('nfe inexistente no inbound') ||
    normalized.includes('nf e inexistente no inbound') ||
    normalized.includes('id 144 portaria 4tax') ||
    normalized.includes('erro desconhecido') ||
    normalized.includes('obrigatorio') ||
    normalized.includes('nao foi possivel')
  ) {
    return { status: 'ERRO', message: message || 'erro informado pela tela', isOk: false };
  }

  return {
    status: 'SEM_CONFIRMACAO',
    message: message || `sem retorno da tela apos ${config.resultTimeoutMs} ms`,
    isOk: false,
  };
}

function extractKnownResultMessage(bodyText) {
  const normalized = normalizeText(bodyText);
  const markers = [
    'nf ja fechada',
    'nota ja fechada',
    'ja fechada',
    'ja possui checkin',
    'checkin ja realizado',
    'sucesso',
    'realizado',
    'efetuado',
    'confirmado',
    'erro',
    'falha',
    'nao encontr',
    'nao existe',
    'inexistente',
    'nfe inexistente no inbound',
    'nf e inexistente no inbound',
    'id 144 portaria 4tax',
    'erro desconhecido',
    'obrigatorio',
  ];

  const marker = markers.find((item) => normalized.includes(item));
  if (!marker) {
    return '';
  }

  const sentences = bodyText.split(/(?<=[.!?])\s+|\n+/).map(cleanCsvValue).filter(Boolean);
  return sentences.find((sentence) => normalizeText(sentence).includes(marker)) || marker;
}

function readNfeKeys(filePath) {
  if (!fs.existsSync(filePath)) {
    return [];
  }

  const seen = new Set();
  const keys = [];
  const text = fs.readFileSync(filePath, 'utf8');

  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) {
      continue;
    }

    const matches = trimmed.match(/\d{44}/g) || [];
    for (const key of matches) {
      if (!seen.has(key)) {
        seen.add(key);
        keys.push(key);
      }
    }
  }

  return keys;
}

function findLocalChrome() {
  const candidates = [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    path.join(process.env.HOME || '', 'Applications', 'Google Chrome.app', 'Contents', 'MacOS', 'Google Chrome'),
  ];

  return candidates.find((candidate) => candidate && fs.existsSync(candidate)) || undefined;
}

function initializeLiveReports() {
  fs.writeFileSync(reportPath, `${reportHeader.join(';')}\n`, 'utf8');
  fs.writeFileSync(errorPath, `${reportHeader.join(';')}\n`, 'utf8');
  fs.writeFileSync(errorTxtPath, '', 'utf8');
}

function appendResult(row) {
  fs.appendFileSync(reportPath, `${formatCsvRow(row)}\n`, 'utf8');

  if (row.status === 'ERRO' || row.status === 'SEM_CONFIRMACAO') {
    fs.appendFileSync(errorPath, `${formatCsvRow(row)}\n`, 'utf8');
    fs.appendFileSync(errorTxtPath, `${row.chave}\n`, 'utf8');
  }
}

function formatCsvRow(row) {
  return reportHeader.map((key) => cleanCsvValue(row[key])).join(';');
}

function writeReports(rows) {
  const lines = [
    reportHeader.join(';'),
    ...rows.map(formatCsvRow),
  ];
  fs.writeFileSync(reportPath, `${lines.join('\n')}\n`, 'utf8');

  const errorRows = rows.filter((row) => row.status === 'ERRO' || row.status === 'SEM_CONFIRMACAO');
  if (errorRows.length) {
    const errorLines = [
      reportHeader.join(';'),
      ...errorRows.map(formatCsvRow),
    ];
    fs.writeFileSync(errorPath, `${errorLines.join('\n')}\n`, 'utf8');
    fs.writeFileSync(
      errorTxtPath,
      `${errorRows.map((row) => row.chave).join('\n')}\n`,
      'utf8',
    );
    return { reportPath, errorPath };
  }

  return { reportPath, errorPath: '' };
}

function bySelector(page, selector) {
  return selector ? page.locator(selector) : null;
}

function compact(values) {
  return values.filter(Boolean);
}

function cleanCsvValue(value) {
  return String(value || '').replace(/\s+/g, ' ').replace(/;/g, ',').trim();
}

function normalizeText(value) {
  return cleanCsvValue(value)
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[-_]/g, ' ')
    .toLowerCase();
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

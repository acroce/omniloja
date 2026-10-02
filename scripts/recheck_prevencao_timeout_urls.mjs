import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(new URL('..', import.meta.url).pathname);
loadDotEnv(path.join(root, '.env'));

const urls = parseUrls(process.env.PREV_PERDAS_RECHECK_URLS || process.argv.slice(2).join('\n'));
if (!urls.length) {
  console.error('Informe URLs em PREV_PERDAS_RECHECK_URLS ou como argumentos.');
  process.exit(2);
}

const out = path.join(root, 'outputs', 'prevencao_perdas');
const runId = Date.now();
const profile = path.join(root, '.cache', 'pleno-chrome-profile', 'prevencao-perdas-recheck', `run-${runId}`);
fs.mkdirSync(out, { recursive: true });

const chrome = Object.hasOwn(process.env, 'PLENO_CHROME_PATH')
  ? process.env.PLENO_CHROME_PATH || undefined
  : process.env.PLENO_CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined);

const context = await chromium.launchPersistentContext(profile, {
  ...(chrome ? { executablePath: chrome } : {}),
  headless: false,
  ignoreHTTPSErrors: true,
  args: ['--ignore-certificate-errors', '--start-maximized'],
  viewport: null,
});

const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(Number(process.env.PREV_PERDAS_TIMEOUT_MS || 90000));

const results = [];
try {
  for (const url of urls) {
    const result = await inspectNota(page, url).catch((error) => ({
      url,
      status: 'erro',
      error: error.message,
    }));
    results.push(result);
    console.log(JSON.stringify(result, ensureJson));
  }
} finally {
  await context.close().catch(() => {});
}

console.log(JSON.stringify({ totals: summarize(results), results }, ensureJson, 2));

async function inspectNota(p, url) {
  await gotoPleno(p, url);
  await loginPleno(p, url);
  await waitNotaScreen(p);
  await waitAriusIdle(p);

  const fields = await p.evaluate(() => {
    const normalize = (value) => String(value || '')
      .normalize('NFD')
      .replace(/\p{Diacritic}/gu, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toUpperCase();
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const controls = Array.from(document.querySelectorAll('input,select,textarea')).filter(visible);
    const byLabel = (wanted) => {
      const labels = Array.from(document.querySelectorAll('label')).filter((label) => visible(label) && normalize(label.innerText || label.textContent).replace(/\*$/, '') === wanted);
      for (const label of labels) {
        const explicit = label.getAttribute('for') ? document.getElementById(label.getAttribute('for')) : null;
        if (explicit && visible(explicit)) return valueOf(explicit);
        const sameParent = Array.from(label.parentElement?.querySelectorAll('input,select,textarea') || []).find((control) => visible(control));
        if (sameParent) return valueOf(sameParent);
        const labelRect = label.getBoundingClientRect();
        const nearby = controls
          .map((control) => ({ control, rect: control.getBoundingClientRect() }))
          .filter(({ rect }) => rect.top >= labelRect.bottom - 8 && Math.abs(rect.left - labelRect.left) < 120 && rect.top - labelRect.bottom < 55)
          .sort((a, b) => (a.rect.top - labelRect.bottom) - (b.rect.top - labelRect.bottom))[0]?.control;
        if (nearby) return valueOf(nearby);
      }
      return '';
    };
    const valueOf = (element) => {
      if (element.tagName === 'SELECT') return element.selectedOptions?.[0]?.textContent?.trim() || element.value || '';
      return element.value || '';
    };
    const controlsText = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .filter(visible)
      .map((element) => `${element.textContent || ''} ${element.value || ''} ${element.title || ''}`.replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    return {
      numero: byLabel('NUMERO'),
      serie: byLabel('SERIE'),
      emissao: byLabel('EMISSAO'),
      entradaSaida: byLabel('ENTRADA/SAIDA'),
      situacao: byLabel('SITUACAO'),
      chaveNfe: byLabel('CHAVE NFE'),
      protocolo: byLabel('PROTOCOLO'),
      controlsText,
      body: (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 1000),
    };
  });

  const hasDanfe = fields.controlsText.some((text) => /DANFE/i.test(text));
  const hasCancel = fields.controlsText.some((text) => /Cancelar\s+NF-e/i.test(text));
  const hasEmit = fields.controlsText.some((text) => /Emitir\s*NF/i.test(text));
  const isClosed = /FECHADA/i.test(fields.situacao || '') || (hasDanfe && hasCancel);
  const hasNfeKey = /\d{20,}/.test(fields.chaveNfe || '');
  const emitted = isClosed || hasNfeKey || (fields.emissao && hasDanfe);
  return {
    url,
    status: emitted ? 'emitida' : 'ainda_pendente',
    numero: fields.numero,
    emissao: fields.emissao,
    situacao: fields.situacao,
    chaveNfe: fields.chaveNfe ? `${fields.chaveNfe.slice(0, 8)}...${fields.chaveNfe.slice(-6)}` : '',
    protocolo: fields.protocolo,
    hasDanfe,
    hasEmit,
  };
}

async function gotoPleno(p, url) {
  await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.waitForFunction(() => {
    const text = document.body?.innerText || '';
    return /Edi[cç][aã]o\s+NF|senha|usuario|usu[aá]rio/i.test(text) ||
      Boolean(document.querySelector('#senha,#Senha,input[type=password]'));
  }, null, { timeout: 60000 });
}

async function loginPleno(p, url) {
  const password = p.locator('#senha,#Senha,#password,input[name=senha],input[type=password]:visible').first();
  if (!await password.isVisible().catch(() => false)) return;
  if (!process.env.PLENO_USER || !process.env.PLENO_PASSWORD) throw new Error('Configure PLENO_USER e PLENO_PASSWORD no .env.');
  for (let attempt = 1; attempt <= 3; attempt++) {
    const username = p.locator('#usuario,#Usuario,#username,input[name=usuario],input[type=text]:visible').first();
    await fillValue(username, process.env.PLENO_USER);
    await fillValue(password, process.env.PLENO_PASSWORD);
    const login = p.locator('#btnEntrar,#btnLogin,button[type=submit],input[type=submit]').first();
    if (attempt === 2) await password.press('Enter');
    else await login.click().catch(() => password.press('Enter'));
    await p.waitForTimeout(5000);
    if (!await password.isVisible().catch(() => false)) {
      await gotoPleno(p, url);
      return;
    }
    await p.reload({ waitUntil: 'domcontentloaded' });
  }
  throw new Error('Login no Pleno nao foi concluido apos 3 tentativas.');
}

async function waitNotaScreen(p) {
  await p.waitForFunction(() => /Edi[cç][aã]o\s+NF\s+Transfer[eê]ncia\s+Sa[ií]da/i.test(document.body?.innerText || ''), null, { timeout: 90000 });
}

async function waitAriusIdle(p) {
  await p.waitForFunction(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const center = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    return !(center && visible(center) && /arius|carreg|load|process/i.test(`${center.textContent || ''} ${center.className || ''}`));
  }, null, { timeout: 60000 }).catch(() => {});
}

async function fillValue(locator, value) {
  await locator.click({ force: true });
  await locator.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
  await locator.fill(String(value));
  await locator.dispatchEvent('change').catch(() => {});
}

function parseUrls(value) {
  return [...new Set(String(value || '')
    .split(/[\n, ]+/)
    .map((url) => url.trim())
    .filter((url) => /^https?:\/\//i.test(url)))];
}

function summarize(rows) {
  return rows.reduce((acc, row) => {
    acc[row.status] = (acc[row.status] || 0) + 1;
    return acc;
  }, {});
}

function loadDotEnv(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const match = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (match && process.env[match[1]] === undefined) process.env[match[1]] = match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '');
  }
}

function ensureJson(key, value) {
  return value === undefined ? null : value;
}

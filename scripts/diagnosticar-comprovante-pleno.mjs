import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const transactionId = Number(process.argv[2]);
if (!Number.isInteger(transactionId) || transactionId <= 0) {
  throw new Error('Uso: node scripts/diagnosticar-comprovante-pleno.mjs <id-da-transferencia>');
}

const root = path.resolve(new URL('..', import.meta.url).pathname);
const env = dotenv(path.join(root, '.env'));
const out = path.join(root, 'outputs', 'tesouraria_cofre_inteligente');
const chrome = Object.hasOwn(process.env, 'PLENO_CHROME_PATH')
  ? process.env.PLENO_CHROME_PATH || undefined
  : env.PLENO_CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined);
fs.mkdirSync(out, { recursive: true });

const context = await chromium.launchPersistentContext(
  path.join(root, '.cache', 'pleno-chrome-profile', 'diagnostico-comprovante'),
  {
    ...(chrome ? { executablePath: chrome } : {}),
    headless: true,
    ignoreHTTPSErrors: true,
    acceptDownloads: true,
    downloadsPath: out,
  },
);

try {
  const page = context.pages()[0] || await context.newPage();
  page.setDefaultTimeout(30000);
  const listUrl = env.PLENO_TRANSFERENCIA_URL || 'https://172.22.20.101/transacao-transferencia';
  await page.goto(`${listUrl}/editar/id/${transactionId}`, { waitUntil: 'domcontentloaded' });
  await loginPleno(page, listUrl);
  await page.goto(`${listUrl}/editar/id/${transactionId}`, { waitUntil: 'domcontentloaded' });

  const attachment = page.locator('a[href*="download-arquivo-ajax/"]').first();
  await attachment.waitFor({ state: 'visible' });
  const [download] = await Promise.all([page.waitForEvent('download'), attachment.click()]);
  const suggested = typeof download.suggestedFilename === 'function' ? download.suggestedFilename() : '';
  const ext = /\.pdf$/i.test(suggested) ? '.pdf' : /\.(jpe?g|png)$/i.test(suggested) ? path.extname(suggested).toLowerCase() : '.bin';
  const target = path.join(out, `diagnostico_comprovante_${transactionId}${ext}`);
  await download.saveAs(target);
  const normalizedTarget = normalizeAttachment(target);

  console.log(`ARQUIVO=${normalizedTarget}`);
  console.log(`TAMANHO=${fs.statSync(normalizedTarget).size}`);
  console.log('--- TESSERACT ---');
  console.log(runTesseract(normalizedTarget).trim());
  console.log('--- PADDLE ONNX ---');
  try {
    console.log(runPaddle(normalizedTarget).trim());
  } catch (error) {
    console.log(`PADDLE_ERRO=${error.message}`);
  }
} finally {
  await context.close();
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
  throw new Error('O anexo do Pleno nao contem JPEG nem PDF valido.');
}

function runTesseract(file) {
  const isPdf = path.extname(file).toLowerCase() === '.pdf';
  const normalized = isPdf ? file.replace(/\.[^.]+$/, '.png') : `${file}.png`;
  try {
    if (isPdf) {
      execFileSync(process.env.PDFTOPPM_BIN || 'pdftoppm', ['-f', '1', '-singlefile', '-png', file, normalized.replace(/\.png$/, '')]);
    } else {
      execFileSync('python3', [
        '-c',
        'from PIL import Image,ImageFile; import sys; ImageFile.LOAD_TRUNCATED_IMAGES=True; image=Image.open(sys.argv[1]); image.load(); image.save(sys.argv[2])',
        file,
        normalized,
      ]);
    }
    return execFileSync(process.env.TESSERACT_BIN || 'tesseract', [normalized, 'stdout', '-l', 'por+eng', '--psm', '6'], { encoding: 'utf8' });
  } catch (error) {
    if (isPdf && error.code === 'ENOENT') throw new Error('Comprovante PDF requer poppler-utils/pdftoppm instalado para OCR no Linux.');
    throw error;
  } finally {
    fs.rmSync(normalized, { force: true });
  }
}

function runPaddle(file) {
  const python = process.env.OCR_PADDLE_ONNX_PYTHON || path.join(root, '.venv-paddle-onnx312', 'bin', 'python');
  return execFileSync(python, [path.join(root, 'scripts', 'ocr_paddle_onnx_portugues.py'), file], {
    encoding: 'utf8',
    timeout: Number(process.env.OCR_PADDLE_ONNX_TIMEOUT_MS || 15000),
  });
}

async function fillCredential(field, value) {
  await field.click({ force: true });
  await field.press('Control+A');
  await field.pressSequentially(value, { delay: 70 });
  if (await field.inputValue() !== value) await field.fill(value);
}

async function loginPleno(page, listUrl) {
  const password = page.locator('#senha,#Senha,#password,input[name=senha],input[type=password]:visible').first();
  if (!await password.isVisible().catch(() => false)) return;
  const username = page.locator('#usuario,#Usuario,#username,input[name=usuario],input[type=text]:visible').first();
  await fillCredential(username, env.PLENO_USER);
  await fillCredential(password, env.PLENO_PASSWORD);
  await page.locator('#btnEntrar,#btnLogin,button[type=submit],input[type=submit]').first().click();
  await page.waitForTimeout(4000);
  if (await password.isVisible().catch(() => false)) throw new Error('Login no Pleno nao foi concluido no diagnostico.');
  await page.goto(listUrl, { waitUntil: 'domcontentloaded' });
}

function dotenv(file) {
  if (!fs.existsSync(file)) return {};
  return Object.fromEntries(fs.readFileSync(file, 'utf8').split(/\r?\n/).flatMap(line => {
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    return match ? [[match[1], match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '')]] : [];
  }));
}

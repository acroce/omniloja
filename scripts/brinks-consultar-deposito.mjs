import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const projectRoot = path.resolve(new URL('..', import.meta.url).pathname);
const outputDir = path.join(projectRoot, 'outputs', 'brinks');
const profileDir = path.join(projectRoot, '.cache', 'brinks-chrome-profile');
fs.mkdirSync(outputDir, { recursive: true });
fs.mkdirSync(profileDir, { recursive: true });

const context = await chromium.launchPersistentContext(profileDir, {
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: false,
  viewport: null,
  args: ['--start-maximized'],
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(120000);

try {
  await page.goto('https://www.brinks24seven.com.br/pt/login', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => {});
  await page.waitForTimeout(1500);
  const state = await page.evaluate(() => ({
    url: location.href,
    title: document.title,
    text: document.body.innerText.replace(/\s+/g, ' ').trim(),
    passwordVisible: Array.from(document.querySelectorAll('input[type="password"]')).some((input) => input.offsetParent !== null),
  }));
  const screenshot = path.join(outputDir, 'brinks-login-ou-sessao.png');
  await page.screenshot({ path: screenshot, fullPage: true });
  fs.writeFileSync(path.join(outputDir, 'brinks-login-ou-sessao.json'), JSON.stringify({ openedAt: new Date().toISOString(), ...state, screenshot }, null, 2) + '\n');
  console.log(`URL atual: ${state.url}`);
  console.log(`Login visivel: ${state.passwordVisible ? 'sim' : 'nao'}`);
  console.log(`Screenshot: ${screenshot}`);
  console.log('Navegador mantido aberto.');
  await new Promise(() => {});
} catch (error) {
  console.error(error.stack || error.message);
  await context.close().catch(() => {});
  process.exitCode = 1;
}

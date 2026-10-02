import { chromium } from 'playwright';

const context = await chromium.launchPersistentContext('.cache/brinks-chrome-profile/sessao-teste', {
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: false,
  viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(30000);

await page.goto('https://www.brinks24seven.com.br/pt/login', { waitUntil: 'domcontentloaded' });
const username = page.locator('input[placeholder="Usuário"],input[placeholder="Usuario"],input:visible:not([type=password])').first();
const password = page.locator('input[placeholder="Senha"],input[type=password]:visible').first();
if (await password.isVisible().catch(() => false)) {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await username.fill(process.env.BRINKS_USER);
    await password.fill(process.env.BRINKS_PASSWORD);
    const login = page.locator('button:has-text("Login"),button[type=submit],input[type=submit]').first();
    if (attempt === 1) await login.click();
    else if (attempt === 2) await password.press('Enter');
    else await login.evaluate((button) => button.click());
    await page.waitForTimeout(5000);
    if (!await password.isVisible().catch(() => false)) break;
  }
}
if (await password.isVisible().catch(() => false)) throw new Error('Login Brinks nao foi concluido apos 3 tentativas.');
await page.goto('https://www.brinks24seven.com.br/pt/control-panel', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(2000);
console.log(`Sessao Brinks autenticada e mantida aberta em ${page.url()}.`);
await new Promise(() => {});

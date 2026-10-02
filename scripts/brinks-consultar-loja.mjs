import { chromium } from 'playwright';

const store = process.env.BRINKS_STORE || '287';
const context = await chromium.launchPersistentContext('.cache/brinks-chrome-profile/consulta-loja', {
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: false, viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(45000);
await page.goto('https://www.brinks24seven.com.br/pt/login', { waitUntil: 'domcontentloaded' });
await login(page);
await page.goto('https://www.brinks24seven.com.br/pt/control-panel', { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(3000);
console.log(`Tela Brinks: ${await page.title()} | ${page.url()}`);
if (await page.locator('input[placeholder="Senha"],input[type=password]:visible').first().isVisible().catch(() => false)) {
  throw new Error('A sessao nao foi autenticada: a Brinks voltou para o login.');
}

const filtersButton = page.getByRole('button', { name: 'Filtros', exact: true });
if (await filtersButton.isVisible().catch(() => false)) await filtersButton.click();

const selects = page.locator('select');
console.log(`Seletores encontrados: ${await selects.count()}`);
console.log(await selects.evaluateAll((items) => items.map((item, index) => ({
  index,
  name: item.getAttribute('name'),
  id: item.id,
  ariaLabel: item.getAttribute('aria-label'),
  options: Array.from(item.options).slice(0, 8).map((option) => option.text.trim()),
}))));

const inputs = page.locator('input');
console.log('Campos de texto:', await inputs.evaluateAll((items) => items.map((item, index) => ({
  index,
  id: item.id,
  name: item.getAttribute('name'),
  type: item.type,
  placeholder: item.getAttribute('placeholder'),
  ariaLabel: item.getAttribute('aria-label'),
  parentText: item.parentElement?.parentElement?.innerText?.slice(0, 120),
}))));

const sigla = page.locator('#filter-customer-acronym, input[placeholder*="Sigla" i], input[aria-label*="Sigla" i], input[aria-label="Number"]').first();
if (!await sigla.count()) throw new Error('Campo "Sigla do cliente" nao foi encontrado no painel Brinks.');
await sigla.click();
await page.waitForTimeout(400);
const search = page.locator('input[placeholder="Selecione..."]').last();
if (await page.locator('input[placeholder="Selecione..."]').count() < 2) {
  throw new Error('A caixa de busca da lista de siglas nao foi aberta.');
}
await search.click();
await search.pressSequentially(store, { delay: 140 });
await page.waitForTimeout(1200);
const option = page.getByText(store, { exact: true }).last();
if (!await option.isVisible().catch(() => false)) throw new Error(`A opcao ${store} nao foi exibida na lista de siglas.`);
await option.click();
console.log(`Sigla selecionada: ${await sigla.inputValue()}`);
await page.getByRole('button', { name: 'Aplicar filtro', exact: true }).click();
await page.waitForTimeout(2500);
const details = page.getByRole('button', { name: 'Ver detalhes', exact: true });
const results = await details.count();
console.log(`Registros retornados para a sigla ${store}: ${results}`);
if (results !== 1) {
  console.log((await page.locator('body').innerText()).slice(-3000));
  throw new Error(`Esperado um registro para a sigla ${store}; a Brinks retornou ${results}.`);
}
await details.first().click();
await page.waitForTimeout(1200);
const detailText = await page.locator('body').innerText();
const account = detailText.match(/Número da conta[^\d]*(\d{4,})/i)?.[1];
if (!account) {
  console.log(detailText.slice(0, 3500));
  throw new Error('Numero da conta nao foi encontrado no detalhe da loja Brinks.');
}
console.log(`Conta Brinks da loja ${store}: ${account}`);
await page.goto('https://www.brinks24seven.com.br/pt/static-report/audit-report', { waitUntil: 'domcontentloaded' });
await page.locator('app-subheader').getByText('Relatório de Auditoria', { exact: true }).waitFor({ state: 'visible' });
await page.getByRole('textbox', { name: 'Digite o número da conta', exact: true }).fill(account);
console.log('Relatorio de Auditoria aberto com a conta preenchida.');
await new Promise(() => {});

async function login(page) {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const password = page.locator('input[placeholder="Senha"],input[type=password]:visible').first();
    const formVisible = await password.waitFor({ state: 'visible', timeout: 10000 }).then(() => true).catch(() => false);
    if (!formVisible) {
      if (!page.url().includes('/login')) return;
      await page.reload({ waitUntil: 'domcontentloaded' });
      continue;
    }
    const username = page.locator('input[placeholder="Usuário"],input[placeholder="Usuario"],input:visible:not([type=password])').first();
    await username.fill(process.env.BRINKS_USER);
    await password.fill(process.env.BRINKS_PASSWORD);
    if (attempt === 1) await page.locator('button:has-text("Login"),button[type=submit]').first().click();
    else if (attempt === 2) await password.press('Enter');
    else await page.locator('button:has-text("Login"),button[type=submit]').first().evaluate((button) => button.click());
    await page.waitForTimeout(5000);
    if (!page.url().includes('/login') && !await password.isVisible().catch(() => false)) return;
    await page.reload({ waitUntil: 'domcontentloaded' });
  }
  throw new Error('Login Brinks nao foi concluido.');
}

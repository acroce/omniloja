import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const rootDir = path.resolve(__dirname, "..");
const chromeUserDataDir = path.join(
  process.env.HOME || "",
  "Library",
  "Application Support",
  "Google",
  "Chrome",
);

const DEFAULT_RECIPIENT = "marcela.silva@diagroup.com";

function loadEnv(envPath) {
  if (!fs.existsSync(envPath)) return;

  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const [key, ...valueParts] = line.split("=");
    let value = valueParts.join("=").trim();
    if (
      value.length >= 2 &&
      ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    if (!process.env[key.trim()]) {
      process.env[key.trim()] = value;
    }
  }
}

loadEnv(path.join(rootDir, ".env"));

function resolveChromeProfileDirectory() {
  if (process.env.GOOGLE_CHAT_CHROME_PROFILE_DIRECTORY) {
    return process.env.GOOGLE_CHAT_CHROME_PROFILE_DIRECTORY;
  }

  const localStatePath = path.join(chromeUserDataDir, "Local State");
  if (!fs.existsSync(localStatePath)) {
    return "Default";
  }

  try {
    const localState = JSON.parse(fs.readFileSync(localStatePath, "utf8"));
    const profiles = localState?.profile?.info_cache || {};
    for (const [directory, info] of Object.entries(profiles)) {
      const values = [
        info?.name,
        info?.gaia_name,
        info?.user_name,
        info?.hosted_domain,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      if (values.includes("diagroup.com") || values.includes("dia group")) {
        return directory;
      }
    }
  } catch {
    return "Default";
  }

  return "Default";
}

function parseArgs() {
  const args = {
    date: new Date().toISOString().slice(0, 10),
    recipient: DEFAULT_RECIPIENT,
  };

  for (let index = 2; index < process.argv.length; index += 1) {
    const arg = process.argv[index];
    const next = process.argv[index + 1];
    if (arg === "--date" && next) {
      args.date = next;
      index += 1;
    } else if (arg === "--recipient" && next) {
      args.recipient = next;
      index += 1;
    }
  }

  return args;
}

function resolveReportFiles(reportDate) {
  const compactDate = reportDate.replaceAll("-", "");
  const outputDir = path.join(rootDir, "outputs", "daily_pleno_reports", compactDate);
  const files = fs
    .readdirSync(outputDir)
    .filter((name) => name.endsWith(".csv"))
    .sort()
    .map((name) => path.join(outputDir, name));

  if (files.length === 0) {
    throw new Error(`Nenhum CSV encontrado em ${outputDir}`);
  }

  return { outputDir, files };
}

async function firstVisible(locator) {
  const count = await locator.count();
  for (let index = 0; index < count; index += 1) {
    const item = locator.nth(index);
    if (await item.isVisible().catch(() => false)) {
      return item;
    }
  }
  return null;
}

async function openConversation(page, recipient) {
  const directUrl = process.env.GOOGLE_CHAT_CONVERSATION_URL;
  if (directUrl) {
    await page.goto(directUrl, { waitUntil: "domcontentloaded" });
    return;
  }

  await page.goto("https://chat.google.com", { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});

  const searchButton = await firstVisible(
    page
      .getByRole("button", { name: /search|pesquisar|buscar/i })
      .or(page.locator('[aria-label*="Search"], [aria-label*="Pesquisar"], [aria-label*="Buscar"]')),
  );
  if (searchButton) {
    await searchButton.click();
    await page.waitForTimeout(1000);
  }

  const search = await firstVisible(
    page
      .getByRole("textbox", { name: /search|pesquisar|buscar/i })
      .or(
        page.locator(
          'input[aria-label*="Search"], input[aria-label*="Pesquisar"], input[aria-label*="Buscar"], input[placeholder*="Search"], input[placeholder*="Pesquisar"], input[placeholder*="Buscar"]',
        ),
      ),
  );

  if (!search) {
    throw new Error(
      "Nao encontrei a busca do Google Chat. Configure GOOGLE_CHAT_CONVERSATION_URL com o link da conversa da Marcela.",
    );
  }

  await search.click();
  await search.fill(recipient);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(3000);

  const conversation = await firstVisible(page.getByText(recipient, { exact: false }));
  if (!conversation) {
    throw new Error(
      `Nao encontrei a conversa de ${recipient}. Abra a conversa uma vez e configure GOOGLE_CHAT_CONVERSATION_URL.`,
    );
  }
  await conversation.click();
}

async function findMessageBox(page) {
  const box = await firstVisible(
    page
      .getByRole("textbox")
      .or(page.locator('[contenteditable="true"][role="textbox"]'))
      .or(page.locator('[contenteditable="true"]')),
  );
  if (!box) {
    throw new Error("Nao encontrei o campo de mensagem do Google Chat.");
  }
  return box;
}

async function attachFile(page, filePath) {
  let fileInput = page.locator('input[type="file"]').last();
  if ((await fileInput.count()) === 0) {
    const attachButton = await firstVisible(
      page
        .getByRole("button", { name: /upload|attach|anexar|arquivo|file/i })
        .or(page.locator('[aria-label*="Upload"], [aria-label*="Attach"], [aria-label*="Anexar"]')),
    );
    if (!attachButton) {
      throw new Error("Nao encontrei o botao/input de anexar arquivo no Google Chat.");
    }
    await attachButton.click();
    fileInput = page.locator('input[type="file"]').last();
  }

  await fileInput.setInputFiles(filePath);
}

async function sendCurrentMessage(page) {
  const sendButton = await firstVisible(
    page
      .getByRole("button", { name: /^send$|enviar/i })
      .or(page.locator('[aria-label*="Send"], [aria-label*="Enviar"]')),
  );

  if (sendButton) {
    await sendButton.click();
  } else {
    await page.keyboard.press("Enter");
  }
}

async function sendFilesSeparately(page, files, reportDate) {
  for (const [index, filePath] of files.entries()) {
    const box = await findMessageBox(page);
    await box.click();
    await box.fill(
      index === 0
        ? `Relatorios Pleno ${reportDate}. Enviando os CSVs separadamente.`
        : "",
    );
    await attachFile(page, filePath);
    await page.waitForTimeout(3000);
    await sendCurrentMessage(page);
    await page.waitForTimeout(5000);
    console.log(`Enviado: ${path.basename(filePath)}`);
  }
}

async function main() {
  const args = parseArgs();
  const { outputDir, files } = resolveReportFiles(args.date);
  const userDataDir = process.env.GOOGLE_CHAT_PROFILE_DIR || chromeUserDataDir;
  const chromeProfileDirectory = resolveChromeProfileDirectory();

  const context = await chromium.launchPersistentContext(userDataDir, {
    channel: process.env.GOOGLE_CHAT_CHROME_CHANNEL || "chrome",
    headless: false,
    acceptDownloads: true,
    args: [`--profile-directory=${chromeProfileDirectory}`],
  });

  try {
    const page = context.pages()[0] || (await context.newPage());
    page.setDefaultTimeout(60000);
    await openConversation(page, args.recipient);
    await sendFilesSeparately(page, files, args.date);
    console.log(`Arquivos enviados separadamente do diretorio: ${outputDir}`);
  } finally {
    await context.close();
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});

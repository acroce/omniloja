#!/usr/bin/env node
import { createHash } from "node:crypto";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { chromium } from "playwright";
import { config } from "./config.mjs";
import { classifyMessage } from "./classifier.mjs";
import { getSettings, listPendingReplies, logEvent, markReplyError, markReplySending, markReplySent, saveIncomingMessage, setSetting, upsertContact } from "./db.mjs";

function hashId(parts) {
  return createHash("sha256").update(parts.filter(Boolean).join("|")).digest("hex");
}

function cleanText(text) {
  return String(text || "").replace(/\s+/g, " ").trim();
}

function cleanMessageText(text) {
  return cleanText(text)
    .replace(/^tail-(in|out)\s*/i, "")
    .replace(/\bic-[a-z-]+\b/g, "")
    .replace(/(\d{1,2}:\d{2})\1/g, "$1")
    .trim();
}

function safeFileName(value) {
  return String(value || "media").replace(/[^a-zA-Z0-9_.-]+/g, "_").slice(0, 120);
}

function processIsAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function acquireWatcherLock() {
  const lockFile = resolve(process.cwd(), "outputs/whatsapp-web/watcher.lock");
  await mkdir(dirname(lockFile), { recursive: true });

  if (existsSync(lockFile)) {
    const lockedPid = Number(readFileSync(lockFile, "utf8").trim());
    if (processIsAlive(lockedPid)) {
      throw new Error(`Watcher ja esta rodando no PID ${lockedPid}`);
    }
    unlinkSync(lockFile);
  }

  writeFileSync(lockFile, String(process.pid), { flag: "wx" });
  const release = () => {
    try {
      const lockedPid = Number(readFileSync(lockFile, "utf8").trim());
      if (lockedPid === process.pid) unlinkSync(lockFile);
    } catch {
      // Lock ja removido.
    }
  };

  process.once("exit", release);
  process.once("SIGINT", () => {
    release();
    process.exit(130);
  });
  process.once("SIGTERM", () => {
    release();
    process.exit(143);
  });
}

async function waitForWhatsApp(page) {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      if (!page.url().startsWith("https://web.whatsapp.com")) {
        await page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });
      }
      break;
    } catch (error) {
      logEvent("watcher.goto_retry", { attempt, message: error.message });
      if (attempt === 3) throw error;
      await page.waitForTimeout(1500);
    }
  }
  await page.waitForSelector("#pane-side, canvas, [data-testid='qrcode']", { timeout: 120000 });
}

async function currentChatName(page) {
  const candidates = [
    () => page.locator("#main header [role='button'] span[dir='auto']").first().textContent({ timeout: 1000 }),
    () => page.locator("#main header span[title]").first().getAttribute("title", { timeout: 1000 }),
    () => page.locator("#main header span[dir='auto']").first().textContent({ timeout: 1000 }),
  ];

  for (const candidate of candidates) {
    const value = cleanText(await candidate().catch(() => ""));
    if (value) return value;
  }

  return "";
}

async function saveDebugScreenshot(page, reason) {
  const file = resolve(process.cwd(), "outputs/whatsapp-web/last-debug.png");
  await mkdir(dirname(file), { recursive: true });
  await page.screenshot({ path: file, fullPage: false }).catch(() => null);
  const excerpt = cleanText(await page.locator("body").textContent({ timeout: 1000 }).catch(() => "")).slice(0, 500);
  logEvent("watcher.debug", { reason, file, excerpt });
}

async function openChatFromList(page, targetChat) {
  const target = cleanText(targetChat).toLowerCase();
  if (!target) return false;

  const directHit = page.getByText(targetChat, { exact: false }).first();
  if (await directHit.isVisible({ timeout: 1000 }).catch(() => false)) {
    await directHit.click({ timeout: 5000 });
    await page.waitForTimeout(900);
    logEvent("watcher.opened_target", { targetChat, mode: "text" });
    return true;
  }

  const rows = await page.locator("#pane-side [role='listitem'], #pane-side [role='row'], #pane-side div[tabindex]").all();
  for (const row of rows) {
    const label = cleanText(await row.textContent({ timeout: 1000 }).catch(() => ""));
    if (label.toLowerCase().includes(target)) {
      await row.click({ timeout: 5000 });
      await page.waitForTimeout(900);
      logEvent("watcher.opened_target", { targetChat, label: label.slice(0, 200) });
      return true;
    }
  }

  return false;
}

function findSystemChrome() {
  const candidates = [
    config.browserExecutablePath,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
  ].filter(Boolean);
  return candidates.find((candidate) => existsSync(candidate)) || "";
}

async function collectVisibleMessages(page, chatName) {
  const messageLocators = await page.locator("#main [data-id]").all();
  const tail = config.maxMessagesPerChat > 0
    ? messageLocators.slice(-config.maxMessagesPerChat)
    : messageLocators;
  const messages = [];

  for (const locator of tail) {
    const data = await locator.evaluate((element) => {
      const selectable = Array.from(element.querySelectorAll("span.selectable-text"))
        .map((node) => node.textContent || "")
        .join("\n");
      const prePlain = element.querySelector("[data-pre-plain-text]")?.getAttribute("data-pre-plain-text") || "";
      return {
        text: selectable || element.innerText || element.textContent || "",
        dataId: element.getAttribute("data-id") || "",
        className: element.getAttribute("class") || "",
        prePlainText: prePlain,
      };
    }).catch(() => ({ text: "", dataId: "", className: "", prePlainText: "" }));
    const raw = cleanMessageText(data.text);
    if (!raw) continue;
    const dataId = data.dataId;
    const prePlainText = data.prePlainText;
    const className = data.className;
    const direction = className.includes("message-out") || dataId?.includes("false_") ? "out" : "in";
    const sourceId = dataId || hashId([chatName, direction, raw]);
    const senderMatch = String(prePlainText || "").match(/\]\s*([^:]+):/);
    const senderName = cleanText(senderMatch?.[1] || "");
    const attachments = await captureImageAttachments(locator, sourceId);
    messages.push({ chatName, chatKey: chatName, direction, senderName, sourceId, text: raw, attachments });
  }

  return { nodes: messageLocators.length, tail: tail.length, messages };
}

async function scrollMessageHistory(page, direction) {
  return page.evaluate((scrollDirection) => {
    const root = document.querySelector("#main") || document.body;
    const nodes = Array.from(root.querySelectorAll("div"));
    const scrollables = nodes
      .filter((node) => node.scrollHeight > node.clientHeight + 80)
      .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
    const scroller = scrollables[0];
    if (!scroller) return false;
    const previous = scroller.scrollTop;
    const delta = Math.max(900, scroller.clientHeight * 0.9);
    if (scrollDirection === "down") {
      scroller.scrollTop = Math.min(scroller.scrollHeight, previous + delta);
    } else {
      scroller.scrollTop = Math.max(0, previous - delta);
    }
    scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    return scroller.scrollTop !== previous;
  }, direction).catch(() => false);
}

async function returnToLatestMessages(page) {
  for (let index = 0; index < 8; index += 1) {
    const moved = await scrollMessageHistory(page, "down");
    if (!moved) break;
    await page.waitForTimeout(180);
  }
}

async function scrapeCurrentChat(page, fallbackName) {
  const chatName = (await currentChatName(page)) || fallbackName || "Contato";
  const scrolls = Math.max(0, Number(config.historyScrolls) || 0);
  const collected = new Map();
  let totalNodesSeen = 0;
  let totalTailSeen = 0;
  let stableRounds = 0;

  for (let index = 0; index <= scrolls; index += 1) {
    const snapshot = await collectVisibleMessages(page, chatName);
    totalNodesSeen = Math.max(totalNodesSeen, snapshot.nodes);
    totalTailSeen = Math.max(totalTailSeen, snapshot.tail);

    let added = 0;
    for (const message of snapshot.messages) {
      if (collected.has(message.sourceId)) continue;
      collected.set(message.sourceId, message);
      added += 1;
    }

    logEvent("watcher.history_step", {
      chatName,
      step: index,
      nodes: snapshot.nodes,
      visibleMessages: snapshot.messages.length,
      added,
      collected: collected.size,
    });

    if (index === scrolls) break;
    if (added === 0) {
      stableRounds += 1;
    } else {
      stableRounds = 0;
    }
    if (stableRounds >= 8) break;

    const moved = await scrollMessageHistory(page, "up");
    if (!moved) {
      await page.mouse.wheel(0, -1800).catch(() => null);
    }
    await page.waitForTimeout(650);
  }

  await returnToLatestMessages(page);

  const messages = [...collected.values()];
  logEvent("watcher.history_loaded", { scrolls, nodes: totalNodesSeen, messages: messages.length });
  logEvent("watcher.scrape_nodes", { chatName, nodes: totalNodesSeen, tail: totalTailSeen, collected: messages.length });
  logEvent("watcher.scrape", { chatName, nodes: totalNodesSeen, messages: messages.length });
  return messages;
}

async function scanChats(page) {
  const { targetChat } = getSettings();
  const openChatName = await currentChatName(page);

  if (!openChatName && targetChat) {
    const opened = await openChatFromList(page, targetChat);
    if (opened) {
      await page.waitForTimeout(500);
      return scanChats(page);
    }
  }

  if (!openChatName) {
    await saveDebugScreenshot(page, "waiting_chat");
    logEvent("watcher.waiting_chat", { message: "Abra o grupo/conversa que deseja monitorar no WhatsApp Web." });
    return 0;
  }

  if (targetChat && !openChatName.toLowerCase().includes(targetChat.toLowerCase())) {
    logEvent("watcher.other_chat_open", { targetChat, currentChatName: openChatName });
    return 0;
  }

  let inserted = 0;

  const messages = await scrapeCurrentChat(page, openChatName);
  for (const message of messages) {
    if (message.direction !== "in") continue;
    upsertContact({ chatKey: message.chatKey, name: message.chatName });
    const classification = await classifyMessage(message.text);
    const wasInserted = saveIncomingMessage({
      ...message,
      ...classification,
      capturedAt: new Date().toISOString(),
    }, message.attachments || []);
    if (wasInserted) inserted += 1;
  }

  return inserted;
}

async function ensureTargetChatOpen(page, targetChat) {
  const openChatName = await currentChatName(page);
  if (targetChat && openChatName.toLowerCase().includes(targetChat.toLowerCase())) return true;
  if (!targetChat && openChatName) return true;
  if (targetChat) return openChatFromList(page, targetChat);
  return false;
}

async function sendPendingReplies(page) {
  const { targetChat } = getSettings();
  const pending = listPendingReplies(5);
  if (!pending.length) return 0;

  let sent = 0;
  for (const reply of pending) {
    try {
      markReplySending(reply.id);
      const opened = await ensureTargetChatOpen(page, reply.chat_name || targetChat);
      if (!opened) throw new Error(`Conversa nao aberta: ${reply.chat_name}`);

      const box = page.locator("footer div[contenteditable='true'][role='textbox']").last();
      await box.click({ timeout: 5000 });
      await box.fill(reply.text);
      await page.keyboard.press("Enter");
      markReplySent(reply.id);
      logEvent("watcher.reply_sent", { replyId: reply.id, messageId: reply.message_id });
      sent += 1;
      await page.waitForTimeout(600);
    } catch (error) {
      markReplyError(reply.id, error.message);
      logEvent("watcher.reply_error", { replyId: reply.id, message: error.message });
    }
  }
  return sent;
}

async function captureImageAttachments(locator, sourceId) {
  const imageCount = await locator.locator("img").count().catch(() => 0);
  if (!imageCount) return [];

  const mediaDir = resolve(process.cwd(), "outputs/whatsapp-web/media");
  await mkdir(mediaDir, { recursive: true });

  const attachments = [];
  for (let index = 0; index < Math.min(imageCount, 4); index += 1) {
    const img = locator.locator("img").nth(index);
    const box = await img.boundingBox().catch(() => null);
    if (!box || box.width < 80 || box.height < 80) continue;

    const filePath = resolve(mediaDir, `${safeFileName(sourceId)}-${index + 1}.png`);
    await img.screenshot({ path: filePath }).catch(() => null);
    if (!existsSync(filePath)) continue;
    attachments.push({
      messageSourceId: sourceId,
      type: "image",
      filePath,
      mimeType: "image/png",
    });
  }
  return attachments;
}

async function main() {
  await acquireWatcherLock();
  logEvent("watcher.starting", {
    headless: config.headless,
    userDataDir: config.userDataDir,
    scanIntervalMs: config.scanIntervalMs,
  });
  setSetting("watcherPid", process.pid);
  setSetting("watcherHeartbeat", new Date().toISOString());

  const executablePath = findSystemChrome();
  const context = await chromium.launchPersistentContext(config.userDataDir, {
    headless: config.headless,
    viewport: { width: 1366, height: 900 },
    ...(executablePath ? { executablePath } : {}),
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });
  const page = context.pages()[0] || await context.newPage();

  await waitForWhatsApp(page);
  logEvent("watcher.ready", { url: page.url() });

  while (true) {
    try {
      setSetting("watcherHeartbeat", new Date().toISOString());
      const inserted = await scanChats(page);
      const repliesSent = await sendPendingReplies(page);
      logEvent("watcher.scan", { inserted, repliesSent, targetChat: getSettings().targetChat });
    } catch (error) {
      logEvent("watcher.error", { message: error.message, stack: error.stack });
    }
    await page.waitForTimeout(config.scanIntervalMs);
  }
}

main().catch((error) => {
  setSetting("watcherHeartbeat", "");
  logEvent("watcher.fatal", { message: error.message, stack: error.stack });
  console.error(error);
  process.exit(1);
});

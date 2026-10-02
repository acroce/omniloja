import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

const envFile = resolve(process.cwd(), ".env");

if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...valueParts] = trimmed.split("=");
    if (process.env[key]) continue;
    process.env[key] = valueParts.join("=").trim().replace(/^["']|["']$/g, "");
  }
}

function env(name, fallback = "") {
  return (process.env[name] ?? fallback).trim();
}

function boolEnv(name, fallback = false) {
  const value = env(name);
  if (!value) return fallback;
  return ["1", "true", "yes", "sim", "on"].includes(value.toLowerCase());
}

function intEnv(name, fallback) {
  const parsed = Number.parseInt(env(name), 10);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export const config = {
  host: env("WHATSAPP_WEB_HOST", "127.0.0.1"),
  port: intEnv("WHATSAPP_WEB_PORT", 3009),
  https: boolEnv("WHATSAPP_WEB_HTTPS", false),
  httpsKeyFile: env("WHATSAPP_WEB_HTTPS_KEY_FILE", "config/whatsapp-web-cert/key.pem"),
  httpsCertFile: env("WHATSAPP_WEB_HTTPS_CERT_FILE", "config/whatsapp-web-cert/cert.pem"),
  dbFile: env("WHATSAPP_WEB_DB_FILE", "outputs/whatsapp-web/messages.db"),
  userDataDir: env("WHATSAPP_WEB_USER_DATA_DIR", "outputs/whatsapp-web/chrome-profile"),
  headless: boolEnv("WHATSAPP_WEB_HEADLESS", false),
  autoStartWatcher: boolEnv("WHATSAPP_WEB_AUTO_START_WATCHER", false),
  scanIntervalMs: intEnv("WHATSAPP_WEB_SCAN_INTERVAL_MS", 15000),
  maxChatsPerScan: intEnv("WHATSAPP_WEB_MAX_CHATS_PER_SCAN", 25),
  maxMessagesPerChat: intEnv("WHATSAPP_WEB_MAX_MESSAGES_PER_CHAT", 0),
  historyScrolls: intEnv("WHATSAPP_WEB_HISTORY_SCROLLS", 120),
  browserExecutablePath: env("WHATSAPP_WEB_BROWSER_EXECUTABLE_PATH"),
  openaiApiKey: env("OPENAI_API_KEY"),
  openaiModel: env("OPENAI_MODEL", "gpt-5-mini"),
};

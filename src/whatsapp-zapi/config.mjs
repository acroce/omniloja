import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const envFile = resolve(process.cwd(), ".env");

if (existsSync(envFile)) {
  const contents = readFileSync(envFile, "utf8");
  for (const line of contents.split(/\r?\n/)) {
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
  const value = Number.parseInt(env(name), 10);
  return Number.isFinite(value) ? value : fallback;
}

export const config = {
  port: intEnv("WHATSAPP_ZAPI_PORT", 3097),
  publicBaseUrl: env("WHATSAPP_ZAPI_PUBLIC_BASE_URL"),
  webhookSecret: env("WHATSAPP_ZAPI_WEBHOOK_SECRET"),
  autoReply: boolEnv("WHATSAPP_AUTO_REPLY", false),
  dryRun: boolEnv("WHATSAPP_DRY_RUN", true),
  allowGroups: boolEnv("WHATSAPP_ALLOW_GROUPS", false),
  businessName: env("WHATSAPP_BUSINESS_NAME", "Equipe"),
  systemPrompt: env(
    "WHATSAPP_SYSTEM_PROMPT",
    "Voce atende clientes pelo WhatsApp em portugues do Brasil. Seja claro, educado e breve. Se faltar informacao, faca uma pergunta objetiva. Se o assunto exigir humano, diga que vai encaminhar para a equipe."
  ),
  openaiApiKey: env("OPENAI_API_KEY"),
  openaiModel: env("OPENAI_MODEL", "gpt-5-mini"),
  zapi: {
    instanceId: env("ZAPI_INSTANCE_ID"),
    token: env("ZAPI_TOKEN"),
    clientToken: env("ZAPI_CLIENT_TOKEN"),
    baseUrl: env("ZAPI_BASE_URL", "https://api.z-api.io"),
  },
  logFile: env("WHATSAPP_ZAPI_LOG_FILE", "outputs/whatsapp-zapi-events.jsonl"),
};

export function requireZapiConfig() {
  const missing = [];
  if (!config.zapi.instanceId) missing.push("ZAPI_INSTANCE_ID");
  if (!config.zapi.token) missing.push("ZAPI_TOKEN");
  if (!config.zapi.clientToken) missing.push("ZAPI_CLIENT_TOKEN");
  if (missing.length) {
    throw new Error(`Configure no .env: ${missing.join(", ")}`);
  }
}

import { config, requireZapiConfig } from "./config.mjs";

function zapiUrl(path) {
  const { baseUrl, instanceId, token } = config.zapi;
  return `${baseUrl}/instances/${instanceId}/token/${token}${path}`;
}

async function zapiFetch(path, body, method = "POST") {
  requireZapiConfig();
  const response = await fetch(zapiUrl(path), {
    method,
    headers: {
      "Client-Token": config.zapi.clientToken,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = { raw: text };
  }

  if (!response.ok) {
    throw new Error(`Z-API HTTP ${response.status}: ${JSON.stringify(payload)}`);
  }

  return payload;
}

export async function sendText(phone, message, options = {}) {
  return zapiFetch("/send-text", {
    phone,
    message,
    ...options,
  });
}

export async function updateReceiveWebhook(url) {
  return zapiFetch("/update-webhook-received", { value: url }, "PUT");
}

export async function updateNotifySentByMe(enabled) {
  return zapiFetch("/update-notify-sent-by-me", { notifySentByMe: enabled }, "PUT");
}

import http from "node:http";
import { URL } from "node:url";
import { config } from "./config.mjs";
import { buildReply, extractTextMessage } from "./auto-reply.mjs";
import { logEvent } from "./logger.mjs";
import { sendText } from "./zapi-client.mjs";

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 2_000_000) {
        req.destroy();
        reject(new Error("Payload muito grande"));
      }
    });
    req.on("end", () => {
      if (!body) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function isAuthorized(reqUrl, req) {
  if (!config.webhookSecret) return true;
  const querySecret = reqUrl.searchParams.get("secret");
  const headerSecret = req.headers["x-webhook-secret"];
  return querySecret === config.webhookSecret || headerSecret === config.webhookSecret;
}

function shouldIgnore(event) {
  if (event.type !== "ReceivedCallback") return "not_received_callback";
  if (event.fromMe) return "from_me";
  if (event.broadcast) return "broadcast";
  if (event.isNewsletter) return "newsletter";
  if (event.isGroup && !config.allowGroups) return "group_disabled";
  if (event.notification) return "notification";
  if (event.waitingMessage) return "waiting_message";
  return "";
}

async function handleReceive(req, res, reqUrl) {
  if (!isAuthorized(reqUrl, req)) {
    sendJson(res, 401, { ok: false, error: "unauthorized" });
    return;
  }

  const event = await readJson(req);
  await logEvent("zapi.receive", event);

  const ignoreReason = shouldIgnore(event);
  if (ignoreReason) {
    await logEvent("zapi.ignored", { reason: ignoreReason, messageId: event.messageId });
    sendJson(res, 200, { ok: true, ignored: ignoreReason });
    return;
  }

  const text = extractTextMessage(event);
  const reply = await buildReply({
    text,
    contactName: event.chatName || event.senderName,
    phone: event.phone,
  });

  const result = {
    phone: event.phone,
    messageId: event.messageId,
    incomingText: text,
    reply,
    dryRun: config.dryRun,
    autoReply: config.autoReply,
  };

  if (config.autoReply && !config.dryRun) {
    result.zapi = await sendText(event.phone, reply, { delayTyping: 2 });
  }

  await logEvent("zapi.reply", result);
  sendJson(res, 200, { ok: true, ...result });
}

const server = http.createServer(async (req, res) => {
  const reqUrl = new URL(req.url, `http://${req.headers.host || "localhost"}`);

  try {
    if (req.method === "GET" && reqUrl.pathname === "/health") {
      sendJson(res, 200, {
        ok: true,
        service: "whatsapp-zapi",
        autoReply: config.autoReply,
        dryRun: config.dryRun,
      });
      return;
    }

    if (req.method === "POST" && reqUrl.pathname === "/webhooks/zapi/receive") {
      await handleReceive(req, res, reqUrl);
      return;
    }

    sendJson(res, 404, { ok: false, error: "not_found" });
  } catch (error) {
    await logEvent("server.error", { message: error.message, stack: error.stack });
    sendJson(res, 500, { ok: false, error: error.message });
  }
});

server.listen(config.port, () => {
  console.log(`WhatsApp Z-API server ouvindo em http://127.0.0.1:${config.port}`);
  console.log(`Webhook local: http://127.0.0.1:${config.port}/webhooks/zapi/receive`);
});

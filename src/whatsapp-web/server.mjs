#!/usr/bin/env node
import http from "node:http";
import https from "node:https";
import { createReadStream, readFileSync } from "node:fs";
import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { config } from "./config.mjs";
import { deleteCategory, deleteMarker, enqueueReply, getReportSummary, getSettings, getStats, latestEvents, listCategories, listMarkers, listMessages, listMessagesForReport, listRelatedMessages, logEvent, reclassifyMessagesByCategoryRules, saveCategory, saveMarker, setSetting, updateMessageCategory, updateMessageClassification, updateMessageMarker, updateMessageObservation, updateMessageStatus } from "./db.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const PUBLIC_DIR = path.join(ROOT, "public", "whatsapp-web");
let watcher = null;

function sendJson(res, statusCode, payload) {
  res.writeHead(statusCode, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload));
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let body = "";
    req.on("data", (chunk) => (body += chunk));
    req.on("end", () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function watcherStatus() {
  const settings = getSettings();
  const heartbeatMs = settings.watcherHeartbeat ? Date.parse(settings.watcherHeartbeat) : 0;
  const externalRunning = heartbeatMs && Date.now() - heartbeatMs < config.scanIntervalMs * 2.5;
  const localRunning = Boolean(watcher && !watcher.killed && watcher.exitCode === null);
  return {
    running: localRunning || Boolean(externalRunning),
    pid: localRunning ? watcher.pid : settings.watcherPid || null,
    heartbeat: settings.watcherHeartbeat || null,
  };
}

function startWatcher() {
  if (watcherStatus().running) return watcherStatus();
  watcher = spawn(process.execPath, [path.join(ROOT, "src", "whatsapp-web", "watcher.mjs")], {
    cwd: ROOT,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  watcher.stdout.on("data", (chunk) => logEvent("watcher.stdout", { text: String(chunk) }));
  watcher.stderr.on("data", (chunk) => logEvent("watcher.stderr", { text: String(chunk) }));
  watcher.on("exit", (code, signal) => logEvent("watcher.exit", { code, signal }));
  logEvent("watcher.spawned", { pid: watcher.pid });
  return watcherStatus();
}

function stopWatcher() {
  const status = watcherStatus();
  if (watcher && status.running) watcher.kill("SIGTERM");
  if (!watcher && status.running) {
    logEvent("watcher.external_stop_requested", { message: "Watcher externo deve ser parado pelo terminal que o iniciou." });
  }
  return watcherStatus();
}

function serveStatic(req, res, pathname) {
  const file = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
  const target = path.resolve(PUBLIC_DIR, file);
  if (!target.startsWith(PUBLIC_DIR)) return false;
  if (!existsSync(target)) return false;
  const ext = path.extname(target);
  const contentType = ext === ".css" ? "text/css" : ext === ".js" ? "text/javascript" : "text/html";
  res.writeHead(200, {
    "Content-Type": `${contentType}; charset=utf-8`,
    "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
  });
  createReadStream(target).on("error", () => sendJson(res, 404, { ok: false })).pipe(res);
  return true;
}

function serveMedia(res, filePath) {
  const mediaRoot = path.resolve(ROOT, "outputs", "whatsapp-web", "media");
  const target = path.resolve(filePath || "");
  if (!target.startsWith(mediaRoot) || !existsSync(target)) {
    sendJson(res, 404, { ok: false, error: "media_not_found" });
    return;
  }
  res.writeHead(200, { "Content-Type": "image/png" });
  createReadStream(target).pipe(res);
}

function csvEscape(value) {
  const text = String(value ?? "");
  return `"${text.replace(/"/g, '""')}"`;
}

function sendCsv(res, rows) {
  const headers = [
    "id",
    "captured_at",
    "chat_name",
    "sender_name",
    "store_number",
    "text",
    "category",
    "priority",
    "sentiment",
    "observation",
    "status",
    "attachments_count",
    "replies_count",
  ];
  const lines = [
    headers.join(","),
    ...rows.map((row) => headers.map((header) => csvEscape(row[header])).join(",")),
  ];
  res.writeHead(200, {
    "Content-Type": "text/csv; charset=utf-8",
    "Content-Disposition": "attachment; filename=\"whatsapp-mensagens.csv\"",
  });
  res.end(lines.join("\n"));
}

const requestHandler = async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  try {
    if (req.method === "GET" && url.pathname === "/api/messages") {
      sendJson(res, 200, {
        ok: true,
        messages: listMessages({
          status: url.searchParams.get("status") || "",
          category: url.searchParams.get("category") || "",
          q: url.searchParams.get("q") || "",
          sender: url.searchParams.get("sender") || "",
          store: url.searchParams.get("store") || "",
          limit: url.searchParams.get("limit") || 200,
        }),
      });
      return;
    }
    if (req.method === "GET" && url.pathname.match(/^\/api\/messages\/\d+\/related$/)) {
      const id = Number(url.pathname.split("/")[3]);
      sendJson(res, 200, { ok: true, messages: listRelatedMessages(id, Number(url.searchParams.get("limit")) || 20) });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/stats") {
      sendJson(res, 200, { ok: true, stats: getStats(), watcher: watcherStatus(), settings: getSettings() });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/settings") {
      sendJson(res, 200, { ok: true, settings: getSettings() });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/settings") {
      const body = await readJson(req);
      setSetting("targetChat", body.targetChat || "");
      logEvent("settings.updated", getSettings());
      sendJson(res, 200, { ok: true, settings: getSettings() });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/events") {
      sendJson(res, 200, { ok: true, events: latestEvents() });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/reports/summary") {
      sendJson(res, 200, { ok: true, report: getReportSummary() });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/reports/messages.csv") {
      sendCsv(res, listMessagesForReport());
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/categories") {
      sendJson(res, 200, { ok: true, categories: listCategories() });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/markers") {
      sendJson(res, 200, { ok: true, markers: listMarkers() });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/markers") {
      const body = await readJson(req);
      sendJson(res, 200, { ok: true, markers: saveMarker(body) });
      return;
    }
    if (req.method === "DELETE" && url.pathname.match(/^\/api\/markers\/\d+$/)) {
      const id = Number(url.pathname.split("/")[3]);
      sendJson(res, 200, { ok: true, markers: deleteMarker(id) });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/categories") {
      const body = await readJson(req);
      sendJson(res, 200, { ok: true, categories: saveCategory(body) });
      return;
    }
    if (req.method === "DELETE" && url.pathname.match(/^\/api\/categories\/\d+$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      if (body.password !== "989898") {
        sendJson(res, 403, { ok: false, error: "Senha invalida" });
        return;
      }
      sendJson(res, 200, { ok: true, categories: deleteCategory(id) });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/messages/reclassify") {
      const changed = reclassifyMessagesByCategoryRules();
      sendJson(res, 200, { ok: true, changed });
      return;
    }
    if (req.method === "GET" && url.pathname === "/api/media") {
      serveMedia(res, url.searchParams.get("path"));
      return;
    }
    if (req.method === "POST" && url.pathname.match(/^\/api\/messages\/\d+\/status$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      updateMessageStatus(id, body.status);
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname.match(/^\/api\/messages\/\d+\/category$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      updateMessageCategory(id, body.category || "outro");
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname.match(/^\/api\/messages\/\d+\/classification$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      updateMessageClassification(id, body.classification || "Checking");
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname.match(/^\/api\/messages\/\d+\/marker$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      updateMessageMarker(id, body.markerId || null);
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname.match(/^\/api\/messages\/\d+\/observation$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      updateMessageObservation(id, body.observation || "");
      sendJson(res, 200, { ok: true });
      return;
    }
    if (req.method === "POST" && url.pathname.match(/^\/api\/messages\/\d+\/reply$/)) {
      const id = Number(url.pathname.split("/")[3]);
      const body = await readJson(req);
      const reply = enqueueReply(id, body.text || "");
      logEvent("reply.queued", { replyId: reply.id, messageId: id });
      sendJson(res, 200, { ok: true, reply });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/watcher/start") {
      sendJson(res, 200, { ok: true, watcher: startWatcher() });
      return;
    }
    if (req.method === "POST" && url.pathname === "/api/watcher/stop") {
      sendJson(res, 200, { ok: true, watcher: stopWatcher() });
      return;
    }
    if (req.method === "GET" && serveStatic(req, res, url.pathname)) return;
    sendJson(res, 404, { ok: false, error: "not_found" });
  } catch (error) {
    logEvent("server.error", { message: error.message, stack: error.stack });
    sendJson(res, 500, { ok: false, error: error.message });
  }
};

function createAppServer() {
  if (!config.https) return http.createServer(requestHandler);
  const keyPath = path.resolve(ROOT, config.httpsKeyFile);
  const certPath = path.resolve(ROOT, config.httpsCertFile);
  if (!existsSync(keyPath) || !existsSync(certPath)) {
    throw new Error(`Certificado HTTPS nao encontrado: ${keyPath} / ${certPath}`);
  }
  return https.createServer({
    key: readFileSync(keyPath),
    cert: readFileSync(certPath),
  }, requestHandler);
}

const server = createAppServer();

server.listen(config.port, config.host, () => {
  const protocol = config.https ? "https" : "http";
  console.log(`WhatsApp Web painel em ${protocol}://${config.host}:${config.port}`);
  if (config.autoStartWatcher) startWatcher();
});

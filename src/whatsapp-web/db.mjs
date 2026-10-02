import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { config } from "./config.mjs";

const dbPath = resolve(process.cwd(), config.dbFile);
mkdirSync(dirname(dbPath), { recursive: true });

export const db = new DatabaseSync(dbPath);
db.exec("PRAGMA journal_mode = WAL");
db.exec("PRAGMA synchronous = NORMAL");
db.exec("PRAGMA wal_autocheckpoint = 50");
db.exec("PRAGMA journal_size_limit = 10485760");
db.exec("PRAGMA busy_timeout = 5000");

db.exec(`
  CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL UNIQUE,
    chat_key TEXT NOT NULL,
    chat_name TEXT NOT NULL,
    direction TEXT NOT NULL,
    sender_name TEXT NOT NULL DEFAULT '',
    store_number TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'outro',
    priority TEXT NOT NULL DEFAULT 'normal',
    sentiment TEXT NOT NULL DEFAULT 'neutro',
    marker_id INTEGER,
    observation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'novo',
    confidence REAL NOT NULL DEFAULT 0,
    captured_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (chat_key) REFERENCES contacts(chat_key)
  );

  CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_source_id TEXT NOT NULL,
    type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'image/png',
    created_at TEXT NOT NULL,
    UNIQUE(message_source_id, file_path),
    FOREIGN KEY (message_source_id) REFERENCES messages(source_id)
  );

  CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    priority TEXT NOT NULL DEFAULT 'normal',
    sentiment TEXT NOT NULL DEFAULT 'neutro',
    keywords TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS deleted_categories (
    name TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS replies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    message_source_id TEXT NOT NULL,
    chat_key TEXT NOT NULL,
    chat_name TEXT NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    sent_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id)
  );

  CREATE TABLE IF NOT EXISTS markers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    color TEXT NOT NULL DEFAULT '#2764b8',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status, captured_at DESC);
  CREATE INDEX IF NOT EXISTS idx_messages_category ON messages(category, captured_at DESC);
  CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_key, captured_at DESC);
  CREATE INDEX IF NOT EXISTS idx_attachments_message ON attachments(message_source_id);
  CREATE INDEX IF NOT EXISTS idx_categories_active ON categories(active, name);
  CREATE INDEX IF NOT EXISTS idx_replies_status ON replies(status, created_at);
  CREATE INDEX IF NOT EXISTS idx_replies_message ON replies(message_id);
  CREATE INDEX IF NOT EXISTS idx_markers_active ON markers(active, name);
`);

try {
  db.exec("ALTER TABLE messages ADD COLUMN sender_name TEXT NOT NULL DEFAULT ''");
} catch (error) {
  if (!String(error.message).includes("duplicate column")) throw error;
}

try {
  db.exec("ALTER TABLE messages ADD COLUMN store_number TEXT NOT NULL DEFAULT ''");
} catch (error) {
  if (!String(error.message).includes("duplicate column")) throw error;
}

try {
  db.exec("ALTER TABLE messages ADD COLUMN marker_id INTEGER");
} catch (error) {
  if (!String(error.message).includes("duplicate column")) throw error;
}

try {
  db.exec("ALTER TABLE messages ADD COLUMN observation TEXT NOT NULL DEFAULT ''");
} catch (error) {
  if (!String(error.message).includes("duplicate column")) throw error;
}

db.exec("CREATE INDEX IF NOT EXISTS idx_messages_marker ON messages(marker_id, captured_at DESC)");
db.exec("CREATE INDEX IF NOT EXISTS idx_messages_store ON messages(store_number, captured_at DESC)");

db.exec(`
  UPDATE messages
  SET sentiment = 'Checking'
  WHERE sentiment IN ('positivo', 'neutro', 'negativo');

  UPDATE categories
  SET sentiment = 'Checking'
  WHERE sentiment IN ('positivo', 'neutro', 'negativo');
`);

export function nowIso() {
  return new Date().toISOString();
}

export function extractStoreNumber(text) {
  const match = String(text || "").match(/\b(?:loja|lj)\s*[:#.-]?\s*(\d{1,5})\b/i);
  return match?.[1] || "";
}

export function upsertContact({ chatKey, name }) {
  const now = nowIso();
  db.prepare(`
    INSERT INTO contacts (chat_key, name, last_seen_at, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(chat_key) DO UPDATE SET
      name = excluded.name,
      last_seen_at = excluded.last_seen_at,
      updated_at = excluded.updated_at
  `).run(chatKey, name || chatKey, now, now);
}

export function insertMessage(message) {
  const now = nowIso();
  const storeNumber = message.storeNumber || extractStoreNumber(message.text);
  const result = db.prepare(`
    INSERT OR IGNORE INTO messages (
      source_id, chat_key, chat_name, direction, sender_name, store_number, text, category, priority,
      sentiment, status, confidence, captured_at, created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
  `).run(
    message.sourceId,
    message.chatKey,
    message.chatName,
    message.direction,
    message.senderName || "",
    storeNumber,
    message.text,
    message.category,
    message.priority,
    message.sentiment,
    message.status || "novo",
    message.confidence || 0,
    message.capturedAt || now,
    now,
    now
  );
  return result.changes > 0;
}

export function insertAttachment(attachment) {
  const now = nowIso();
  const result = db.prepare(`
    INSERT OR IGNORE INTO attachments (message_source_id, type, file_path, mime_type, created_at)
    VALUES (?, ?, ?, ?, ?)
  `).run(
    attachment.messageSourceId,
    attachment.type || "image",
    attachment.filePath,
    attachment.mimeType || "image/png",
    now
  );
  return result.changes > 0;
}

function checkpointWal() {
  try {
    db.prepare("PRAGMA wal_checkpoint(PASSIVE)").get();
  } catch {
    // Outro processo pode estar lendo; o proximo checkpoint resolve.
  }
}

export function saveIncomingMessage(message, attachments = []) {
  db.exec("BEGIN IMMEDIATE");
  try {
    const wasInserted = insertMessage(message);
    for (const attachment of attachments) {
      insertAttachment(attachment);
    }
    db.exec("COMMIT");
    checkpointWal();
    return wasInserted;
  } catch (error) {
    db.exec("ROLLBACK");
    throw error;
  }
}

export function listAttachmentsForSources(sourceIds) {
  if (!sourceIds.length) return new Map();
  const placeholders = sourceIds.map(() => "?").join(",");
  const rows = db.prepare(`
    SELECT * FROM attachments
    WHERE message_source_id IN (${placeholders})
    ORDER BY id
  `).all(...sourceIds);
  const map = new Map(sourceIds.map((id) => [id, []]));
  for (const row of rows) {
    map.get(row.message_source_id)?.push(row);
  }
  return map;
}

export function listRepliesForMessageIds(messageIds) {
  if (!messageIds.length) return new Map();
  const placeholders = messageIds.map(() => "?").join(",");
  const rows = db.prepare(`
    SELECT * FROM replies
    WHERE message_id IN (${placeholders})
    ORDER BY id
  `).all(...messageIds);
  const map = new Map(messageIds.map((id) => [id, []]));
  for (const row of rows) {
    map.get(row.message_id)?.push(row);
  }
  return map;
}

export function listMessages({ status = "", category = "", q = "", sender = "", store = "", excludeId = "", limit = 200 } = {}) {
  const clauses = [];
  const params = [];
  if (status) {
    clauses.push("m.status = ?");
    params.push(status);
  }
  if (category) {
    clauses.push("m.category = ?");
    params.push(category);
  }
  if (q) {
    clauses.push("(m.chat_name LIKE ? OR m.sender_name LIKE ? OR m.text LIKE ? OR m.store_number LIKE ?)");
    params.push(`%${q}%`, `%${q}%`, `%${q}%`, `%${q}%`);
  }
  if (sender) {
    clauses.push("m.sender_name = ?");
    params.push(sender);
  }
  if (store) {
    clauses.push("m.store_number = ?");
    params.push(store);
  }
  if (excludeId) {
    clauses.push("m.id <> ?");
    params.push(Number(excludeId));
  }
  params.push(Math.min(Number(limit) || 200, 1000));
  const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
  const messages = db.prepare(`
    SELECT
      m.*,
      mk.id marker_id,
      mk.name marker_name,
      mk.color marker_color
    FROM messages m
    LEFT JOIN markers mk ON mk.id = m.marker_id AND mk.active = 1
    ${where}
    ORDER BY m.captured_at DESC, m.id DESC
    LIMIT ?
  `).all(...params);
  const attachmentsBySource = listAttachmentsForSources(messages.map((message) => message.source_id));
  const repliesByMessage = listRepliesForMessageIds(messages.map((message) => message.id));
  return messages.map((message) => ({
    ...message,
    attachments: attachmentsBySource.get(message.source_id) || [],
    replies: repliesByMessage.get(message.id) || [],
  }));
}

export function listRelatedMessages(messageId, limit = 20) {
  const message = db.prepare("SELECT * FROM messages WHERE id = ?").get(messageId);
  if (!message) return [];
  const rows = listMessages({
    sender: message.sender_name || "",
    store: message.store_number || "",
    excludeId: message.id,
    limit,
  });
  if (rows.length) return rows;
  return listMessages({ sender: message.sender_name || "", excludeId: message.id, limit });
}

export function enqueueReply(messageId, text) {
  const message = db.prepare("SELECT * FROM messages WHERE id = ?").get(messageId);
  if (!message) throw new Error("Mensagem nao encontrada");
  const body = String(text || "").trim();
  if (!body) throw new Error("Texto da resposta e obrigatorio");
  const now = nowIso();
  const result = db.prepare(`
    INSERT INTO replies (
      message_id, message_source_id, chat_key, chat_name, text, status,
      created_at, updated_at
    )
    VALUES (?, ?, ?, ?, ?, 'pendente', ?, ?)
  `).run(message.id, message.source_id, message.chat_key, message.chat_name, body, now, now);
  return db.prepare("SELECT * FROM replies WHERE id = ?").get(result.lastInsertRowid);
}

export function listPendingReplies(limit = 10) {
  return db.prepare(`
    SELECT * FROM replies
    WHERE status = 'pendente'
    ORDER BY created_at ASC, id ASC
    LIMIT ?
  `).all(limit);
}

export function markReplySending(id) {
  db.prepare("UPDATE replies SET status = 'enviando', updated_at = ? WHERE id = ? AND status = 'pendente'").run(nowIso(), id);
}

export function markReplySent(id) {
  const now = nowIso();
  const reply = db.prepare("SELECT * FROM replies WHERE id = ?").get(id);
  db.prepare("UPDATE replies SET status = 'enviado', sent_at = ?, updated_at = ? WHERE id = ?").run(now, now, id);
  if (reply?.message_id) updateMessageStatus(reply.message_id, "respondido");
}

export function markReplyError(id, error) {
  db.prepare("UPDATE replies SET status = 'erro', error = ?, updated_at = ? WHERE id = ?").run(String(error || ""), nowIso(), id);
}

export function updateMessageStatus(id, status) {
  const allowed = new Set(["novo", "em_atendimento", "respondido", "ignorado", "concluido"]);
  if (!allowed.has(status)) throw new Error("Status invalido");
  return db.prepare("UPDATE messages SET status = ?, updated_at = ? WHERE id = ?").run(status, nowIso(), id);
}

export function updateMessageCategory(id, categoryName) {
  const category = db.prepare("SELECT * FROM categories WHERE name = ? AND active = 1").get(String(categoryName || "").trim());
  const next = category || { name: "outro", priority: "normal", sentiment: "Checking" };
  return db.prepare(`
    UPDATE messages
    SET category = ?, priority = ?, sentiment = ?, confidence = 1, updated_at = ?
    WHERE id = ?
  `).run(next.name, next.priority, next.sentiment, nowIso(), id);
}

export function updateMessageClassification(id, classification) {
  const next = classificationOptions.includes(classification) ? classification : "Checking";
  return db.prepare(`
    UPDATE messages
    SET sentiment = ?, confidence = 1, updated_at = ?
    WHERE id = ?
  `).run(next, nowIso(), id);
}

export function updateMessageMarker(id, markerId) {
  const nextId = Number(markerId) || null;
  if (nextId) {
    const marker = db.prepare("SELECT id FROM markers WHERE id = ? AND active = 1").get(nextId);
    if (!marker) throw new Error("Marcador invalido");
  }
  return db.prepare("UPDATE messages SET marker_id = ?, updated_at = ? WHERE id = ?").run(nextId, nowIso(), id);
}

export function updateMessageObservation(id, observation) {
  const text = String(observation || "").trim();
  return db.prepare("UPDATE messages SET observation = ?, updated_at = ? WHERE id = ?").run(text, nowIso(), id);
}

export function getStats() {
  const byStatus = db.prepare("SELECT status, COUNT(*) total FROM messages GROUP BY status").all();
  const byCategory = db.prepare("SELECT category, COUNT(*) total FROM messages GROUP BY category ORDER BY total DESC").all();
  const since = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
  const recent = db.prepare("SELECT COUNT(*) total FROM messages WHERE captured_at >= ?").get(since);
  const highPriority = db.prepare("SELECT COUNT(*) total FROM messages WHERE priority = 'alta'").get();
  return { byStatus, byCategory, recent24h: recent?.total || 0, highPriority: highPriority?.total || 0 };
}

export function getReportSummary() {
  return {
    byStatus: db.prepare("SELECT status, COUNT(*) total FROM messages GROUP BY status ORDER BY total DESC").all(),
    byCategory: db.prepare("SELECT category, COUNT(*) total FROM messages GROUP BY category ORDER BY total DESC").all(),
    byStore: db.prepare(`
      SELECT COALESCE(NULLIF(store_number, ''), 'sem loja') store_number, COUNT(*) total
      FROM messages
      GROUP BY COALESCE(NULLIF(store_number, ''), 'sem loja')
      ORDER BY total DESC
      LIMIT 30
    `).all(),
    bySender: db.prepare(`
      SELECT COALESCE(NULLIF(sender_name, ''), 'sem remetente') sender, COUNT(*) total
      FROM messages
      GROUP BY COALESCE(NULLIF(sender_name, ''), 'sem remetente')
      ORDER BY total DESC
      LIMIT 20
    `).all(),
    replies: db.prepare("SELECT status, COUNT(*) total FROM replies GROUP BY status ORDER BY total DESC").all(),
    attachments: db.prepare("SELECT COUNT(*) total FROM attachments").get()?.total || 0,
  };
}

export function listMessagesForReport() {
  return db.prepare(`
    SELECT
      m.id,
      m.captured_at,
      m.chat_name,
      m.sender_name,
      m.store_number,
      m.text,
      m.category,
      m.priority,
      m.sentiment,
      m.observation,
      m.status,
      COUNT(a.id) attachments_count,
      COUNT(r.id) replies_count
    FROM messages m
    LEFT JOIN attachments a ON a.message_source_id = m.source_id
    LEFT JOIN replies r ON r.message_id = m.id
    GROUP BY m.id
    ORDER BY m.captured_at DESC, m.id DESC
  `).all();
}

export function logEvent(type, payload) {
  db.prepare("INSERT INTO events (type, payload, created_at) VALUES (?, ?, ?)").run(
    type,
    JSON.stringify(payload || {}),
    nowIso()
  );
}

export function latestEvents(limit = 80) {
  return db.prepare("SELECT * FROM events ORDER BY id DESC LIMIT ?").all(limit);
}

export const classificationOptions = [
  "Checking",
  "Causa 1",
  "Causa 2",
  "Causa 3",
  "Causa 4",
  "Causa 5",
  "Causa 6",
  "Causa 7",
  "Causa 19",
  "Causa 20",
  "Causa 21",
  "Transferencia entre lojas",
  "Retificação",
];

const defaultCategories = [
  { name: "urgente", priority: "alta", sentiment: "Checking", keywords: "urgente,agora,imediato,parado,sem sistema,nao funciona,não funciona" },
  { name: "reclamacao", priority: "alta", sentiment: "Checking", keywords: "reclamacao,reclamação,absurdo,insatisfeito,problema,erro,atraso" },
  { name: "financeiro", priority: "normal", sentiment: "Checking", keywords: "boleto,pagamento,nota,nf,fatura,cobranca,cobrança,pix" },
  { name: "pedido", priority: "normal", sentiment: "Checking", keywords: "pedido,compra,entrega,produto,mercadoria,estoque" },
  { name: "suporte", priority: "normal", sentiment: "Checking", keywords: "ajuda,duvida,dúvida,como faço,acesso,senha,sistema" },
  { name: "agendamento", priority: "normal", sentiment: "Checking", keywords: "horario,horário,agenda,marcar,reuniao,reunião,amanha,amanhã" },
];

export function seedDefaultCategories() {
  const now = nowIso();
  const deleted = new Set(db.prepare("SELECT name FROM deleted_categories").all().map((row) => row.name));
  for (const category of defaultCategories) {
    if (deleted.has(category.name)) continue;
    db.prepare(`
      INSERT OR IGNORE INTO categories (name, priority, sentiment, keywords, active, created_at, updated_at)
      VALUES (?, ?, ?, ?, 1, ?, ?)
    `).run(category.name, category.priority, category.sentiment, category.keywords, now, now);
  }
}

seedDefaultCategories();

export function listCategories({ activeOnly = false } = {}) {
  const where = activeOnly ? "WHERE active = 1" : "";
  return db.prepare(`
    SELECT * FROM categories
    ${where}
    ORDER BY active DESC, name
  `).all();
}

export function saveCategory(category) {
  const now = nowIso();
  const name = String(category.name || "").trim().toLowerCase();
  if (!name) throw new Error("Nome da categoria e obrigatorio");
  const priority = ["alta", "normal", "baixa"].includes(category.priority) ? category.priority : "normal";
  const sentiment = classificationOptions.includes(category.sentiment) ? category.sentiment : "Checking";
  const keywords = String(category.keywords || "").trim();
  const active = category.active === false || category.active === 0 ? 0 : 1;
  db.prepare("DELETE FROM deleted_categories WHERE name = ?").run(name);

  if (category.id) {
    db.prepare(`
      UPDATE categories
      SET name = ?, priority = ?, sentiment = ?, keywords = ?, active = ?, updated_at = ?
      WHERE id = ?
    `).run(name, priority, sentiment, keywords, active, now, category.id);
  } else {
    db.prepare(`
      INSERT INTO categories (name, priority, sentiment, keywords, active, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(name) DO UPDATE SET
        priority = excluded.priority,
        sentiment = excluded.sentiment,
        keywords = excluded.keywords,
        active = excluded.active,
        updated_at = excluded.updated_at
    `).run(name, priority, sentiment, keywords, active, now, now);
  }
  reclassifyMessagesByCategoryRules();
  return listCategories();
}

export function deleteCategory(id) {
  const category = db.prepare("SELECT name FROM categories WHERE id = ?").get(id);
  if (category?.name) {
    db.prepare("INSERT OR REPLACE INTO deleted_categories (name, deleted_at) VALUES (?, ?)").run(category.name, nowIso());
  }
  db.prepare("DELETE FROM categories WHERE id = ?").run(id);
  reclassifyMessagesByCategoryRules();
  return listCategories();
}

function normalizeColor(color) {
  const value = String(color || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(value) ? value : "#2764b8";
}

export function listMarkers({ activeOnly = false } = {}) {
  const where = activeOnly ? "WHERE active = 1" : "";
  return db.prepare(`
    SELECT * FROM markers
    ${where}
    ORDER BY active DESC, name
  `).all();
}

export function saveMarker(marker) {
  const now = nowIso();
  const name = String(marker.name || "").trim();
  if (!name) throw new Error("Nome do marcador e obrigatorio");
  const color = normalizeColor(marker.color);
  const active = marker.active === false || marker.active === 0 ? 0 : 1;

  if (marker.id) {
    db.prepare(`
      UPDATE markers
      SET name = ?, color = ?, active = ?, updated_at = ?
      WHERE id = ?
    `).run(name, color, active, now, marker.id);
  } else {
    db.prepare(`
      INSERT INTO markers (name, color, active, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(name) DO UPDATE SET
        color = excluded.color,
        active = excluded.active,
        updated_at = excluded.updated_at
    `).run(name, color, active, now, now);
  }
  return listMarkers();
}

export function deleteMarker(id) {
  db.prepare("UPDATE messages SET marker_id = NULL, updated_at = ? WHERE marker_id = ?").run(nowIso(), id);
  db.prepare("DELETE FROM markers WHERE id = ?").run(id);
  return listMarkers();
}

export function reclassifyMessagesByCategoryRules() {
  const categories = listCategories({ activeOnly: true }).map((category) => ({
    ...category,
    words: String(category.keywords || "")
      .split(",")
      .map((word) => word.trim().toLowerCase())
      .filter(Boolean),
  }));
  const messages = db.prepare("SELECT id, text FROM messages").all();
  const update = db.prepare(`
    UPDATE messages
    SET category = ?, priority = ?, sentiment = ?, confidence = ?, updated_at = ?
    WHERE id = ?
  `);
  let changed = 0;
  const now = nowIso();

  for (const message of messages) {
    const normalized = String(message.text || "").toLowerCase();
    const match = categories.find((category) => category.words.some((word) => normalized.includes(word)));
    const next = match || { name: "outro", priority: "normal", sentiment: "Checking" };
    const confidence = match ? 0.72 : 0.45;
    changed += update.run(next.name, next.priority, next.sentiment, confidence, now, message.id).changes;
  }

  return changed;
}

const messagesWithoutStore = db.prepare("SELECT id, text FROM messages WHERE COALESCE(store_number, '') = ''").all();
const updateStore = db.prepare("UPDATE messages SET store_number = ? WHERE id = ?");
for (const message of messagesWithoutStore) {
  const storeNumber = extractStoreNumber(message.text);
  if (storeNumber) updateStore.run(storeNumber, message.id);
}

export function getSetting(key, fallback = "") {
  const row = db.prepare("SELECT value FROM settings WHERE key = ?").get(key);
  return row?.value ?? fallback;
}

export function setSetting(key, value) {
  const now = nowIso();
  db.prepare(`
    INSERT INTO settings (key, value, updated_at)
    VALUES (?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET
      value = excluded.value,
      updated_at = excluded.updated_at
  `).run(key, String(value ?? "").trim(), now);
}

export function getSettings() {
  return {
    targetChat: getSetting("targetChat", ""),
    watcherPid: getSetting("watcherPid", ""),
    watcherHeartbeat: getSetting("watcherHeartbeat", ""),
  };
}

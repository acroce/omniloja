import fs from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { randomBytes, scrypt, timingSafeEqual } from 'node:crypto';
import { promisify } from 'node:util';
import { spawn } from 'node:child_process';
import { pipeline } from 'node:stream/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(HERE, '../..');
const hashPassword = promisify(scrypt);
export const reports = {
  vendas: 'Exportação de vendas', integracao: 'Integração de Vendas',
  retiradas: 'Relatório de Retiradas', encerramento: 'Encerramento de Caixa',
  autoconsumo: 'Autoconsumo',
};
const TTL = 8 * 60 * 60 * 1000;
const JOB_TTL = 15 * 60 * 1000;
const cookieName = 'noc_export_session';
const id = () => randomBytes(32).toString('hex');
const fail = (status, message) => Object.assign(new Error(message), { status });

export function validatePeriod(start, end) {
  for (const value of [start, end]) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
      !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value) {
      throw fail(400, 'Informe datas válidas.');
    }
  }
  const days = (Date.parse(end) - Date.parse(start)) / 86400000;
  if (days < 0 || days > 365) throw fail(400, 'O período deve ter de 1 a 366 dias, com a data final igual ou posterior à inicial.');
}
export function exportName(report, start, end) {
  const short = value => `${value.slice(8, 10)}-${value.slice(5, 7)}`;
  return `${reports[report]}_${short(start)}_${short(end)}.csv`;
}

async function body(req) {
  if (!String(req.headers['content-type']).startsWith('application/json')) throw fail(415, 'Formato inválido.');
  let text = '';
  for await (const chunk of req) {
    text += chunk;
    if (Buffer.byteLength(text) > 4096) throw fail(413, 'Solicitação muito grande.');
  }
  try { return JSON.parse(text); } catch { throw fail(400, 'Solicitação inválida.'); }
}
function json(res, status, value) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(value));
}
async function runExport({ report, start, end, directory, signal }) {
  const destination = path.join(directory, 'export.csv');
  return new Promise((resolve, reject) => {
    const child = spawn(process.env.AUDIT_PYTHON_BIN || 'python3',
      [path.join(HERE, 'export_csv.py'), report, start, end, destination],
      { cwd: ROOT, env: process.env, signal, timeout: 150000, killSignal: 'SIGKILL', stdio: ['ignore', 'pipe', 'ignore'] });
    let output = '';
    child.stdout.on('data', chunk => { if (output.length < 4096) output += chunk; });
    child.on('error', reject);
    child.on('close', code => {
      if (code !== 0) return reject(new Error('Export failed'));
      try { resolve({ ...JSON.parse(output), destination }); } catch (error) { reject(error); }
    });
  });
}

export function createExportRoutes(options = {}) {
  const authDirectory = options.authDirectory || process.env.NOC_EXPORT_AUTH_DIR || path.join(ROOT, 'outputs/noc_exportacoes_auth');
  const secureCookie = options.secureCookie ?? process.env.NOC_EXPORT_INSECURE_LOCAL !== '1';
  const runner = options.runner || runExport;
  const sessions = new Map(), attempts = new Map(), jobs = new Map();
  let active = 0;
  function sweep() {
    const now = Date.now();
    for (const [key, session] of sessions) if (session.expires <= now) sessions.delete(key);
    for (const [key, entry] of attempts) if (entry.until <= now) attempts.delete(key);
    for (const [key, job] of jobs) if (job.expires <= now) {
      jobs.delete(key); job.abort.abort();
      fs.rm(job.directory, { recursive: true, force: true }).catch(() => {});
    }
  }
  const interval = setInterval(sweep, 60000); interval.unref();
  const cookie = (value, age) => `${cookieName}=${value}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${age}${secureCookie ? '; Secure' : ''}`;
  async function handle(req, res, url) {
    const pathname = url.pathname;
    if (!(pathname === '/exportacoes' || pathname.startsWith('/exportacoes/') || pathname.startsWith('/api/noc-exportacoes/'))) return false;
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'same-origin');
    res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'");
    try {
      sweep();
      const token = String(req.headers.cookie || '').split(';').map(x => x.trim()).find(x => x.startsWith(cookieName + '='))?.slice(cookieName.length + 1);
      const session = sessions.get(token);
      if (req.method === 'POST' && req.headers.origin) {
        let origin;
        try { origin = new URL(req.headers.origin); } catch { throw fail(403, 'Origem inválida.'); }
        if (origin.host !== req.headers.host) throw fail(403, 'Origem inválida.');
      }
      if (pathname === '/api/noc-exportacoes/login' && req.method === 'POST') {
        const key = req.socket.remoteAddress || 'local';
        const accountKey = 'all';
        for (const [k, limit] of [[key, 8], [accountKey, 40]]) {
          if ((attempts.get(k)?.count || 0) >= limit) throw fail(429, 'Muitas tentativas. Aguarde 15 minutos.');
        }
        const data = await body(req);
        if (typeof data.username !== 'string' || typeof data.password !== 'string' || data.password.length > 200) throw fail(400, 'Informe usuário e senha.');
        // Count before asynchronous hashing to also bound parallel attempts.
        for (const k of [key, accountKey]) {
          const entry = attempts.get(k) || { count: 0, until: Date.now() + 900000 };
          entry.count++; attempts.set(k, entry);
        }
        let users;
        try { users = JSON.parse(await fs.readFile(path.join(authDirectory, 'users.json'), 'utf8')); }
        catch { throw fail(503, 'Acesso ainda não configurado. Contate o administrador do NOC.'); }
        const user = Object.hasOwn(users, data.username) ? users[data.username] : null;
        const hash = await hashPassword(data.password, user?.salt || 'unconfigured-user', 64);
        if (!user || !timingSafeEqual(hash, Buffer.from(user.hash, 'hex'))) throw fail(401, 'Usuário ou senha inválidos.');
        attempts.delete(key);
        attempts.get(accountKey).count--;
        if (sessions.size >= 200) throw fail(429, 'Limite de acessos atingido. Tente mais tarde.');
        const sessionToken = id();
        if (token) sessions.delete(token);
        sessions.set(sessionToken, { username: data.username, csrf: id(), expires: Date.now() + TTL });
        res.setHeader('Set-Cookie', cookie(sessionToken, TTL / 1000));
        json(res, 200, { ok: true }); return true;
      }
      const assets = { '/exportacoes/app.js': ['app.js', 'text/javascript'], '/exportacoes/style.css': ['style.css', 'text/css'] };
      if (assets[pathname] && req.method === 'GET') {
        const [file, type] = assets[pathname];
        res.setHeader('Content-Type', type + '; charset=utf-8');
        res.end(await fs.readFile(path.join(HERE, 'public', file))); return true;
      }
      if (pathname === '/exportacoes/login' && req.method === 'GET') {
        if (session) { res.writeHead(302, { Location: '/exportacoes' }); res.end(); }
        else { res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(await fs.readFile(path.join(HERE, 'public/login.html'))); }
        return true;
      }
      if (!session) {
        if (pathname.startsWith('/api/')) throw fail(401, 'Sua sessão expirou. Entre novamente.');
        res.writeHead(302, { Location: '/exportacoes/login' }); res.end(); return true;
      }
      if (req.method === 'POST' && req.headers['x-csrf-token'] !== session.csrf) throw fail(403, 'Sessão inválida. Atualize a página.');
      if (['/exportacoes', '/exportacoes/'].includes(pathname) && req.method === 'GET') {
        res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(await fs.readFile(path.join(HERE, 'public/index.html'))); return true;
      }
      if (pathname === '/api/noc-exportacoes/session' && req.method === 'GET') {
        json(res, 200, { username: session.username, csrf: session.csrf }); return true;
      }
      if (pathname === '/api/noc-exportacoes/logout' && req.method === 'POST') {
        sessions.delete(token); res.setHeader('Set-Cookie', cookie('', 0)); json(res, 200, { ok: true }); return true;
      }
      if (pathname === '/api/noc-exportacoes/jobs' && req.method === 'POST') {
        const { report, start, end } = await body(req);
        if (!Object.hasOwn(reports, report)) throw fail(400, 'Relatório inválido.');
        validatePeriod(start, end);
        if (active >= 1) throw fail(409, 'Há uma exportação em andamento. Aguarde a conclusão e tente novamente.');
        if (jobs.size >= 30) throw fail(429, 'Limite de arquivos temporários atingido. Tente novamente em alguns minutos.');
        active++;
        let directory;
        try { directory = await fs.mkdtemp(path.join(os.tmpdir(), 'noc-export-')); }
        catch (error) { active--; throw error; }
        const jobId = id();
        const job = { id: jobId, owner: token, report, start, end, directory, status: 'running',
          filename: exportName(report, start, end), expires: Date.now() + JOB_TTL, abort: new AbortController() };
        jobs.set(jobId, job);
        Promise.resolve().then(() => runner({ ...job, signal: job.abort.signal })).then(result => {
          Object.assign(job, result, { status: 'ready' });
          console.log(JSON.stringify({ event: 'noc_export', user: session.username, report, start, end, rows: result.rows }));
        }).catch(() => {
          job.status = 'failed'; job.error = 'Não foi possível consultar o Pleno. Tente um período menor ou contate o administrador.';
          fs.rm(directory, { recursive: true, force: true }).catch(() => {});
          console.warn(JSON.stringify({ event: 'noc_export_failed', user: session.username, report, start, end }));
        }).finally(() => { active--; });
        json(res, 202, { id: jobId }); return true;
      }
      const match = pathname.match(/^\/api\/noc-exportacoes\/jobs\/([a-f0-9]{64})(\/download)?$/);
      if (match && req.method === 'GET') {
        const job = jobs.get(match[1]);
        if (!job || job.owner !== token) throw fail(404, 'Arquivo não encontrado ou expirado. Gere uma nova exportação.');
        if (!match[2]) {
          json(res, 200, { id: job.id, status: job.status, rows: job.rows, filename: job.filename, error: job.error }); return true;
        }
        if (job.status !== 'ready') throw fail(409, 'O arquivo ainda não está disponível.');
        const stat = await fs.stat(job.destination);
        const fallback = job.filename.normalize('NFD').replace(/[\u0300-\u036f]/g, '');
        res.writeHead(200, { 'content-type': 'text/csv; charset=utf-8', 'content-length': stat.size,
          'content-disposition': `attachment; filename="${fallback}"; filename*=UTF-8''${encodeURIComponent(job.filename)}` });
        await pipeline(createReadStream(job.destination), res); return true;
      }
      throw fail(404, 'Página não encontrada.');
    } catch (error) {
      if (!res.headersSent) json(res, error.status || 500, { error: error.status ? error.message : 'Não foi possível concluir a solicitação.' });
      else res.destroy();
      return true;
    }
  }
  handle.close = async () => {
    clearInterval(interval);
    for (const job of jobs.values()) { job.abort.abort(); await fs.rm(job.directory, { recursive: true, force: true }); }
  };
  return handle;
}

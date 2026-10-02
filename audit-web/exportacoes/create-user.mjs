import { randomBytes, scryptSync } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const username = process.argv[2] || 'exportador';
if (!/^[a-zA-Z0-9._-]{3,40}$/.test(username)) throw new Error('Nome de usuário inválido.');
const directory = process.env.NOC_EXPORT_AUTH_DIR || path.join(root, 'outputs/noc_exportacoes_auth');
await fs.mkdir(directory, { recursive: true, mode: 0o700 });
const filename = path.join(directory, 'users.json');
let users = {};
try { users = JSON.parse(await fs.readFile(filename, 'utf8')); } catch (error) { if (error.code !== 'ENOENT') throw error; }
if (users[username]) throw new Error('Usuário já existe. Nenhuma senha foi alterada.');
const password = randomBytes(18).toString('base64url');
const salt = randomBytes(16).toString('hex');
users[username] = { salt, hash: scryptSync(password, salt, 64).toString('hex') };
const temporary = filename + '.' + randomBytes(6).toString('hex');
await fs.writeFile(temporary, JSON.stringify(users, null, 2), { mode: 0o600, flag: 'wx' });
await fs.rename(temporary, filename);
// Capture stdout to a protected credential handoff file; never put this in a build.
console.log(`Usuário: ${username}\nSenha: ${password}\n`);

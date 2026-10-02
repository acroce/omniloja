import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { scryptSync } from 'node:crypto';
import { createExportRoutes, validatePeriod, exportName } from './routes.mjs';

test('strict inclusive dates and filenames', () => {
  validatePeriod('2026-01-01', '2026-09-28');
  validatePeriod('2024-01-01', '2024-12-31');
  for (const dates of [['2026-02-30','2026-03-02'],['2026-09-29','2026-09-01'],['2026-01-01','2027-01-02'],["2026-01-01' OR 1=1",'2026-02-01']]) assert.throws(() => validatePeriod(...dates));
  assert.equal(exportName('encerramento', '2026-09-01', '2026-09-29'), 'Encerramento de Caixa_01-09_29-09.csv');
});

test('login, session protection, exports, ownership, failures, logout and throttling', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'noc-export-test-'));
  await fs.writeFile(path.join(directory, 'users.json'), JSON.stringify({ tester: { salt: 'testsalt', hash: scryptSync('test-password', 'testsalt', 64).toString('hex') } }));
  let release;
  const handler = createExportRoutes({ authDirectory: directory, secureCookie: true, runner: async job => {
    if (job.report === 'integracao') throw new Error('secret-database-error');
    if (job.report === 'encerramento') await new Promise(resolve => { release = resolve; });
    const destination = path.join(job.directory, 'export.csv');
    await fs.writeFile(destination, '\ufeffFilial;Nome\r\n1;Teste\r\n');
    return { destination, rows: 1 };
  }});
  const server = createServer(async (req, res) => { if (!await handler(req, res, new URL(req.url, 'http://localhost'))) { res.writeHead(404); res.end(); } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const call = (url, { cookie, csrf, method = 'GET', data, origin } = {}) => fetch(base + url, { method, redirect: 'manual', headers: { 'content-type':'application/json', ...(cookie ? { cookie } : {}), ...(csrf ? { 'x-csrf-token':csrf } : {}), ...(origin ? { origin } : {}) }, ...(data ? { body: JSON.stringify(data) } : {}) });
  const prefix = '/api/noc-exportacoes';
  async function login() {
    const response = await call(prefix + '/login', { method: 'POST', data: { username:'tester', password:'test-password' } });
    assert.equal(response.status, 200);
    assert.match(response.headers.get('set-cookie'), /HttpOnly; SameSite=Strict; Max-Age=28800; Secure/);
    const cookie = response.headers.get('set-cookie').split(';')[0];
    const session = await (await call(prefix + '/session', { cookie })).json();
    return { cookie, csrf: session.csrf };
  }
  async function ready(job, auth) {
    for (let i=0;i<50;i++) { const data = await (await call(prefix + '/jobs/' + job.id, auth)).json(); if (data.status !== 'running') return data; await new Promise(resolve => setTimeout(resolve,10)); }
    throw new Error('Job timeout');
  }
  try {
    assert.equal((await call('/exportacoes')).status, 302);
    assert.equal((await call(prefix + '/jobs', { method:'POST', data:{} })).status, 401);
    assert.equal((await call(prefix + '/login', { method:'POST', origin:'https://attacker.invalid', data:{ username:'tester',password:'test-password' } })).status,403);
    const auth = await login(), other = await login();
    assert.equal((await call('/exportacoes',auth)).status,200);
    const data={ report:'autoconsumo',start:'2026-09-01',end:'2026-09-30' };
    assert.equal((await call(prefix+'/jobs',{cookie:auth.cookie,method:'POST',data})).status,403);
    assert.equal((await call(prefix+'/jobs',{...auth,method:'POST',data:{...data,report:'../users'}})).status,400);
    assert.equal((await call(prefix+'/jobs',{...auth,method:'POST',data:{...data,start:'2026-02-30'}})).status,400);
    const job=await (await call(prefix+'/jobs',{...auth,method:'POST',data})).json();
    assert.equal((await ready(job,auth)).rows,1);
    assert.equal((await call(prefix+'/jobs/'+job.id+'/download')).status,401);
    assert.equal((await call(prefix+'/jobs/'+job.id+'/download',other)).status,404);
    const download=await call(prefix+'/jobs/'+job.id+'/download',auth);
    assert.equal(download.status,200);assert.match(download.headers.get('content-disposition'),/UTF-8''Autoconsumo_01-09_30-09/);
    assert.deepEqual([...new Uint8Array(await download.arrayBuffer()).slice(0,3)],[239,187,191]);
    const failed=await (await call(prefix+'/jobs',{...auth,method:'POST',data:{...data,report:'integracao'}})).json();
    const failure=await ready(failed,auth);assert.equal(failure.status,'failed');assert.ok(!failure.error.includes('secret'));
    const running=await (await call(prefix+'/jobs',{...auth,method:'POST',data:{...data,report:'encerramento'}})).json();
    assert.equal((await call(prefix+'/jobs',{...other,method:'POST',data})).status,409);
    assert.equal((await call(prefix+'/jobs/'+running.id+'/download',auth)).status,409);
    release();await ready(running,auth);
    assert.equal((await call(prefix+'/logout',{...auth,method:'POST',data:{}})).status,200);
    assert.equal((await call(prefix+'/jobs/'+job.id+'/download',auth)).status,401);
    for(let i=0;i<8;i++) assert.equal((await call(prefix+'/login',{method:'POST',data:{username:'tester',password:'wrong'}})).status,401);
    assert.equal((await call(prefix+'/login',{method:'POST',data:{username:'tester',password:'wrong'}})).status,429);
  } finally { await handler.close(); server.closeAllConnections(); await new Promise(resolve=>server.close(resolve)); await fs.rm(directory,{recursive:true,force:true}); }
});

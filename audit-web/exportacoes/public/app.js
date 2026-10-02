const api = '/api/noc-exportacoes';
const $ = selector => document.querySelector(selector);
const names = { vendas: 'Exportação de vendas', integracao: 'Integração de Vendas', retiradas: 'Relatório de Retiradas', encerramento: 'Encerramento de Caixa', autoconsumo: 'Autoconsumo' };
const descriptions = { vendas: 'Vendas, recebimentos, troco e situação da prestação por loja e dia.', integracao: 'Comparação entre vendas dos cupons e vendas ECF por loja, data e PDV.', retiradas: 'Retiradas em dinheiro, com operador, supervisor e meio de pagamento.', encerramento: 'Valores de fechamento, retiradas, resíduos e situação dos caixas.', autoconsumo: 'Consumo por loja e produto, com requisição, situação, nota fiscal, quantidade e custos médio e da última nota.' };
let csrf = '', selected = 'vendas', busy = false;
async function request(url, options = {}) {
  const response = await fetch(api + url, { ...options, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...options.headers } });
  const data = await response.json();
  if (response.status === 401 && !$('#login-form')) { location.assign('/exportacoes/login'); throw new Error('Sessão expirada.'); }
  if (!response.ok) throw new Error(data.error || 'Não foi possível concluir. Tente novamente.');
  return data;
}
const login = $('#login-form');
if (login) {
  login.addEventListener('submit', async event => {
    event.preventDefault(); const button = login.querySelector('button'); button.disabled = true;
    $('#message').textContent = '';
    try { await request('/login', { method: 'POST', body: JSON.stringify({ username: $('#username').value.trim(), password: $('#password').value }) }); location.assign('/exportacoes'); }
    catch (error) { $('#message').textContent = error.message; button.disabled = false; }
  });
} else {
  const localDate = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const short = value => `${value.slice(8,10)}-${value.slice(5,7)}`;
  function preview() {
    const start = $('#start').value, end = $('#end').value;
    const days = Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1;
    $('#day-count').textContent = Number.isFinite(days) && days > 0 ? `${days} ${days === 1 ? 'dia' : 'dias'}` : 'Verifique o período';
    $('#filename').textContent = start && end ? `${names[selected]}_${short(start)}_${short(end)}.csv` : 'Selecione as datas';
    $('#end').min = start;
    if (!busy) $('#result').hidden = true;
  }
  function month(previous = false) {
    const today = new Date();
    $('#start').value = localDate(new Date(today.getFullYear(), today.getMonth() - (previous ? 1 : 0), 1));
    $('#end').value = localDate(previous ? new Date(today.getFullYear(), today.getMonth(), 0) : today);
    preview();
  }
  function select(button) {
    if (busy) return;
    selected = button.dataset.report;
    document.querySelectorAll('[role=tab]').forEach(tab => { const current = tab === button; tab.setAttribute('aria-selected', String(current)); tab.tabIndex = current ? 0 : -1; });
    $('#report-title').textContent = names[selected]; $('#report-description').textContent = descriptions[selected];
    $('#report-panel').setAttribute('aria-labelledby', button.id); preview();
  }
  document.querySelectorAll('[role=tab]').forEach((tab, index, tabs) => {
    tab.addEventListener('click', () => select(tab));
    tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = tabs.length - 1;
      if (next !== undefined && !busy) { event.preventDefault(); select(tabs[next]); tabs[next].focus(); }
    });
  });
  $('#current-month').addEventListener('click', () => month()); $('#previous-month').addEventListener('click', () => month(true));
  $('#start').addEventListener('change', preview); $('#end').addEventListener('change', preview);
  function lock(value) {
    busy = value;
    document.querySelectorAll('#export-form button, #export-form input, [role=tab]').forEach(control => control.disabled = value);
    $('#export-button').textContent = value ? 'Gerando CSV…' : 'Exportar CSV ↓';
    $('#report-panel').setAttribute('aria-busy', String(value));
  }
  $('#export-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy) return;
    const start = $('#start').value, end = $('#end').value;
    $('#result').hidden = false; $('#result').classList.remove('error'); $('#download').hidden = true;
    const days = (Date.parse(end) - Date.parse(start)) / 86400000;
    if (!Number.isFinite(days) || days < 0 || days > 365) { $('#message').textContent = 'Escolha um período válido de até 366 dias.'; $('#result').classList.add('error'); return; }
    lock(true); $('#message').textContent = 'Consultando o Pleno e preparando o arquivo. Aguarde nesta página.';
    try {
      const job = await request('/jobs', { method: 'POST', body: JSON.stringify({ report: selected, start, end }) });
      const deadline = Date.now() + 180000;
      while (true) {
        const result = await request(`/jobs/${job.id}`);
        if (result.status === 'failed') throw new Error(result.error);
        if (result.status === 'ready') {
          $('#message').textContent = result.rows === 0 ? 'Nenhum registro encontrado neste período. O CSV contém apenas os cabeçalhos.' : `Arquivo pronto. ${Number(result.rows).toLocaleString('pt-BR')} registros exportados.`;
          const link = $('#download'); link.href = `${api}/jobs/${job.id}/download`; link.download = result.filename; link.textContent = 'Baixar ' + result.filename; link.hidden = false; link.click(); break;
        }
        if (Date.now() > deadline) throw new Error('A consulta excedeu o tempo de espera. Tente novamente em alguns instantes com um período menor.');
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
    } catch (error) { $('#message').textContent = error.message; $('#result').classList.add('error'); }
    finally { lock(false); }
  });
  $('#logout').addEventListener('click', async () => {
    try { await request('/logout', { method: 'POST', body: '{}' }); location.assign('/exportacoes/login'); }
    catch (error) { $('#result').hidden = false; $('#message').textContent = error.message; }
  });
  const linkedTab = [...document.querySelectorAll('[role=tab]')].find(tab => tab.dataset.report === location.hash.slice(1));
  if (linkedTab) select(linkedTab);
  lock(true);
  request('/session').then(session => { csrf = session.csrf; $('#account').textContent = session.username; lock(false); }).catch(error => { $('#result').hidden = false; $('#message').textContent = error.message; });
  month();
}

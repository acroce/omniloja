import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const root = path.resolve(new URL('..', import.meta.url).pathname);
loadDotEnv(path.join(root, '.env'));

const out = path.join(root, 'outputs', 'prevencao_perdas');
const db = path.join(out, 'acompanhamento.sqlite');
const runStatusFile = path.join(out, 'execucao.json');
const runDate = today();
const runId = Date.now();
const limit = Number(process.env.PREV_PERDAS_LIMIT || 25);
const offset = Number(process.env.PREV_PERDAS_OFFSET || 0);
const includeRetries = process.env.PREV_PERDAS_INCLUDE_RETRIES === '1';
const dryRun = process.env.PREV_PERDAS_DRY_RUN === '1';
const startDate = process.env.PREV_PERDAS_START_DATE || daysAgo(30);
const endDate = process.env.PREV_PERDAS_END_DATE || todayBR();
const pendingStatuses = new Set(['pendente_reconsulta', 'pendente_revalidacao_pleno']);
const chrome = Object.hasOwn(process.env, 'PLENO_CHROME_PATH')
  ? process.env.PLENO_CHROME_PATH || undefined
  : process.env.PLENO_CHROME_PATH || (process.platform === 'darwin' ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined);
const profile = path.join(root, '.cache', 'pleno-chrome-profile', 'prevencao-perdas', `run-${runId}`);

fs.mkdirSync(out, { recursive: true });

let processed = 0;
let completed = 0;
let failed = 0;
let pendingReview = 0;
let currentFilial = '';
let currentNota = '';
let interrupted = false;
let interruptionMessage = '';

heartbeat('executando', 'Iniciando Chrome e abrindo Retificacao de Sobra e Falta Dia.');

const context = await chromium.launchPersistentContext(profile, {
  ...(chrome ? { executablePath: chrome } : {}),
  headless: false,
  ignoreHTTPSErrors: true,
  downloadsPath: out,
  args: ['--ignore-certificate-errors', '--start-maximized'],
  viewport: null,
});
const page = context.pages()[0] || await context.newPage();
page.setDefaultTimeout(Number(process.env.PREV_PERDAS_TIMEOUT_MS || 90000));

try {
  await openRetificacao(page);
  if (process.env.PREV_PERDAS_STOP_AFTER_FILTER === '1') {
    heartbeat('finalizado', 'Filtro aplicado; execucao pausada antes de abrir notas.');
    console.log('PREV_PERDAS_STOP_AFTER_FILTER=1 ativo: filtro aplicado e tela mantida aberta para conferencia.');
    await new Promise(() => {});
  }
  const handled = includeRetries ? new Set() : handledIds();
  const candidates = await collectCandidatesAcrossPages(page, handled, limit + offset);
  if (offset > 0) candidates.splice(0, offset);
  candidates.splice(limit);
  console.log(`Prevencao e perdas: ${candidates.length} nota(s) selecionada(s).`);

  if (!dryRun) {
    for (const item of candidates) {
      currentFilial = item.filial || '';
      currentNota = item.nroNf || item.notaId || '';
      heartbeat('executando', 'Abrindo nota e acompanhando emissao.');
      const startedAt = new Date().toISOString();
      try {
        const result = await processOne(page, item);
        const finalStatus = pendingStatuses.has(result.status) ? result.status : 'concluido';
        record({ ...item, processKey: processKeyForItem(item), runDate, status: finalStatus, situacaoFinal: result.situacaoFinal, message: result.message, startedAt, finishedAt: new Date().toISOString() });
        if (finalStatus === 'concluido') completed++;
        else pendingReview++;
      } catch (error) {
        if (/Target page, context or browser has been closed/i.test(String(error?.message || ''))) throw error;
        const screenshotFile = `erro_${Date.now()}_${safeName(item.retificacaoId || item.notaId || item.albaran || 'nota')}.png`;
        await page.screenshot({ path: path.join(out, screenshotFile), fullPage: true }).catch(() => {});
        const recoverable = recoverablePlenoTimeout(error);
        record({
          ...item,
          processKey: processKeyForItem(item),
          runDate,
          status: recoverable ? 'pendente_revalidacao_pleno' : 'erro',
          situacaoFinal: recoverable ? 'Revalidar link Pleno' : undefined,
          message: recoverable ? 'Revalidar: timeout ao localizar link do Pleno' : error.message,
          errorStage: error.stage || 'pleno',
          screenshotFile,
          startedAt,
          finishedAt: new Date().toISOString(),
        });
        if (recoverable) pendingReview++;
        else failed++;
        console.error(`[Prevencao ${currentFilial}] falha na nota ${currentNota}: ${error.message}`);
      } finally {
        processed++;
        heartbeat('executando', `Processadas ${processed} nota(s).`);
      }
    }
  }
} catch (error) {
  interrupted = true;
  interruptionMessage = error.message;
  heartbeat('erro', error.message);
  throw error;
} finally {
  heartbeat(interrupted ? 'erro' : 'finalizado', interrupted ? interruptionMessage : `Lote encerrado: ${processed} nota(s), ${completed} OK, ${failed} erro(s), ${pendingReview} reconsulta(s).`);
  if (process.env.PREV_PERDAS_KEEP_OPEN === '1') {
    console.log('PREV_PERDAS_KEEP_OPEN=1 ativo: Chrome mantido aberto para conferencia visual. Pressione Ctrl+C para encerrar.');
    await new Promise(() => {});
  }
  await context.close().catch(() => {});
}

function recoverablePlenoTimeout(error) {
  const message = String(error?.message || '');
  return error?.stage === 'abrir_nota' ||
    (/locator\.waitFor:\s*Timeout/i.test(message) && /data-dia01id/i.test(message));
}

async function collectCandidatesAcrossPages(p, handled, max) {
  const selected = [];
  const seen = new Set();
  const maxPages = Number(process.env.PREV_PERDAS_MAX_PAGES || 30);
  for (let pageNo = 1; pageNo <= maxPages && selected.length < max; pageNo++) {
    const gridRows = await collectGridRows(p);
    const pendingRows = gridRows.filter((row) => /PENDENTE|AGUARDANDO/i.test(row.situacaoInicial || ''));
    const candidates = pendingRows
      .filter((item) => includeRetries || !handled.has(String(item.retificacaoId || item.notaId || item.albaran || item.nroNf)))
      .filter((item) => item.href || item.retificacaoId || item.dia01Id)
      .filter((item) => {
        const key = process.env.PREV_PERDAS_GROUP_BY_NOTA === '0'
          ? item.retificacaoId || item.dia01Id || [notaGroupKey(item), item.mercadoria || '', item.rowIndex].join('|')
          : notaGroupKey(item) || item.retificacaoId || item.dia01Id || [item.mercadoria || '', item.rowIndex].join('|');
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    console.log(`Prevencao e perdas: pagina ${pageNo}: ${gridRows.length} linha(s), ${pendingRows.length} pendente(s), ${candidates.length} candidata(s).`);
    if (pageNo === 1) console.log('Amostra da grade:', JSON.stringify(gridRows.slice(0, 5), null, 2));
    selected.push(...candidates);
    if (selected.length >= max) break;
    if (!await nextGridPage(p)) break;
  }
  return selected.slice(0, max);
}

async function openRetificacao(p) {
  const url = process.env.PREV_PERDAS_RETIFICACAO_URL || process.env.PLENO_RETIFICACAO_URL || 'https://172.22.20.101/retificacao-sobra-falta-dia';
  await gotoPleno(p, url);
  await loginPleno(p, url);
  await openAdvancedFilter(p);
  heartbeat('executando', 'Filtro avancado aberto; preenchendo periodo e situacoes.');
  await fillFilterDates(p, startDate, endDate);
  await setWantedSituations(p);
  await closeDatepickers(p);
  await waitAriusGoneForScreenshot(p);
  await p.screenshot({ path: path.join(out, 'debug_filtro_preenchido.png'), fullPage: true }).catch(() => {});
  if (process.env.PREV_PERDAS_STOP_AT_FILTER_MODAL === '1') {
    heartbeat('finalizado', 'Filtro avancado preenchido; execucao pausada antes de pesquisar.');
    console.log('PREV_PERDAS_STOP_AT_FILTER_MODAL=1 ativo: filtro preenchido e tela mantida aberta para conferencia.');
    await new Promise(() => {});
  }
  heartbeat('executando', 'Filtro preenchido; pesquisando notas pendentes.');
  await clickSearch(p);
  await p.waitForTimeout(1500);
  await p.screenshot({ path: path.join(out, 'debug_pos_pesquisa.png'), fullPage: true }).catch(() => {});
  await waitGrid(p);
  if (process.env.PREV_PERDAS_DEBUG_GRID === '1') {
    console.log('Debug grade:', JSON.stringify(await debugGridLinks(p), null, 2));
  }
}

async function gotoPleno(p, url) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 45000 });
      lastError = null;
      break;
    } catch (error) {
      lastError = error;
      console.warn(`Navegacao inicial demorou/trocou rede na tentativa ${attempt} (${error.message}); tentando commit.`);
      try {
        await p.goto(url, { waitUntil: 'commit', timeout: 45000 });
        lastError = null;
        break;
      } catch (commitError) {
        lastError = commitError;
        if (!/ERR_NETWORK_CHANGED|Timeout/i.test(commitError.message) || attempt === 3) break;
        await p.waitForTimeout(3000);
      }
    }
  }
  if (lastError) throw lastError;
  await p.waitForFunction(() => {
    const text = document.body?.innerText || '';
    return /Retifica[cç][aã]o de Sobra e Falta Dia|senha|usuario|usu[aá]rio/i.test(text) ||
      Boolean(document.querySelector('#btn-filtro-avancado,#senha,#Senha,input[type=password]'));
  }, null, { timeout: 60000 });
}

async function openAdvancedFilter(p) {
  const button = p.locator('#btn-filtro-avancado').first();
  await button.waitFor({ state: 'visible', timeout: 30000 });
  await waitAriusIdle(p);
  await button.evaluate((element) => element.click());
  let opened = await waitForAdvancedFilterModal(p, 8000);
  if (!opened) {
    const box = await button.boundingBox();
    if (box) await p.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    opened = await waitForAdvancedFilterModal(p, 12000);
  }
  if (!opened) {
    await p.screenshot({ path: path.join(out, 'debug_filtro_nao_abriu.png'), fullPage: true }).catch(() => {});
    const text = clean(await p.locator('body').innerText().catch(() => ''));
    throw new Error(`Filtro Avancado nao abriu apos clicar no funil. Tela atual: ${text.slice(0, 800)}`);
  }
  await waitAriusIdle(p);
}

async function waitAriusIdle(p) {
  await p.waitForFunction(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const center = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    if (center && visible(center) && /arius|carreg|load/i.test(`${center.textContent || ''} ${center.className || ''}`)) return false;
    return !Array.from(document.querySelectorAll('.blockUI,.blockOverlay,.loading,.loader,.modal-backdrop'))
      .some((element) => visible(element) && /arius|carreg|load/i.test(element.textContent || element.className || ''));
  }, null, { timeout: 30000 }).catch(() => {});
}

async function waitUsefulScreenAfterAction(p, timeout = 180000) {
  await p.waitForFunction(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const center = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    const centerText = `${center?.textContent || ''} ${center?.className || ''}`;
    if (center && visible(center) && /arius|carreg|load|process/i.test(centerText)) return false;
    const bodyText = document.body?.innerText || '';
    const hasActionButton = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .some((element) => visible(element) && /Verifica\s*NF|Emitir\s*NF/i.test(`${element.textContent || ''} ${element.value || ''} ${element.title || ''}`));
    const hasResultMessage = /Verifica[cç][aã]o|Processando\s+NFE|erro|falha|sucesso|autorizad|rejei/i.test(bodyText);
    const hasNotaScreen = /Edi[cç][aã]o\s+NF\s+Transfer[eê]ncia\s+Sa[ií]da/i.test(bodyText);
    return (hasActionButton || hasResultMessage) && hasNotaScreen;
  }, null, { timeout });
  await waitAriusIdle(p);
}

async function waitAriusGoneForScreenshot(p) {
  await p.waitForFunction(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const center = document.elementFromPoint(window.innerWidth / 2, window.innerHeight / 2);
    return !(center && visible(center) && /arius|carreg|load|process/i.test(`${center.textContent || ''} ${center.className || ''}`));
  }, null, { timeout: 90000 });
}

async function waitForAdvancedFilterModal(p, timeout) {
  return p.locator('label').filter({ hasText: /PENDENTE\s+CRIA[ÇC][AÃ]O\s+DE\s+NF/i }).first()
    .waitFor({ state: 'visible', timeout })
    .then(() => true)
    .catch(() => false);
}

async function fillFilterDates(p, start, end) {
  const visibleInputs = p.locator('input:visible');
  const count = await visibleInputs.count();
  const dateIndexes = [];
  for (let i = 0; i < count; i++) {
    const input = visibleInputs.nth(i);
    const value = await input.inputValue().catch(() => '');
    const placeholder = await input.getAttribute('placeholder').catch(() => '') || '';
    if (/\d{2}\/\d{2}\/\d{4}/.test(value) || /data|periodo|per[ií]odo/i.test(placeholder)) dateIndexes.push(i);
  }
  const targets = dateIndexes.length >= 2 ? [visibleInputs.nth(dateIndexes.at(-2)), visibleInputs.nth(dateIndexes.at(-1))] : [visibleInputs.nth(Math.max(0, count - 2)), visibleInputs.nth(Math.max(0, count - 1))];
  await fillValue(targets[0], start);
  await fillValue(targets[1], end);
  await p.keyboard.press('Escape').catch(() => {});
  await p.waitForTimeout(300);
}

async function closeDatepickers(p) {
  await p.evaluate(() => {
    document.activeElement?.blur?.();
    for (const element of document.querySelectorAll('.datepicker,.datepicker-dropdown,.ui-datepicker,.bootstrap-datetimepicker-widget,[class*="datepicker"],[id*="datepicker"]')) {
      element.style.display = 'none';
      element.style.visibility = 'hidden';
    }
  }).catch(() => {});
  await p.waitForTimeout(300);
}

async function setWantedSituations(p) {
  await p.evaluate(() => {
    const normalize = (value) => String(value || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').toUpperCase();
    const situationLabels = [
      'ABERTO',
      'AGUARDANDO CONFIRMACAO',
      'PENDENTE CRIACAO DE NF',
      'AGUARDANDO EMISSAO DE NF',
      'CONCLUIDO',
      'CANCELADO',
    ];
    const wanted = new Set(['PENDENTE CRIACAO DE NF', 'AGUARDANDO EMISSAO DE NF']);
    for (const label of Array.from(document.querySelectorAll('label'))) {
      const text = normalize(label.innerText);
      const situation = situationLabels.find((term) => text.includes(term));
      if (!situation) continue;
      const input = label.querySelector('input[type=checkbox]') || document.getElementById(label.getAttribute('for') || '');
      if (input && input.checked !== wanted.has(situation)) {
        input.checked = wanted.has(situation);
        input.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }
  });
}

async function clickSearch(p) {
  const clicked = await p.evaluate(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const filterModal = Array.from(document.querySelectorAll('.modal.in,.modal.show,.modal,[role=dialog],div'))
      .filter(visible)
      .filter((element) => /Filtro\s+Avan[cç]ado/i.test(element.innerText || ''))
      .sort((a, b) => {
        const area = (element) => {
          const rect = element.getBoundingClientRect();
          return rect.width * rect.height;
        };
        return area(b) - area(a);
      })[0];
    const root = filterModal || document;
    const candidates = Array.from(root.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .filter(visible)
      .filter((element) => {
        const text = `${element.textContent || ''} ${element.value || ''} ${element.title || ''}`.replace(/\s+/g, ' ').trim();
        return /^Pesquisar$/i.test(text) || /\bPesquisar\b/i.test(text);
      })
      .filter((element) => !/Salvar/i.test(`${element.textContent || ''} ${element.value || ''}`));
    const button = candidates.find((element) => {
      const rect = element.getBoundingClientRect();
      return !filterModal || rect.top >= filterModal.getBoundingClientRect().top;
    }) || candidates.at(-1);
    if (!button) return false;
    button.click();
    return true;
  });
  if (!clicked) {
    const visibleButtons = await p.evaluate(() => Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .filter((element) => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
      })
      .map((element) => `${element.tagName}:${element.textContent || element.value || element.title || ''}`.replace(/\s+/g, ' ').trim())
      .slice(0, 80));
    throw new Error(`Botao Pesquisar visivel nao encontrado. Elementos visiveis: ${visibleButtons.join(' | ')}`);
  }
}

async function waitGrid(p) {
  await p.waitForFunction(() => Array.from(document.querySelectorAll('tbody tr,.ui-jqgrid-btable tr')).some((row) => row.offsetParent && row.querySelectorAll('td').length >= 8), null, { timeout: 30000 });
}

async function collectGridRows(p) {
  return p.evaluate(() => {
    const normalize = (value) => String(value || '')
      .normalize('NFD')
      .replace(/\p{Diacritic}/gu, '')
      .replace(/\s+/g, ' ')
      .trim()
      .toUpperCase();
    const table = document.querySelector('#dataTables') || document.querySelector('table');
    const rows = Array.from((table || document).querySelectorAll('tbody tr,.ui-jqgrid-btable tr'))
      .filter((row) => row.offsetParent && row.querySelectorAll('td').length >= 8);
    return rows.map((row, index) => {
      const cellElements = Array.from(row.querySelectorAll('td'));
      const cells = cellElements.map((cell) => cell.innerText.trim());
      const statusCell = cellElements.at(-1);
      const statusLinks = Array.from(statusCell?.querySelectorAll('a,button,[onclick]') || []);
      const statusLink = statusLinks.find((element) => /notafiscal|editar|PENDENTE|AGUARDANDO/i.test(`${element.getAttribute('href') || ''} ${element.getAttribute('onclick') || ''} ${element.textContent || ''}`)) || statusLinks[0];
      const href = statusLink?.getAttribute('href') || '';
      const onclick = statusLink?.getAttribute('onclick') || '';
      const dia01Id = statusLink?.getAttribute('data-dia01id') || '';
      const ref = [href, onclick].join(' ');
      const id = ref.match(/(?:id\/|id=|editar\/id\/|editar\s*\(|notafiscal[^0-9]*)(\d{3,})/i)?.[1] || ref.match(/\b\d{5,}\b/)?.[0] || '';
      return {
        rowIndex: index,
        retificacaoId: id,
        notaId: id,
        dia01Id,
        href,
        onclick,
        filial: cells[1] || '',
        nroNf: cells[2] || '',
        dataNf: cells[3] || '',
        mercadoria: cells[4] || '',
        albaran: cells[7] || cells[6] || '',
        dataAlbaran: cells[8] || '',
        tipoOperacao: cells.at(-3) || '',
        situacaoInicial: statusCell?.innerText?.trim() || cells.at(-1) || '',
      };
    }).filter((row) => /PENDENTE|AGUARDANDO/.test(normalize(row.situacaoInicial)) && (row.href || row.onclick || row.retificacaoId || row.dia01Id));
  });
}

async function debugGridLinks(p) {
  return p.evaluate(() => {
    const table = document.querySelector('#dataTables') || document.querySelector('table');
    const rows = Array.from((table || document).querySelectorAll('tbody tr,.ui-jqgrid-btable tr'))
      .filter((row) => row.offsetParent && row.querySelectorAll('td').length >= 8)
      .slice(0, 25);
    return rows.map((row, index) => {
      const cells = Array.from(row.querySelectorAll('td'));
      const situation = cells.at(-1);
      const links = Array.from(situation?.querySelectorAll('a,button,[onclick]') || []).map((element) => ({
        tag: element.tagName,
        text: (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim(),
        href: element.getAttribute('href') || '',
        onclick: element.getAttribute('onclick') || '',
        cls: element.getAttribute('class') || '',
      }));
      return {
        index,
        filial: cells[1]?.innerText?.trim() || '',
        nf: cells[2]?.innerText?.trim() || '',
        mercadoria: cells[4]?.innerText?.trim() || '',
        situacaoText: situation?.innerText?.replace(/\s+/g, ' ').trim() || '',
        situacaoHtml: (situation?.innerHTML || '').replace(/\s+/g, ' ').trim().slice(0, 500),
        links,
      };
    });
  });
}

async function nextGridPage(p) {
  const before = await p.evaluate(() => Array.from(document.querySelectorAll('tbody tr,.ui-jqgrid-btable tr'))
    .filter((row) => row.offsetParent && row.querySelectorAll('td').length >= 8)
    .map((row) => Array.from(row.querySelectorAll('td')).map((cell) => cell.innerText.trim()).join('|')).join('\n'));
  const clicked = await p.evaluate(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const buttons = Array.from(document.querySelectorAll('a,button,span'))
      .filter(visible)
      .filter((element) => /Pr[oó]ximo/i.test(element.textContent || element.title || ''))
      .filter((element) => !/\bdisabled\b|ui-state-disabled/i.test(element.className || '') && !element.closest('.disabled,.ui-state-disabled'));
    const button = buttons.at(-1);
    if (!button) return false;
    button.click();
    return true;
  });
  if (!clicked) return false;
  await p.waitForFunction((previous) => Array.from(document.querySelectorAll('tbody tr,.ui-jqgrid-btable tr'))
    .filter((row) => row.offsetParent && row.querySelectorAll('td').length >= 8)
    .map((row) => Array.from(row.querySelectorAll('td')).map((cell) => cell.innerText.trim()).join('|')).join('\n') !== previous, before, { timeout: 15000 }).catch(() => {});
  await waitAriusIdle(p);
  return true;
}

async function processOne(p, item) {
  const notePage = await openNota(p, item);
  await waitNotaReady(notePage);
  console.log(`[Prevencao ${item.filial}] nota aberta em ${notePage.url()}`);
  if (await hasClosedNfeScreen(notePage)) return { status: 'concluido', message: 'Nota já estava emitida; FECHADA e DANFE confirmados', situacaoFinal: 'FECHADA' };
  const emissionDate = await readEmissionDate(notePage);
  if (emissionDate) return noActionEmissionFilledResult(emissionDate, 'emissão já preenchida antes de qualquer ação');
  const pendingCreation = /PENDENTE/i.test(item.situacaoInicial || '');
  let verified = false;
  if (pendingCreation) {
    const verify = notePage.getByRole('button', { name: /Verifica NF/i })
      .or(notePage.locator('button:has-text("Verifica NF"), a:has-text("Verifica NF"), input[value*="Verifica"]'))
      .first();
    if (await verify.isVisible().catch(() => false)) {
      if (await isControlDisabled(verify)) {
        const error = new Error('Sem acesso ao Verifica NF: botão Verifica NF desabilitado para esta nota.');
        error.stage = 'verificacao_nf';
        throw error;
      } else {
        console.log(`[Prevencao ${item.filial}] clicando Verifica NF.`);
        await clickAriusControl(notePage, verify, /Verifica\s*NF/i, 'Verifica NF');
        verified = true;
        await waitUsefulScreenAfterAction(notePage, Number(process.env.PREV_PERDAS_VERIFICA_TIMEOUT_MS || 180000));
        await waitForEmitButton(notePage, 90000);
      }
    } else {
      const error = new Error('Verifica NF não encontrado para nota PENDENTE CRIAÇÃO DE NF; não é permitido seguir sem verificar.');
      error.stage = 'verificacao_nf';
      throw error;
    }
  } else {
    console.log(`[Prevencao ${item.filial}] AGUARDANDO EMISSAO: seguindo direto para Emitir NF-e.`);
  }
  const emit = notePage.getByRole('button', { name: /Emitir NF-e|Emitir NFe|Emitir NF/i }).or(notePage.locator('button:has-text("Emitir"), a:has-text("Emitir"), input[value*="Emitir"]')).first();
  if (await emit.isVisible().catch(() => false)) {
    if (await isControlDisabled(emit)) {
      if (emissionDate) return noActionEmissionFilledResult(emissionDate, 'botão Emitir NF-e desabilitado');
      const error = new Error('Sem acesso ao Emitir NF-e: botão Emitir NF-e desabilitado para esta nota.');
      error.stage = 'emissao';
      throw error;
    }
    console.log(`[Prevencao ${item.filial}] clicando Emitir NF-e.`);
    await clickAriusControl(notePage, emit, /Emitir\s*NF/i, 'Emitir NF-e');
  } else {
    if (verified) {
      const error = new Error('Emitir NF-e não apareceu após concluir Verifica NF.');
      error.stage = 'emissao';
      throw error;
    }
    if (emissionDate) return noActionEmissionFilledResult(emissionDate, 'botão Emitir NF-e não encontrado');
    const error = new Error('Sem acesso ao Emitir NF-e: botão Emitir NF-e não encontrado na tela da nota.');
    error.stage = 'emissao';
    throw error;
  }
  const result = await waitEmissionResult(notePage);
  if (result.status === 'erro') {
    const error = new Error(result.message || 'Emissao retornou erro no Pleno.');
    error.stage = 'emissao';
    throw error;
  }
  if (notePage !== p && process.env.PREV_PERDAS_KEEP_NOTE_TABS !== '1') {
    await notePage.close().catch(() => {});
    await p.bringToFront().catch(() => {});
  }
  return result;
}

async function clickAriusControl(p, locator, pattern, label) {
  await locator.scrollIntoViewIfNeeded().catch(() => {});
  const clickedByLocator = await locator.click({ force: true, timeout: 10000 }).then(() => true).catch(() => false);
  if (clickedByLocator) return;
  const clickedByDom = await p.evaluate((source) => {
    const regex = new RegExp(source, 'i');
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const control = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .filter(visible)
      .find((element) => regex.test(`${element.textContent || ''} ${element.value || ''} ${element.title || ''}`));
    if (!control) return false;
    control.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
    control.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
    control.click();
    return true;
  }, pattern.source).catch(() => false);
  if (!clickedByDom) throw new Error(`Botão ${label} visível, mas o clique não foi executado.`);
}

async function waitForEmitButton(p, timeout) {
  await p.waitForFunction(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    return Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .some((element) => visible(element) && /Emitir\s*NF/i.test(`${element.textContent || ''} ${element.value || ''} ${element.title || ''}`));
  }, null, { timeout }).catch(() => {});
  await waitAriusIdle(p);
  await p.screenshot({ path: path.join(out, 'debug_apos_verifica_nf.png'), fullPage: true }).catch(() => {});
}

function noActionEmissionFilledResult(emissionDate, reason) {
  return {
    status: 'pendente_revalidacao_pleno',
    message: 'Data de emissão preenchida; autorização não confirmada. Revalidar no Pleno antes de emitir.',
    situacaoFinal: 'Autorização não confirmada',
  };
}

async function readEmissionDate(p) {
  const value = await p.evaluate(() => {
    const normalize = (text) => String(text || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').replace(/\s+/g, ' ').trim().toUpperCase();
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const labels = Array.from(document.querySelectorAll('label')).filter((label) => visible(label) && /^EMISSAO\*?$/.test(normalize(label.innerText || label.textContent)));
    const controls = Array.from(document.querySelectorAll('input,select,textarea')).filter(visible);
    for (const label of labels) {
      const labelRect = label.getBoundingClientRect();
      const explicit = label.getAttribute('for') ? document.getElementById(label.getAttribute('for')) : null;
      if (explicit && visible(explicit) && explicit.value) return explicit.value;
      const sameParent = Array.from(label.parentElement?.querySelectorAll('input,select,textarea') || []).find((control) => visible(control) && control.value);
      if (sameParent) return sameParent.value;
      const nearby = controls
        .map((control) => ({ control, rect: control.getBoundingClientRect() }))
        .filter(({ rect }) => rect.top >= labelRect.bottom - 6 && Math.abs(rect.left - labelRect.left) < 80 && rect.top - labelRect.bottom < 40)
        .sort((a, b) => (a.rect.top - labelRect.bottom) - (b.rect.top - labelRect.bottom))[0]?.control;
      if (nearby?.value) return nearby.value;
    }
    return '';
  }).catch(() => '');
  const trimmed = clean(value);
  return /\d{2}\/\d{2}\/\d{4}/.test(trimmed) ? trimmed : '';
}

async function isControlDisabled(locator) {
  return locator.evaluate((element) => {
    const control = element.closest('button,input,a') || element;
    return Boolean(
      control.disabled ||
      control.getAttribute('disabled') !== null ||
      control.getAttribute('aria-disabled') === 'true' ||
      window.getComputedStyle(control).pointerEvents === 'none' ||
      /\bdisabled\b|ui-state-disabled|btn-disabled/i.test(control.className || '') ||
      control.closest('.disabled,.ui-state-disabled')
    );
  }).catch(() => false);
}

async function openNota(p, item) {
  if (item.href) {
    const url = new URL(item.href, p.url()).toString();
    await gotoNota(p, url);
    return p;
  }
  if (item.retificacaoId) {
    const base = process.env.PREV_PERDAS_NOTA_URL_BASE || 'https://172.22.20.101/notafiscal-transf-saida/editar/id';
    await gotoNota(p, `${base}/${item.retificacaoId}`);
    return p;
  }
  if (item.dia01Id) {
    await openRetificacao(p);
    const openedPage = await clickPendingCreationLink(p, item.dia01Id);
    if (openedPage) return openedPage;
    const converted = await findConvertedNotaLink(p, item);
    if (converted?.href) {
      await gotoNota(p, new URL(converted.href, p.url()).toString());
      return p;
    }
    const error = new Error(`Link PENDENTE CRIAÇÃO DE NF não abriu a nota nem gerou link AGUARDANDO para data-dia01id=${item.dia01Id}.`);
    error.stage = 'abrir_nota';
    throw error;
  }
  await p.locator('tbody tr,.ui-jqgrid-btable tr').nth(item.rowIndex).locator('td:last-child a,td:last-child button,a[href*="notafiscal"],button').first().click();
  return p;
}

async function clickPendingCreationLink(p, dia01Id) {
  const link = p.locator(`a[data-dia01id="${dia01Id}"], button[data-dia01id="${dia01Id}"], [onclick][data-dia01id="${dia01Id}"]`).first();
  await link.waitFor({ state: 'visible', timeout: 30000 });
  await link.scrollIntoViewIfNeeded().catch(() => {});
  const popupPromise = p.context().waitForEvent('page', { timeout: 8000 }).catch(() => null);
  await link.click({ force: true }).catch(() => {});
  const popup = await popupPromise;
  if (popup) {
    await popup.bringToFront().catch(() => {});
    await popup.waitForLoadState('domcontentloaded', { timeout: 60000 }).catch(() => {});
    if (await waitForNotaUrlOrScreen(popup, 90000)) return popup;
    await popup.close().catch(() => {});
  }
  if (await waitForNotaUrlOrScreen(p, 90000)) return p;
  return null;
}

async function waitForNotaUrlOrScreen(p, timeout) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    await p.waitForTimeout(1000);
    await waitAriusIdle(p);
    if (/notafiscal-transf-saida\/editar\/id\/\d+/i.test(p.url())) return true;
    const text = await p.locator('body').innerText().catch(() => '');
    if (/Edi[cç][aã]o\s+NF\s+Transfer[eê]ncia\s+Sa[ií]da/i.test(text) && /Verifica\s*NF|Emitir\s*NF/i.test(text)) return true;
  }
  return false;
}

async function findConvertedNotaLink(p, item) {
  await openRetificacao(p);
  const rows = await collectGridRows(p);
  const targetKey = [item.filial, item.nroNf, item.albaran, item.mercadoria].map(normalizeText).join('|');
  return rows.find((row) => {
    if (!row.href) return false;
    const rowKey = [row.filial, row.nroNf, row.albaran, row.mercadoria].map(normalizeText).join('|');
    return rowKey === targetKey && /AGUARDANDO/i.test(row.situacaoInicial || '');
  });
}

async function gotoNota(p, url) {
  const timeout = Number(process.env.PREV_PERDAS_NOTA_NAV_TIMEOUT_MS || 15000);
  const commitTimeout = Number(process.env.PREV_PERDAS_NOTA_COMMIT_TIMEOUT_MS || 8000);
  try {
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout });
  } catch (error) {
    console.warn(`Abertura da nota demorou (${error.message}); tentando continuar com commit.`);
    await p.goto(url, { waitUntil: 'commit', timeout: commitTimeout });
  }
}

async function waitNotaReady(p) {
  await p.waitForTimeout(Number(process.env.PREV_PERDAS_NOTA_SETTLE_MS || 3000));
  await waitAriusIdle(p);
  await p.waitForFunction(() => {
    const normalize = (text) => String(text || '').normalize('NFD').replace(/\p{Diacritic}/gu, '').replace(/\s+/g, ' ').trim().toUpperCase();
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const hasActionButton = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .some((element) => visible(element) && /Verifica\s*NF|Emitir\s*NF/i.test(`${element.textContent || ''} ${element.value || ''} ${element.title || ''}`));
    const hasEmissionField = Array.from(document.querySelectorAll('label'))
      .some((element) => visible(element) && /^EMISSAO\*?$/.test(normalize(element.innerText || element.textContent)));
    return hasActionButton || hasEmissionField;
  }, null, { timeout: 90000 });
  await waitAriusIdle(p);
  await p.screenshot({ path: path.join(out, 'debug_nota_pronta.png'), fullPage: true }).catch(() => {});
}

async function waitEmissionResult(p) {
  const started = Date.now();
  let lastText = '';
  let lastHeartbeat = 0;
  while (Date.now() - started < Number(process.env.PREV_PERDAS_EMISSAO_TIMEOUT_MS || 60000)) {
    await p.waitForTimeout(2500);
    if (Date.now() - lastHeartbeat > 30000) {
      lastHeartbeat = Date.now();
      heartbeat('executando', 'Aguardando retorno SAP.');
    }
    lastText = clean(await p.locator('body').innerText().catch(() => ''));
    const alertText = await p.evaluate(() => Array.from(document.querySelectorAll('.alert,.alert-success,.alert-danger,.alert-error,.alert-warning,[class*=success],[class*=danger],[class*=error]')).map((el) => el.textContent || '').join(' ')).catch(() => '');
    const combined = clean(`${alertText} ${lastText}`);
    if (await hasClosedNfeScreen(p)) return { status: 'concluido', message: 'Nota emitida', situacaoFinal: 'FECHADA' };
    if (/processando\s+nf/i.test(combined)) continue;
    if (/verifica[cç][aã]o\s+conclu[ií]da\s+com\s+sucesso/i.test(combined) && await hasEmitButton(p)) continue;
    if (/aguardando\s+sap|retorno\s+sap/i.test(combined)) {
      return { status: 'pendente_reconsulta', message: 'Aguardando retorno SAP', situacaoFinal: 'Aguardando retorno SAP' };
    }
    if (/rejei|erro|falha|denegad|nao\s+autoriz|não\s+autoriz/i.test(combined)) {
      return { status: 'erro', message: summarizePlenoError(combined), situacaoFinal: extractSituation(combined) };
    }
    if (/autorizad|emitid|nfe\s+gerad|nf-e\s+gerad|fechada|danfe/i.test(combined)) return { status: 'concluido', message: 'Nota emitida', situacaoFinal: extractSituation(combined) || 'FECHADA' };
  }
  return {
    status: 'pendente_reconsulta',
    message: 'Aguardando retorno SAP',
    situacaoFinal: 'Aguardando retorno SAP',
  };
}

function summarizePlenoError(text) {
  const compact = clean(text);
  const errorMatch = compact.match(/(?:×\s*)?(Erro:\s*)?(Motivo\s+\d+:\s*[^×]+)/i);
  if (errorMatch?.[0]) return clean(errorMatch[0].replace(/^×\s*/u, '')).slice(0, 220);
  const sentenceMatch = compact.match(/(?:rejei\w*|erro|falha|denegad\w*|n[aã]o\s+autoriz\w*)[^.。!?]*(?:[.。!?]|$)/i);
  if (sentenceMatch?.[0]) return clean(sentenceMatch[0]).slice(0, 220);
  return compact.slice(0, 220);
}

async function hasEmitButton(p) {
  return p.evaluate(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    return Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .some((element) => visible(element) && /Emitir\s*NF/i.test(`${element.textContent || ''} ${element.value || ''} ${element.title || ''}`));
  }).catch(() => false);
}

async function hasClosedNfeScreen(p) {
  return p.evaluate(() => {
    const visible = (element) => {
      const style = window.getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
    };
    const controlsText = Array.from(document.querySelectorAll('button,input[type=button],input[type=submit],a'))
      .filter(visible)
      .map((element) => `${element.textContent || ''} ${element.value || ''} ${element.title || ''}`)
      .join(' ');
    const fieldsText = Array.from(document.querySelectorAll('input,select,textarea'))
      .filter(visible)
      .map((element) => `${element.value || ''} ${element.selectedOptions?.[0]?.textContent || ''}`)
      .join(' ');
    return /DANFE/i.test(controlsText) && /Cancelar\s+NF-e/i.test(controlsText) && /FECHADA/i.test(fieldsText);
  }).catch(() => false);
}

async function waitForMessage(p, pattern, timeout) {
  await p.waitForFunction((source) => new RegExp(source, 'i').test(document.body.innerText || ''), pattern.source, { timeout }).catch(() => {});
}

async function loginPleno(p, url) {
  const password = p.locator('#senha,#Senha,#password,input[name=senha],input[type=password]:visible').first();
  if (!await password.isVisible().catch(() => false)) return;
  if (!process.env.PLENO_USER || !process.env.PLENO_PASSWORD) throw new Error('Configure PLENO_USER e PLENO_PASSWORD no .env.');
  for (let attempt = 1; attempt <= 3; attempt++) {
    const username = p.locator('#usuario,#Usuario,#username,input[name=usuario],input[type=text]:visible').first();
    await fillValue(username, process.env.PLENO_USER);
    await fillValue(password, process.env.PLENO_PASSWORD);
    const login = p.locator('#btnEntrar,#btnLogin,button[type=submit],input[type=submit]').first();
    if (attempt === 2) await password.press('Enter');
    else await login.click().catch(() => password.press('Enter'));
    await p.waitForTimeout(5000);
    if (!await password.isVisible().catch(() => false)) {
      await gotoPleno(p, url);
      return;
    }
    await p.reload({ waitUntil: 'domcontentloaded' });
  }
  throw new Error('Login no Pleno nao foi concluido apos 3 tentativas.');
}

async function fillValue(locator, value) {
  await locator.click({ force: true });
  await locator.press(process.platform === 'darwin' ? 'Meta+A' : 'Control+A').catch(() => {});
  await locator.fill(String(value));
  await locator.dispatchEvent('change').catch(() => {});
}

function heartbeat(status, message = '') {
  fs.writeFileSync(runStatusFile, JSON.stringify({ status, message, currentFilial, currentNota, processed, completed, failed, pendingReview, updatedAt: new Date().toISOString() }));
}

function record(payload) {
  execFileSync('python3', [path.join(root, 'scripts', 'prevencao_perdas_status.py'), '--db', db, 'record'], { input: JSON.stringify(payload), encoding: 'utf8' });
}

function handledIds() {
  return new Set(JSON.parse(execFileSync('python3', [path.join(root, 'scripts', 'prevencao_perdas_status.py'), '--db', db, 'handled-ids', '--run-date', runDate], { encoding: 'utf8' })));
}

function handledNotaGroups() {
  const rows = JSON.parse(execFileSync('python3', [path.join(root, 'scripts', 'prevencao_perdas_status.py'), '--db', db, 'recent', '--limit', '5000'], { encoding: 'utf8' }));
  return new Set(rows.filter((row) => ['erro', 'concluido'].includes(row.status)).map((row) => notaGroupKey({
    filial: row.filial,
    nroNf: row.nro_nf,
    albaran: row.albaran,
    dataNf: row.data_nf,
  })));
}

function notaGroupKey(item) {
  return [item.filial || '', item.nroNf || '', item.albaran || '', item.dataNf || ''].map((value) => String(value).trim()).join('|');
}

function processKeyForItem(item) {
  if (item.retificacaoId || item.notaId) return undefined;
  return [item.dia01Id || '', notaGroupKey(item), item.mercadoria || '', item.tipoOperacao || ''].map((value) => String(value).trim()).join('|');
}

function loadDotEnv(file) {
  if (!fs.existsSync(file)) return;
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const match = line.trim().match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (match && process.env[match[1]] === undefined) process.env[match[1]] = match[2].trim().replace(/^(?:"|')|(?:"|')$/g, '');
  }
}

function today() { return new Date().toISOString().slice(0, 10); }
function todayBR() { const d = new Date(); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; }
function daysAgo(days) { const d = new Date(); d.setDate(d.getDate() - days); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; }
function safeName(value) { return String(value).replace(/[^A-Za-z0-9_.-]+/g, '_').slice(0, 80); }
function clean(value) { return String(value || '').replace(/\s+/g, ' ').trim(); }
function normalizeText(value) { return clean(value).normalize('NFD').replace(/\p{Diacritic}/gu, '').toUpperCase(); }
function extractSituation(text) { return text.match(/situa[cç][aã]o[^A-Za-z0-9]*(.{0,80})/i)?.[1]?.trim() || ''; }

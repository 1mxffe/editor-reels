// Teste de tela das telas Cortes, Legendas, Preview e Final contra o servidor REAL
// em modo de teste, com a transcricao falsa (REEL_APP_FAKE_TRANSCRIBE=1).
//
// Uso: node tests/js/app_flow_a.mjs <config.json>
// config: {tmp, video, screens, review_html, tempo_js}
// Imprime em stdout um JSON {cenario: observacoes | {error}}; quem afirma e o pytest.
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { iniciarServidor, api, esperar, require_ } from './helpers.mjs';

const { chromium } = require_('playwright');
const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
const DOCTOR_OK = {
  estado: 'READY',
  itens: [{ name: 'python >= 3.11', ok: true, required: true },
    { name: 'ffmpeg', ok: true, required: true }, { name: 'ffprobe', ok: true, required: true }],
};
const marca = JSON.parse(fs.readFileSync(path.resolve(path.dirname(cfg.review_html), '..', 'brand', 'brand.json'), 'utf-8'));
const brandPath = path.join(cfg.tmp, 'brand.json');
fs.writeFileSync(brandPath, JSON.stringify({ ...marca, handles: ['@gutmannesilva'] }));

const browser = await chromium.launch();
const out = {};
const srvs = [];
const visivel = {};

async function servidor(nome, env) {
  const s = await iniciarServidor({ root: path.join(cfg.tmp, nome, 'projects'), brand: brandPath,
    doctor: DOCTOR_OK, test_mode: true }, cfg.tmp, { REEL_APP_FAKE_TRANSCRIBE: '1', ...env });
  srvs.push(s);
  return s;
}

async function contexto(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...opts });
  ctx.setDefaultTimeout(15000);
  return ctx;
}

async function abrir(ctx, srv, ultimo) {
  const page = await ctx.newPage();
  const erros = [];
  page.on('pageerror', (e) => erros.push(String(e)));
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) erros.push(m.text());
  });
  if (ultimo) {
    await page.addInitScript((s) => {
      try { localStorage.setItem('editor-reels:ultimo-projeto', s); } catch { /* sem storage */ }
    }, ultimo);
  }
  await page.goto(srv.url);
  await page.waitForSelector('#painel[data-passo]');
  page.__erros = erros;
  return page;
}

async function novoProjeto(srv, nome) {
  const p = (await api(srv, 'POST', '/api/projects', { nome })).json;
  const r = await fetch(`${srv.base}/api/projects/${p.slug}/video`, {
    method: 'PUT', headers: { 'X-Token': srv.token, 'X-Filename': 'video.mp4' },
    body: fs.readFileSync(cfg.video),
  });
  if (r.status !== 200) throw new Error('envio falhou: ' + r.status);
  return p.slug;
}

const estados = (page) => page.$$eval('#passos .passo', (bs) => bs.map((b) => ({
  id: b.dataset.passo, estado: b.dataset.estado, bloqueado: b.getAttribute('aria-disabled') === 'true',
})));

const semRolagem = (page) => page.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
  bodyScroll: document.body.scrollWidth,
}));

const textoVisivel = (page) => page.evaluate(() => {
  const codes = [...document.querySelectorAll('code')];
  const antes = codes.map((c) => c.style.display);
  codes.forEach((c) => { c.style.display = 'none'; });
  const t = document.body.innerText;
  codes.forEach((c, i) => { c.style.display = antes[i]; });
  return t;
});

async function screenshot(page, nome) {
  if (!cfg.screens) return;
  fs.mkdirSync(cfg.screens, { recursive: true });
  await page.evaluate(() => document.fonts.ready.then(() => true));
  await page.screenshot({ path: path.join(cfg.screens, nome), fullPage: true });
}

async function cenario(nome, fn) {
  try {
    out[nome] = await fn();
  } catch (e) {
    // o texto do painel na hora da falha ajuda a entender o que a pessoa veria
    let painel = '';
    try { painel = page ? (await page.textContent('#painel', { timeout: 1000 })).replace(/\s+/g, ' ') : ''; } catch { /* sem pagina */ }
    out[nome] = { error: String(e && e.stack || e) + (painel ? `\n[painel] ${painel.slice(0, 1500)}` : '') };
  }
}

const revisao = async (srv, slug) => (await api(srv, 'GET', `/api/projects/${slug}/revisao`)).json;
const meio = (w) => (w.start + w.end) / 2;
const cobre = (c, t) => c.start <= t && t <= c.end;
const economia = (page) => page.textContent('#cortes-economia').then((t) => t.trim());

const srvR = await servidor('rapido', {});
const srvL = await servidor('lento', { REEL_APP_FAKE_TRANSCRIBE_ESPERA: '8' });

// ================================================== fluxo completo (um projeto)
const slug = await novoProjeto(srvR, 'Reel fluxo');
const ctxF = await contexto();
const tarefasPedidas = [];
ctxF.on('request', (rq) => {
  const m = rq.method() === 'POST' && rq.url().match(/\/api\/projects\/[^/]+\/jobs\/([a-z-]+)$/);
  if (m) tarefasPedidas.push(m[1]);
});
let page;

await cenario('cortes', async () => {
  page = await abrir(ctxF, srvR, slug);
  await page.waitForSelector('#painel[data-passo="cortes"] #cortes-reconhecer');
  const avisoModelo = (await page.textContent('#cortes-aviso-modelo')).trim();
  visivel['cortes-inicio'] = await textoVisivel(page);
  await page.click('#cortes-reconhecer');
  await page.waitForSelector('#cortes-lista .corte', { timeout: 60000 });
  await esperar(async () => !(await page.$('#tarefa-cancelar:visible')), 10000);
  const lista = await page.$$eval('#cortes-lista .corte', (lis) => lis.map((li) => ({
    id: li.dataset.id, ligado: li.querySelector('[role="switch"]').getAttribute('aria-checked'),
    texto: li.textContent.replace(/\s+/g, ' ').trim() })));
  const rev = await revisao(srvR, slug);
  const r = {
    avisoModelo, lista, tarefas: tarefasPedidas.slice(),
    cortesApi: rev.cuts, duracao: rev.duration, kept: rev.kept_duration,
    economia: await economia(page),
    estado: (await api(srvR, 'GET', `/api/projects/${slug}`)).json,
    playerOriginal: await page.$eval('#player-video', (v) => v.getAttribute('src') || ''),
    detalhes: await page.$eval('#painel details', (d) => ({
      resumo: d.querySelector('summary').textContent.trim(), aberto: d.open })).catch(() => null),
  };
  visivel.cortes = await textoVisivel(page);
  await screenshot(page, 'cortes-1280-claro.png');
  // desliga a pausa longa (c2); a linha e a do trecho 3,1-3,85 (ligar de novo cria outro id)
  const sw = '#cortes-lista .corte[data-faixa="3.1-3.85"] [role="switch"]';
  r.idAntes = await page.getAttribute('#cortes-lista .corte[data-faixa="3.1-3.85"]', 'data-id');
  await page.click(sw);
  await esperar(async () => (await page.getAttribute(sw, 'aria-checked')) === 'false');
  await esperar(async () => !(await page.$('#painel [data-ocupado]')));
  let rv = await revisao(srvR, slug);
  r.desligado = {
    ligado: await page.getAttribute(sw, 'aria-checked'),
    ativoNoServidor: rv.cuts.find((c) => c.id === 'c2').active,
    economia: await economia(page),
  };
  await page.click(sw);
  await esperar(async () => (await page.getAttribute(sw, 'aria-checked')) === 'true');
  await esperar(async () => !(await page.$('#painel [data-ocupado]')));
  rv = await revisao(srvR, slug);
  r.religado = {
    ligado: await page.getAttribute(sw, 'aria-checked'),
    texto: (await page.textContent('#cortes-lista .corte[data-faixa="3.1-3.85"]')).replace(/\s+/g, ' ').trim(),
    cobertoNoServidor: rv.cuts.some((c) => c.active && c.start <= 3.1 && c.end >= 3.85),
    economia: await economia(page),
  };
  r.erros = page.__erros.slice();
  return r;
});

await cenario('palavras', async () => {
  const rev = await revisao(srvR, slug);
  const ativos = () => rev.cuts.filter((c) => c.active);
  const leia = rev.words.find((w) => w.w === 'Leia');
  const ne = rev.words.find((w) => w.w === 'né');
  if (ativos().some((c) => cobre(c, meio(leia)))) throw new Error('"Leia" ja comeca cortada');
  const btn = `#cortes-palavras .palavra[data-i="${leia.i}"]`;
  const r = { antes: await page.getAttribute(btn, 'data-estado'), inicioPalavra: leia.start };
  await page.click(btn);
  await esperar(async () => (await page.getAttribute(btn, 'data-estado')) === 'cortada');
  await esperar(async () => !(await page.$('#painel [data-ocupado]')));
  r.cortada = await page.getAttribute(btn, 'data-estado');
  r.playerEm = await page.$eval('#player-video', (v) => v.currentTime);
  let rv = await revisao(srvR, slug);
  r.manualNoServidor = rv.cuts.some((c) => c.active && c.kind === 'manual' && cobre(c, meio(leia)));
  await page.click(btn);
  await esperar(async () => (await page.getAttribute(btn, 'data-estado')) === 'mantida');
  await esperar(async () => !(await page.$('#painel [data-ocupado]')));
  r.restaurada = await page.getAttribute(btn, 'data-estado');
  rv = await revisao(srvR, slug);
  r.manualDepois = rv.cuts.some((c) => c.active && cobre(c, meio(leia)));
  const bne = `#cortes-palavras .palavra[data-i="${ne.i}"]`;
  r.muletaAntes = await page.getAttribute(bne, 'data-estado');
  await page.click(bne);
  await esperar(async () => (await page.getAttribute(bne, 'data-estado')) === 'mantida');
  await esperar(async () => !(await page.$('#painel [data-ocupado]')));
  r.muletaDepois = await page.getAttribute(bne, 'data-estado');
  rv = await revisao(srvR, slug);
  r.muletaAtivaNoServidor = rv.cuts.some((c) => c.active && cobre(c, meio(ne)));
  // volta a muleta para o fluxo seguir com os 3 cortes
  await page.click(bne);
  await esperar(async () => (await page.getAttribute(bne, 'data-estado')) === 'cortada');
  await esperar(async () => !(await page.$('#painel [data-ocupado]')));
  r.erros = page.__erros.slice();
  return r;
});

await cenario('paridade', async () => {
  const tempo = await import(pathToFileURL(cfg.tempo_js).href);
  const conjuntos = [
    [],
    [{ start: 1.7, end: 1.95 }, { start: 3.1, end: 3.85 }, { start: 4.3, end: 4.4 }],
    [{ start: 3, end: 4 }, { start: 1, end: 2 }],            // fora de ordem
    [{ start: 1, end: 3 }, { start: 2, end: 4 }],            // sobrepostos
    [{ start: 0, end: 0.5 }, { start: 0.5, end: 1 }],        // encostados, desde o zero
    [{ start: 2, end: 2 }, { start: 5, end: 4 }],            // vazios / invertidos
    [{ start: '1', end: '2.5' }],                            // numeros como texto
  ];
  const pontos = [];
  for (let i = 0; i < conjuntos.length; i++) {
    for (const t of [-1, 0, 0.25, 0.5, 0.99, 1, 1.5, 1.7, 1.8, 1.95, 2, 2.75, 3, 3.5, 3.85, 4, 4.35, 5, 6, 9.5]) {
      pontos.push({ i, t });
    }
  }
  const pg = await browser.newPage();
  await pg.goto(pathToFileURL(cfg.review_html).href);
  await pg.waitForFunction(() => !!window.ReviewApp);
  const review = await pg.evaluate(({ pontos, conjuntos }) => pontos.map(({ i, t }) => ({
    o2c: window.ReviewApp.originalToCutTime(t, conjuntos[i]),
    c2o: window.ReviewApp.cutToOriginalTime(t, conjuntos[i]),
  })), { pontos, conjuntos });
  const mergeReview = await pg.evaluate((cs) => cs.map((c) => window.ReviewApp.mergeCuts(c)), conjuntos);
  await pg.close();
  const novo = pontos.map(({ i, t }) => ({
    o2c: tempo.originalToCutTime(t, conjuntos[i]), c2o: tempo.cutToOriginalTime(t, conjuntos[i]) }));
  const mergeNovo = conjuntos.map((c) => tempo.mergeCuts(c));
  return { pontos, review, novo, mergeIgual: JSON.stringify(mergeReview) === JSON.stringify(mergeNovo) };
});

await cenario('legendas', async () => {
  const previewBloqueadoAntes = (await estados(page)).find((p) => p.id === 'preview').bloqueado;
  await page.click('#passos .passo[data-passo="legendas"]');
  await page.waitForSelector('#lista-frases .frase textarea');
  const frases = await page.locator('#lista-frases .frase').count();
  const base0 = (await revisao(srvR, slug)).phrases[0].base_text;
  const ta0 = '#lista-frases .frase[data-idx="0"] textarea';
  await page.fill(ta0, 'O prazo para recorrer é curto');
  await page.press(ta0, 'Tab');
  await esperar(async () => (await page.textContent('#lista-frases .frase[data-idx="0"] .frase-tag')).trim() === 'Editada');
  const tagEditada = (await page.textContent('#lista-frases .frase[data-idx="0"] .frase-tag')).trim();
  const ultima = frases - 1;
  const taU = `#lista-frases .frase[data-idx="${ultima}"] textarea`;
  const erroU = `#lista-frases .frase[data-idx="${ultima}"] .frase-erro`;
  await page.fill(taU, 'linha um\nlinha dois\nlinha três');
  await page.press(taU, 'Tab');
  await page.waitForSelector(`${erroU}:not([hidden])`);
  const erroLinhas = (await page.textContent(erroU)).trim();
  await page.fill(taU, 'texto {ruim}');
  await page.press(taU, 'Tab');
  await esperar(async () => (await page.textContent(erroU)).includes('chaves'));
  const erroChaves = (await page.textContent(erroU)).trim();
  const textoAposErro = await page.inputValue(taU);
  const legendasJson = JSON.parse(fs.readFileSync(path.join(srvR.root, slug, 'legendas.json'), 'utf-8'));
  visivel.legendas = await textoVisivel(page);
  await screenshot(page, 'legendas-1280-claro.png');
  // desfaz o texto ruim (volta ao automatico) e confirma
  await page.fill(taU, '');
  await page.press(taU, 'Tab');
  await esperar(async () => (await page.$eval(erroU, (e) => e.hidden)));
  await page.click('#legendas-confirmar');
  await page.waitForSelector('#painel[data-passo="preview"]');
  const st = (await api(srvR, 'GET', `/api/projects/${slug}`)).json;
  await esperar(async () => (await estados(page)).find((p) => p.id === 'legendas').estado === 'pronto');
  return {
    frases, base0, previewBloqueadoAntes, tagEditada, erroLinhas, erroChaves, textoAposErro, legendasJson,
    confirmado: st.legendas_confirmadas, passoApos: await page.getAttribute('#painel', 'data-passo'),
    passosApos: await estados(page), erros: page.__erros.slice(),
  };
});

await cenario('preview', async () => {
  const antes = tarefasPedidas.length;
  await page.waitForSelector('#preview-gerar');
  visivel['preview-inicio'] = await textoVisivel(page);
  await page.click('#preview-gerar');
  await page.waitForSelector('#preview-pronto', { timeout: 180000 });
  await esperar(async () => (await page.$eval('#player-video', (v) => v.getAttribute('src') || '')).includes('preview.mp4'));
  const src = await page.$eval('#player-video', (v) => v.getAttribute('src'));
  const rotuloPlayer = (await page.textContent('#player-legenda')).trim();
  await page.click('#nota-adicionar');
  await page.waitForSelector('#lista-notas .nota textarea');
  await page.fill('#lista-notas .nota textarea', 'Trocar o começo');
  await page.press('#lista-notas .nota textarea', 'Tab');
  await esperar(async () => ((await revisao(srvR, slug)).notes || []).length === 1);
  const notas = (await revisao(srvR, slug)).notes;
  const tempoNota = (await page.textContent('#lista-notas .nota .nota-tempo')).trim();
  visivel.preview = await textoVisivel(page);
  await screenshot(page, 'preview-1280-claro.png');
  return {
    tarefas: tarefasPedidas.slice(antes), root: srvR.root, slug, src, rotuloPlayer, notas, tempoNota,
    finalLiberado: !(await estados(page)).find((p) => p.id === 'final').bloqueado,
    erros: page.__erros.slice(),
  };
});

await cenario('final', async () => {
  await page.click('#passos .passo[data-passo="final"]');
  await page.waitForSelector('#final-gerar');
  visivel['final-inicio'] = await textoVisivel(page);
  await page.click('#final-gerar');
  await page.waitForSelector('#final-arquivos li', { timeout: 240000 });
  await esperar(async () => (await page.$eval('#player-video', (v) => v.getAttribute('src') || '')).includes('final.mp4'));
  const arquivos = await page.$$eval('#final-arquivos li', (lis) => lis.map((li) => {
    const a = li.querySelector('a');
    return { texto: li.textContent.replace(/\s+/g, ' ').trim(), href: a ? a.getAttribute('href') : '',
      download: a ? a.hasAttribute('download') : false };
  }));
  await page.click('#final-abrir-pasta');
  await page.waitForSelector('#toasts .toast');
  const toast = (await page.locator('#toasts .toast').allTextContents()).join(' | ');
  visivel.final = await textoVisivel(page);
  await screenshot(page, 'final-1280-claro.png');
  return {
    root: srvR.root, slug, arquivos, toast,
    src: await page.$eval('#player-video', (v) => v.getAttribute('src')),
    estado: (await api(srvR, 'GET', `/api/projects/${slug}`)).json,
    erros: page.__erros.slice(),
  };
});
await ctxF.close();

// ================================================== cancelar (tarefa lenta)
await cenario('cancelar', async () => {
  const s = await novoProjeto(srvL, 'Reel cancelar');
  const ctx = await contexto();
  const pg = await abrir(ctx, srvL, s);
  await pg.waitForSelector('#cortes-reconhecer');
  await pg.click('#cortes-reconhecer');
  await pg.waitForSelector('#tarefa-cancelar:visible');
  await esperar(async () => (await pg.textContent('#tarefa')).includes('Reconhecendo'));
  const rodando = (await pg.textContent('#tarefa')).replace(/\s+/g, ' ');
  visivel['cortes-rodando'] = await textoVisivel(pg);
  await screenshot(pg, 'cortes-rodando-1280-claro.png');
  const botaoCancelar = await pg.locator('#tarefa-cancelar:visible').count();
  await pg.click('#tarefa-cancelar');
  await esperar(async () => /Cancelado/.test(await pg.textContent('#painel')), 15000);
  await pg.waitForSelector('#cortes-reconhecer');
  const jobs = (await api(srvL, 'GET', `/api/projects/${s}/jobs`)).json;
  const r = {
    rodando, botaoCancelar, depois: (await pg.textContent('#painel')).replace(/\s+/g, ' '),
    job: jobs.recentes[0], transcricao: fs.existsSync(path.join(srvL.root, s, 'transcricao.json')),
    botaoDeNovo: await pg.locator('#cortes-reconhecer:visible').count(),
    erros: pg.__erros,
  };
  visivel['cortes-cancelado'] = await textoVisivel(pg);
  await ctx.close();
  return r;
});

// ================================================== recarregar (F5) com tarefa rodando
await cenario('recarregar', async () => {
  const s = await novoProjeto(srvL, 'Reel recarregar');
  const ctx = await contexto();
  const pg = await abrir(ctx, srvL, s);
  await pg.waitForSelector('#cortes-reconhecer');
  await pg.click('#cortes-reconhecer');
  await pg.waitForSelector('#tarefa-cancelar:visible');
  const antes = (await pg.textContent('#tarefa')).replace(/\s+/g, ' ');
  const id1 = (await api(srvL, 'GET', `/api/projects/${s}/jobs`)).json.ativo.id;
  await pg.reload();
  await pg.waitForSelector('#painel[data-passo="cortes"]');
  await pg.waitForSelector('#tarefa-cancelar:visible');
  const depoisF5 = (await pg.textContent('#tarefa')).replace(/\s+/g, ' ');
  const cancelarDepoisF5 = await pg.locator('#tarefa-cancelar:visible').count();
  const ativo = (await api(srvL, 'GET', `/api/projects/${s}/jobs`)).json.ativo;
  await pg.waitForSelector('#cortes-lista .corte', { timeout: 60000 });
  const r = {
    antes, depoisF5, cancelarDepoisF5, mesmoJob: !!ativo && ativo.id === id1,
    cortesNoFim: await pg.locator('#cortes-lista .corte').count(), erros: pg.__erros,
  };
  await ctx.close();
  return r;
});


// ================================================== 375 px
await cenario('scroll375', async () => {
  const ctx = await contexto({ viewport: { width: 375, height: 800 } });
  const pg = await abrir(ctx, srvR, slug);
  const medidas = {};
  const alvos = [];
  for (const tela of ['cortes', 'legendas', 'preview', 'final']) {
    await pg.click(`#passos .passo[data-passo="${tela}"]`);
    await pg.waitForSelector(`#painel[data-passo="${tela}"]`);
    const pronto = { cortes: '#cortes-lista .corte', legendas: '#lista-frases .frase',
      preview: '#preview-pronto', final: '#final-arquivos li' }[tela];
    await pg.waitForSelector(pronto);
    await esperar(async () => !(await pg.$('#painel [data-ocupado]')));
    medidas[tela] = await semRolagem(pg);
    alvos.push(...await pg.$$eval('#painel button, #painel input, #painel textarea, #painel a.botao, #painel [role="button"]',
      (els, t) => els.filter((e) => e.offsetParent !== null && e.type !== 'file').map((e) => {
        const b = e.getBoundingClientRect();
        return { tela: t, id: e.id || e.className, w: b.width, h: b.height };
      }), tela));
    await screenshot(pg, `${tela}-375-claro.png`);
  }
  const r = { medidas, alvos, erros: pg.__erros };
  await ctx.close();
  return r;
});

// ================================================== mudar cortes depois de gerar
await cenario('desatualizado', async () => {
  const st0 = (await api(srvR, 'GET', `/api/projects/${slug}`)).json;
  if (st0.final_desatualizado || st0.preview_desatualizado) throw new Error('ja comecou desatualizado');
  const put = await api(srvR, 'PUT', `/api/projects/${slug}/revisao`, { cuts_added: [{ start: 0.6, end: 1.0 }] });
  if (put.status !== 200) throw new Error('PUT falhou ' + put.status);
  const estado = (await api(srvR, 'GET', `/api/projects/${slug}`)).json;
  const ctx = await contexto();
  const pg = await abrir(ctx, srvR, slug);
  await pg.click('#passos .passo[data-passo="legendas"]');
  await pg.waitForSelector('#aviso-desatualizado');
  const avisoLegendas = (await pg.textContent('#aviso-desatualizado')).trim();
  await pg.click('#legendas-confirmar');
  await pg.waitForSelector('#painel[data-passo="preview"] #aviso-desatualizado');
  await esperar(async () => (await estados(pg)).find((p) => p.id === 'legendas').estado === 'pronto');
  await screenshot(pg, 'preview-desatualizado-1280-claro.png');
  const r = {
    estado, avisoLegendas, passos: await estados(pg),
    depoisConfirmar: (await api(srvR, 'GET', `/api/projects/${slug}`)).json.legendas_desatualizado,
    avisoPreview: (await pg.textContent('#aviso-desatualizado')).trim(),
    botaoPreview: (await pg.textContent('#preview-gerar')).trim(),
    classeBotaoPreview: await pg.getAttribute('#preview-gerar', 'class'),
    irParaFinal: await pg.locator('#painel button:has-text("Ir para Final")').count(),
    erros: pg.__erros,
  };
  visivel['preview-desatualizado'] = await textoVisivel(pg);
  await ctx.close();
  return r;
});

// ================================================== ultima palavra passa do fim
await cenario('ultimaPalavra', async () => {
  const s = await novoProjeto(srvR, 'Reel ultima');
  const d = path.join(srvR.root, s);
  const dur = 6.0;
  fs.writeFileSync(path.join(d, 'transcricao.json'), JSON.stringify({ duration: dur, words: [
    { w: 'Prazo', start: 0.5, end: 1.0 }, { w: 'curto', start: 1.0, end: 1.6 },
    { w: 'Leia', start: 2.0, end: 2.5 }, { w: 'tudo', start: 5.8, end: 6.03 }] }));
  const j = (await api(srvR, 'POST', `/api/projects/${s}/jobs/cortes`, {})).json.job_id;
  await esperar(async () => (await api(srvR, 'GET', `/api/jobs/${j}`)).json.estado !== 'rodando', 30000);
  const ctx = await contexto();
  const pg = await abrir(ctx, srvR, s);
  await pg.click('#passos .passo[data-passo="cortes"]');
  await pg.waitForSelector('#cortes-palavras .palavra[data-i="3"]');
  await pg.click('#cortes-palavras .palavra[data-i="3"]');
  await esperar(async () => (await pg.getAttribute('#cortes-palavras .palavra[data-i="3"]', 'data-estado')) === 'cortada'
    || !(await pg.$eval('#cortes-erro', (e) => e.hidden)));
  await esperar(async () => !(await pg.$('#painel [data-ocupado]')));
  const rv = await revisao(srvR, s);
  const corte = rv.cuts.find((c) => c.active && c.kind === 'manual') || {};
  const r = {
    estado: await pg.getAttribute('#cortes-palavras .palavra[data-i="3"]', 'data-estado'),
    erro: await pg.$eval('#cortes-erro', (e) => (e.hidden ? '' : e.textContent)), corte, duracao: rv.duration,
  };
  // confirmar com uma gravacao lenta em curso: espera e mostra o erro tardio
  await pg.click('#passos .passo[data-passo="legendas"]');
  await pg.waitForSelector('#lista-frases .frase textarea');
  await pg.route('**/revisao', async (route) => {
    if (route.request().method() === 'PUT') await new Promise((ok) => setTimeout(ok, 1500));
    await route.continue();
  });
  await pg.fill('#lista-frases .frase[data-idx="0"] textarea', 'texto {x}');
  await pg.click('#legendas-confirmar');
  await pg.waitForSelector('#lista-frases .frase[data-idx="0"] .frase-erro:not([hidden])', { timeout: 10000 });
  await esperar(async () => !(await pg.$eval('#legendas-confirmar', (b) => b.disabled)), 10000);
  out.confirmarEspera = {
    painel: await pg.getAttribute('#painel', 'data-passo'),
    erro: (await pg.textContent('#lista-frases .frase[data-idx="0"] .frase-erro')).trim(),
    confirmado: (await api(srvR, 'GET', `/api/projects/${s}`)).json.legendas_confirmadas,
    erros: pg.__erros,
  };
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== traducao de mensagens
await cenario('mensagens', async () => {
  const m = await import(pathToFileURL(path.resolve(path.dirname(cfg.tempo_js), 'mensagens.js')).href);
  const brutos = [
    'Ffprobe falhou (codigo 1): [mov,mp4 @ 0x55fe] moov atom not found.',
    'legenda da frase 1: sem barra invertida (\\) nem chaves ({ }); a legenda nao desenha esses caracteres',
    'legenda da frase 0: no maximo 2 linhas',
    "frase 0: o texto automatico mudou desde a revisao (era 'x', agora 'y'); recarregue a pagina e edite de novo",
    'corte novo fora do intervalo: 5.9-6.02 (precisa 0 <= start < end <= 6.0)',
    'arquivo ausente: <projeto>/transcricao.json',
    'transcreva o vídeo primeiro',
    'já existe uma tarefa rodando neste projeto',
    'a revisão excedeu o tempo limite',
    'o arquivo não parece ser um vídeo',
    'ainda não há arquivos prontos neste Reel',
    'Erro estranho: /usr/lib/x.py linha 3',
  ];
  return { pares: brutos.map((b) => [b, m.traduzir(b)]), generica: m.GENERICA };
});

out.visivel = { telas: visivel };
await browser.close();
for (const s of srvs) s.parar();
process.stdout.write(JSON.stringify(out));

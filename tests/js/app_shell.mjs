// Teste de tela da casca do app (app/web) contra o servidor REAL.
//
// Uso: node tests/js/app_shell.mjs <config.json>
// config: {tmp, brand_ok, brand_falta, video, lixo, grande, max_upload, screens}
// Imprime em stdout um JSON {cenario: observacoes | {error}}; quem afirma e o pytest.
import fs from 'node:fs';
import path from 'node:path';
import { iniciarServidor, api, esperar, require_ } from './helpers.mjs';

const { chromium } = require_('playwright');
const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
const XSS = '<img src=x onerror="window.__xss=1">';
const PASSOS = ['video', 'cortes', 'legendas', 'estilo', 'preview', 'graficos', 'capa', 'final'];

const DOCTOR_OK = {
  estado: 'READY WITH LIMITS',
  itens: [
    { name: 'python >= 3.11', ok: true, required: true },
    { name: 'ffmpeg', ok: true, required: true },
    { name: 'ffprobe', ok: true, required: true },
    { name: 'chromium + playwright (opcional: graficos)', ok: false, required: false,
      detail: 'Chromium do Playwright ausente' },
  ],
};
const DOCTOR_FALTA = {
  estado: 'NOT READY',
  itens: [
    { name: 'python >= 3.11', ok: true, required: true },
    { name: 'ffmpeg', ok: false, required: true, detail: 'ffmpeg não encontrado no PATH' },
    { name: 'disco livre >= 10 GB', ok: true, required: true },
    { name: 'faster_whisper (opcional)', ok: false, required: false, detail: 'módulo faster_whisper ausente' },
    { name: 'Pillow (opcional: capa)', ok: false, required: false, detail: 'pip install -r requirements.txt' },
    { name: 'node (opcional: cards e capa)', ok: false, required: false },
    { name: 'chromium + playwright (opcional: graficos)', ok: false, required: false,
      detail: 'Chromium do Playwright ausente (npx playwright install chromium)' },
  ],
};

const browser = await chromium.launch();
const out = {};
const srvs = [];

async function servidor(nome, extra) {
  const s = await iniciarServidor({ root: path.join(cfg.tmp, nome, 'projects'), ...extra }, cfg.tmp);
  srvs.push(s);
  return s;
}

async function contexto(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...opts });
  ctx.setDefaultTimeout(10000);
  return ctx;
}

async function abrir(ctx, srv, ultimo) {
  const page = await ctx.newPage();
  const erros = [];
  page.on('pageerror', (e) => erros.push(String(e)));
  // "Failed to load resource" e o navegador registrando os erros HTTP provocados de proposito
  page.on('console', (m) => {
    if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) erros.push(m.text());
  });
  if (ultimo) {
    await page.addInitScript((s) => {
      try { localStorage.setItem('editor-reels:ultimo-projeto', s); } catch { /* sem storage */ }
    }, ultimo);
  }
  const resp = await page.goto(srv.url);
  await page.waitForSelector('#painel[data-passo]');
  page.__erros = erros;
  page.__resp = resp;
  return page;
}

const estados = (page) => page.$$eval('#passos .passo', (bs) => bs.map((b) => ({
  id: b.dataset.passo, estado: b.dataset.estado, bloqueado: b.getAttribute('aria-disabled') === 'true',
  texto: b.textContent.trim(),
})));

const semRolagem = (page) => page.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
  bodyScroll: document.body.scrollWidth,
}));

// Texto que a pessoa le na tela: innerText (so o renderizado; <details> fechado fica
// de fora) sem os comandos copiaveis (<code>), que sao tecnicos de proposito.
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

async function enviar(page, arquivo) {
  await page.setInputFiles('#arquivo-video', arquivo);
}

async function cenario(nome, fn) {
  try {
    out[nome] = await fn();
  } catch (e) {
    out[nome] = { error: String(e && e.stack || e) };
  }
}

const srvA = await servidor('a', { brand: cfg.brand_ok, max_upload: cfg.max_upload, doctor: DOCTOR_OK });
const srvB = await servidor('b', { brand: cfg.brand_falta, doctor: DOCTOR_FALTA });

// ---------------------------------------------------------------- casca
await cenario('shell', async () => {
  const ctx = await contexto();
  const page = await abrir(ctx, srvA);
  const player = await page.locator('#coluna-player').boundingBox();
  const painel = await page.locator('#painel').boundingBox();
  const passos = await estados(page);
  const controles = await page.$$eval('#coluna-player button', (bs) => bs.map((b) => ({
    id: b.id, texto: b.textContent.trim(), rotulo: b.getAttribute('aria-label') || '',
  })));
  const tempo = await page.textContent('#player-tempo');
  const r = {
    player, painel, passos, controles, tempo: tempo.trim(),
    telaInicial: await page.getAttribute('#painel', 'data-passo'),
    instalacaoBotao: await page.locator('#btn-instalacao').count(),
    csp: page.__resp.headers()['content-security-policy'] || '',
    nativos: await page.$eval('#player-video', (v) => v.controls),
    erros: page.__erros,
  };
  await screenshot(page, 'shell-1280-claro.png');
  await ctx.close();
  return r;
});

// ------------------------------------------- passos bloqueados e voltar
await cenario('locked', async () => {
  const ctx = await contexto();
  const page = await abrir(ctx, srvA);
  await page.click('#passos .passo[data-passo="video"]');
  await page.fill('#novo-nome', 'Reel bloqueio');
  await page.click('#novo-criar');
  await page.waitForSelector('#arquivo-video', { state: 'attached' });
  const antes = await estados(page);
  await page.click('#passos .passo[data-passo="legendas"]', { force: true });
  await page.waitForSelector('#toasts .toast');
  const painelAposBloqueado = await page.getAttribute('#painel', 'data-passo');
  const toast = (await page.locator('#toasts .toast').allTextContents()).join(' | ');
  await enviar(page, cfg.video);
  await page.waitForSelector('#video-info', { timeout: 20000 });
  await esperar(async () => (await estados(page))[0].estado === 'pronto');
  const depoisVideo = await estados(page);
  const slug = (await api(srvA, 'GET', '/api/projects')).json.find((p) => p.nome === 'Reel bloqueio').slug;
  fs.writeFileSync(path.join(srvA.root, slug, 'cortes.json'), JSON.stringify({ cuts: [] }));
  await page.click('#passos .passo[data-passo="cortes"]');
  await page.waitForSelector('#painel[data-passo="cortes"]');
  await esperar(async () => (await estados(page))[1].estado === 'pronto');
  const depoisCortes = await estados(page);
  const textoCortes = (await page.textContent('#painel')).trim();
  await page.click('#passos .passo[data-passo="video"]');
  await page.waitForSelector('#painel[data-passo="video"] #video-info');
  const voltou = (await page.textContent('#video-info')).trim();
  // a chave fica na barra de endereco: F5 continua funcionando
  const busca = await page.evaluate(() => window.location.search);
  await page.reload();
  await page.waitForSelector('#painel[data-passo]');
  await esperar(async () => (await page.textContent('#projeto-atual')).includes('Reel bloqueio'));
  const fatalAposF5 = await page.$eval('#fatal', (f) => !f.hidden);
  const r = {
    antes, painelAposBloqueado, toast, busca, fatalAposF5, depoisVideo, depoisCortes, textoCortes, voltou,
    aposRecarregar: (await page.textContent('#projeto-atual')).trim(),
    storage: await page.evaluate(() => Object.keys(localStorage)),
    erros: page.__erros,
  };
  await ctx.close();
  return r;
});

// ------------------------------------------------------------ instalacao
await cenario('install', async () => {
  const ctx = await contexto({ permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await abrir(ctx, srvB);
  const telaInicial = await page.getAttribute('#painel', 'data-passo');
  await page.waitForSelector('#lista-itens .item');
  const itens = await page.$$eval('#lista-itens .item', (els) => els.map((e) => ({
    id: e.dataset.id, ok: e.dataset.ok, texto: e.textContent.replace(/\s+/g, ' ').trim(),
    comando: (e.querySelector('.item-comando code') || {}).textContent || null,
    copiar: !!e.querySelector('button.copiar'),
  })));
  const resumo = (await page.textContent('#instalacao-resumo')).trim();
  await page.click('#lista-itens .item[data-id="ffmpeg"] button.copiar');
  await esperar(async () => (await page.textContent('#lista-itens .item[data-id="ffmpeg"] button.copiar')).includes('Copiado'), 3000);
  const copiado = await page.evaluate(() => navigator.clipboard.readText());
  const botaoCopiar = (await page.textContent('#lista-itens .item[data-id="ffmpeg"] button.copiar')).trim();
  const chromiumSemProjeto = await page.locator('#instalar-chromium').count();
  const dicaSemProjeto = await page.locator('#lista-itens .item[data-id="graficos"]').innerText();
  const visivelInstalacao = await textoVisivel(page);
  const detalhes = await page.$$eval('#lista-itens details', (ds) => ds.map((d) => ({
    resumo: d.querySelector('summary').textContent.trim(), aberto: d.open, texto: d.textContent })));
  const comandoChromium = await page.locator('#lista-itens .item[data-id="graficos"] .item-comando code').count();
  // @ invalido: mensagem do servidor por extenso
  await page.fill('#handle-campo', '@@ruim!');
  await page.click('#handle-salvar');
  await page.waitForSelector('#handle-erro:not([hidden])');
  const erroHandle = (await page.textContent('#handle-erro')).trim();
  await page.fill('#handle-campo', '@gutmannesilva');
  await page.click('#handle-salvar');
  await page.waitForSelector('#handle-salvo');
  const salvo = (await page.textContent('#handle-salvo')).trim();
  const brand = (await api(srvB, 'GET', '/api/brand')).json;
  // com projeto aberto aparece o botao de instalar
  const proj = (await api(srvB, 'POST', '/api/projects', { nome: 'Com projeto' })).json;
  const page2 = await abrir(ctx, srvB, proj.slug);
  await page2.click('#btn-instalacao');
  await page2.waitForSelector('#lista-itens .item');
  const chromiumComProjeto = await page2.locator('#instalar-chromium').count();
  const textoBotao = chromiumComProjeto ? (await page2.textContent('#instalar-chromium')).trim() : '';
  const visivelInstalacaoProjeto = await textoVisivel(page2);
  await page2.click('#passos .passo[data-passo="video"]');
  await page2.waitForSelector('#arquivo-video', { state: 'attached' });
  const visivelVideo = await textoVisivel(page2);
  await screenshot(page2, 'instalacao-1280-claro.png');
  const r = {
    telaInicial, itens, resumo, copiado, botaoCopiar, chromiumSemProjeto, comandoChromium,
    erroHandle, salvo, brand, chromiumComProjeto, textoBotao, dicaSemProjeto, detalhes,
    visivel: { instalacao: visivelInstalacao, instalacaoProjeto: visivelInstalacaoProjeto, video: visivelVideo },
    textoTela: (await page.textContent('body')).replace(/\s+/g, ' '),
    erros: [...page.__erros, ...page2.__erros],
  };
  await ctx.close();
  return r;
});

// ----------------------------------------------------- envio do video
await cenario('upload', async () => {
  const proj = (await api(srvA, 'POST', '/api/projects', { nome: 'Reel envio' })).json;
  const ctx = await contexto();
  const page = await abrir(ctx, srvA, proj.slug);
  await page.click('#passos .passo[data-passo="video"]');
  await page.waitForSelector('#arquivo-video', { state: 'attached' });
  const puts = [];
  page.on('request', (rq) => { if (rq.method() === 'PUT') puts.push(rq.url()); });

  // 1) acima do limite: recusado no cliente, sem requisicao
  await enviar(page, cfg.grande);
  await page.waitForSelector('#video-erro:not([hidden])');
  const erroGrande = (await page.textContent('#video-erro')).trim();
  const putsGrande = puts.length;

  // 2) erro do servidor por extenso
  await enviar(page, cfg.lixo);
  await esperar(async () => (await page.textContent('#video-erro')).includes('vídeo')
    && !(await page.textContent('#video-erro')).includes('limite'), 15000);
  const erroServidor = (await page.textContent('#video-erro')).trim();

  // 3) falha de rede
  await page.route('**/video', (route) => route.abort('connectionreset'));
  await enviar(page, cfg.video);
  await esperar(async () => (await page.textContent('#video-erro')).includes('conexão'), 15000);
  const erroRede = (await page.textContent('#video-erro')).trim();
  await page.unroute('**/video');

  // 4) envio lento: progresso intermediario, depois cancelar
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions',
    { offline: false, latency: 20, downloadThroughput: -1, uploadThroughput: 120 * 1024 });
  await page.evaluate(() => {
    window.__progresso = [];
    const bar = document.querySelector('#envio-barra');
    window.__amostra = setInterval(() => {
      const b = document.querySelector('#envio-barra');
      if (b && !b.closest('[hidden]')) window.__progresso.push(Number(b.value));
    }, 30);
    return !!bar;
  });
  await enviar(page, cfg.video);
  await page.waitForSelector('#envio:not([hidden])');
  await esperar(async () => (await page.evaluate(() => window.__progresso.some((v) => v > 0 && v < 100))), 15000);
  const textoEnviando = (await page.textContent('#envio-texto')).trim();
  await page.click('#envio-cancelar');
  await esperar(async () => /cancelad/i.test(await page.textContent('#painel')), 5000);
  const cancelado = (await page.textContent('#painel')).replace(/\s+/g, ' ');

  // 5) envio completo
  await enviar(page, cfg.video);
  await page.waitForSelector('#video-info', { timeout: 30000 });
  await cdp.send('Network.emulateNetworkConditions',
    { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  const progresso = await page.evaluate(() => { clearInterval(window.__amostra); return window.__progresso; });
  await esperar(async () => (await page.textContent('#video-duracao')).match(/\d:\d\d/), 10000);
  const info = {
    duracao: (await page.textContent('#video-duracao')).trim(),
    formato: (await page.textContent('#video-formato')).trim(),
  };
  // player: carrega o video pelo servidor (Range) e responde aos botoes
  await esperar(async () => page.$eval('#player-video', (v) => v.readyState >= 1), 10000);
  const src = await page.$eval('#player-video', (v) => v.currentSrc);
  await page.click('#player-mais5');
  await esperar(async () => page.$eval('#player-video', (v) => v.currentTime > 4), 3000);
  const aposMais5 = await page.$eval('#player-video', (v) => v.currentTime);
  await page.click('#player-menos5');
  await esperar(async () => page.$eval('#player-video', (v) => v.currentTime < 1), 3000);
  const aposMenos5 = await page.$eval('#player-video', (v) => v.currentTime);
  await page.click('#player-play');
  await esperar(async () => (await page.getAttribute('#player-play', 'aria-label')) === 'Pausar', 3000).catch(() => {});
  const tocando = await page.$eval('#player-video', (v) => !v.paused);
  const rotuloPlay = await page.getAttribute('#player-play', 'aria-label');
  // espaco no corpo pausa; espaco num campo de texto nao
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await page.keyboard.press('Space');
  await esperar(async () => (await page.getAttribute('#player-play', 'aria-label')) === 'Tocar', 3000).catch(() => {});
  const pausadoPorEspaco = await page.$eval('#player-video', (v) => v.paused);
  const tempo = (await page.textContent('#player-tempo')).trim();
  const visivel = await textoVisivel(page);
  await screenshot(page, 'video-1280-claro.png');
  const r = {
    erroGrande, putsGrande, erroServidor, erroRede, textoEnviando, cancelado, progresso, info,
    src, aposMais5, aposMenos5, tocando, rotuloPlay, pausadoPorEspaco, tempo, visivel,
    estado: (await api(srvA, 'GET', `/api/projects/${proj.slug}`)).json,
    erros: page.__erros,
  };
  await ctx.close();
  return r;
});

// ------------------------------------------------------------ 375 px
await cenario('scroll375', async () => {
  const proj = (await api(srvA, 'GET', '/api/projects')).json.find((p) => p.nome === 'Reel envio');
  const ctx = await contexto({ viewport: { width: 375, height: 800 } });
  const medidas = {};
  const page = await abrir(ctx, srvA);
  medidas.inicial = await semRolagem(page);
  await screenshot(page, 'inicio-375-claro.png');
  await page.click('#btn-instalacao');
  await page.waitForSelector('#lista-itens .item');
  medidas.instalacao = await semRolagem(page);
  await screenshot(page, 'instalacao-375-claro.png');
  const page2 = await abrir(ctx, srvA, proj.slug);
  await page2.click('#passos .passo[data-passo="video"]');
  await page2.waitForSelector('#video-info');
  medidas.video = await semRolagem(page2);
  await screenshot(page2, 'video-375-claro.png');
  await page2.click('#passos .passo[data-passo="cortes"]');
  await page2.waitForSelector('#painel[data-passo="cortes"]');
  medidas.cortes = await semRolagem(page2);
  const alvos = await page2.$$eval('button, input, [role="button"]', (els) => els
    .filter((e) => e.offsetParent !== null && e.type !== 'file')
    .map((e) => { const r = e.getBoundingClientRect(); return { id: e.id || e.className, w: r.width, h: r.height }; }));
  const r = { medidas, alvos, erros: [...page.__erros, ...page2.__erros] };
  await ctx.close();
  return r;
});

// ------------------------------------------------------ tema escuro
await cenario('dark', async () => {
  const proj = (await api(srvA, 'GET', '/api/projects')).json.find((p) => p.nome === 'Reel envio');
  const r = {};
  for (const tema of ['light', 'dark']) {
    const ctx = await contexto({ colorScheme: tema });
    const page = await abrir(ctx, srvA, proj.slug);
    await page.click('#passos .passo[data-passo="video"]');
    await page.waitForSelector('#video-info');
    r[tema] = await page.evaluate(() => {
      const cs = getComputedStyle(document.body);
      return { fundo: cs.backgroundColor, texto: cs.color, fonte: getComputedStyle(document.querySelector('h1')).fontFamily };
    });
    const nome = tema === 'dark' ? 'escuro' : 'claro';
    await screenshot(page, `video-1280-${nome}.png`);
    await page.setViewportSize({ width: 375, height: 800 });
    await screenshot(page, `video-375-${nome}.png`);
    await page.click('#btn-instalacao');
    await page.waitForSelector('#lista-itens .item');
    await screenshot(page, `instalacao-375-${nome}.png`);
    await page.setViewportSize({ width: 1280, height: 800 });
    await screenshot(page, `instalacao-1280-${nome}.png`);
    await ctx.close();
  }
  return r;
});

// --------------------------------------------------- foco por teclado
await cenario('focus', async () => {
  const ctx = await contexto();
  const page = await abrir(ctx, srvA);
  const visitados = [];
  let achou = null;
  for (let i = 0; i < 25; i++) {
    await page.keyboard.press('Tab');
    const info = await page.evaluate(() => {
      const a = document.activeElement;
      const cs = getComputedStyle(a);
      return { id: a.id, passo: a.dataset ? a.dataset.passo || null : null,
        noPassos: !!a.closest('#passos'), outline: cs.outlineStyle, outlineW: cs.outlineWidth,
        sombra: cs.boxShadow, bloqueado: a.getAttribute('aria-disabled') };
    });
    visitados.push(info);
    if (info.noPassos && info.bloqueado !== 'true' && info.passo === 'video') { achou = info; break; }
  }
  if (achou) await page.keyboard.press('Enter');
  await page.waitForSelector('#painel[data-passo="video"]');
  const r = { visitados, achou, painel: await page.getAttribute('#painel', 'data-passo') };
  await ctx.close();
  return r;
});

// ------------------------------------------------- texto via textContent
await cenario('xss', async () => {
  const proj = (await api(srvA, 'POST', '/api/projects', { nome: XSS })).json;
  const ctx = await contexto();
  const page = await abrir(ctx, srvA);
  await page.click('#passos .passo[data-passo="video"]');
  await page.click('#btn-trocar-projeto').catch(() => {});
  await page.waitForSelector('#lista-projetos .projeto');
  const lista = (await page.textContent('#lista-projetos')).trim();
  await page.click(`#lista-projetos .projeto[data-slug="${proj.slug}"]`);
  await esperar(async () => (await page.textContent('#projeto-atual')).includes('<img'));
  await page.waitForLoadState('networkidle');
  const r = {
    lista, cabecalho: (await page.textContent('#projeto-atual')).trim(),
    xss: await page.evaluate(() => window.__xss === 1),
    imgs: await page.$$eval('body img', (is) => is.map((i) => i.outerHTML)),
    erros: page.__erros,
  };
  await ctx.close();
  return r;
});

// --------------------------------------------------------------- CSP
await cenario('csp', async () => {
  const ctx = await contexto();
  const pedidos = [];
  ctx.on('request', (rq) => pedidos.push(rq.url()));
  const page = await abrir(ctx, srvA);
  await page.waitForLoadState('networkidle');
  const carga = pedidos.slice();
  const res = await page.evaluate(async () => {
    const violacoes = [];
    document.addEventListener('securitypolicyviolation', (e) => violacoes.push(
      { uri: e.blockedURI, diretiva: e.effectiveDirective }));
    let fetchErro = null;
    try { await fetch('https://example.com/vazamento'); } catch (e) { fetchErro = String(e); }
    const img = new Image();
    img.src = 'https://example.com/pixel.png';
    document.body.appendChild(img);
    const s = document.createElement('script');
    s.src = 'https://example.com/x.js';
    document.head.appendChild(s);
    const inline = document.createElement('script');
    inline.textContent = 'window.__inline = 1';
    document.head.appendChild(inline);
    const fim = Date.now() + 3000;
    while (violacoes.length < 4 && Date.now() < fim) await new Promise((r) => setTimeout(r, 25));
    img.remove();
    return { violacoes, fetchErro, inline: window.__inline === 1 };
  });
  const r = { ...res, carga, base: srvA.base, externos: pedidos.filter((u) => !u.startsWith(srvA.base)) };
  await ctx.close();
  return r;
});

// ----------------------------------------------------------- token
await cenario('token', async () => {
  const ctx = await contexto();
  const page = await ctx.newPage();
  const sem = await page.goto(srvA.base + '/');
  const semTexto = (await page.textContent('body')).replace(/\s+/g, ' ').trim();
  const errado = await page.goto(srvA.base + '/?t=errado');
  // pagina servida com uma chave que o servidor nao aceita (ex.: editor reiniciado)
  await page.route(srvA.url, async (route) => {
    const resp = await route.fetch();
    const corpo = (await resp.text()).replace(srvA.token, 'chave-velha');
    await route.fulfill({ response: resp, body: corpo });
  });
  await page.goto(srvA.url);
  await page.waitForSelector('#fatal:not([hidden])', { timeout: 10000 });
  const r = {
    semStatus: sem.status(), semTexto, erradoStatus: errado.status(),
    fatal: (await page.textContent('#fatal')).replace(/\s+/g, ' ').trim(),
  };
  await ctx.close();
  return r;
});

// ------------------------------- respostas atrasadas de outro projeto
await cenario('corrida', async () => {
  const a = (await api(srvA, 'POST', '/api/projects', { nome: 'Reel A lento' })).json;
  const b = (await api(srvA, 'POST', '/api/projects', { nome: 'Reel B rapido' })).json;
  fs.writeFileSync(path.join(srvA.root, a.slug, 'entrada.mp4'), 'falso');
  const ctx = await contexto();
  const page = await abrir(ctx, srvA);
  await page.waitForSelector(`#lista-projetos .projeto[data-slug="${b.slug}"]`);
  let segura;
  const solto = new Promise((r) => { segura = r; });
  await page.route(`**/api/projects/${a.slug}`, async (route) => {
    await solto;
    await route.continue();
  });
  await page.click(`#lista-projetos .projeto[data-slug="${a.slug}"]`);
  await page.click(`#lista-projetos .projeto[data-slug="${b.slug}"]`);
  await esperar(async () => (await page.textContent('#projeto-atual')).includes('Reel B'));
  segura();
  await page.waitForLoadState('networkidle');
  await page.click('#passos .passo[data-passo="video"]');
  await page.waitForSelector('#arquivo-video', { state: 'attached' });
  const r = {
    cabecalho: (await page.textContent('#projeto-atual')).trim(),
    passos: await estados(page),
    temInfoVideo: await page.locator('#video-info').count(),
    storage: await page.evaluate(() => localStorage.getItem('editor-reels:ultimo-projeto')),
    b: b.slug,
  };
  // envio do Reel A termina depois de trocar para o B
  await page.unroute(`**/api/projects/${a.slug}`);
  await page.click('#btn-trocar-projeto');
  await page.click(`#lista-projetos .projeto[data-slug="${a.slug}"]`);
  await page.click('#passos .passo[data-passo="video"]');
  await page.waitForSelector('#arquivo-video', { state: 'attached' });
  const cdp = await ctx.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions',
    { offline: false, latency: 20, downloadThroughput: -1, uploadThroughput: 200 * 1024 });
  await enviar(page, cfg.video);
  await page.waitForSelector('#envio:not([hidden])');
  await page.click('#btn-trocar-projeto');
  await page.click(`#lista-projetos .projeto[data-slug="${b.slug}"]`);
  await esperar(async () => (await page.locator('#toasts .toast').allTextContents()).some((t) => t.includes('Reel A lento')), 30000);
  await cdp.send('Network.emulateNetworkConditions',
    { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await page.waitForLoadState('networkidle');
  r.depoisEnvio = {
    cabecalho: (await page.textContent('#projeto-atual')).trim(),
    toasts: await page.locator('#toasts .toast').allTextContents(),
    passos: await estados(page),
    estadoA: (await api(srvA, 'GET', `/api/projects/${a.slug}`)).json.etapas.video,
    src: await page.$eval('#player-video', (v) => v.getAttribute('src') || ''),
  };
  r.erros = page.__erros;
  await ctx.close();
  return r;
});

// ------------------------------- ultimo projeto nao some por falha de rede
await cenario('rede', async () => {
  const p = (await api(srvA, 'POST', '/api/projects', { nome: 'Reel rede' })).json;
  const ctx = await contexto();
  await ctx.route(`**/api/projects/${p.slug}`, (route) => route.abort('connectionreset'));
  const page = await ctx.newPage();
  await page.addInitScript((s) => {
    if (!sessionStorage.getItem('semeado')) {
      localStorage.setItem('editor-reels:ultimo-projeto', s);
      sessionStorage.setItem('semeado', '1');
    }
  }, p.slug);
  await page.goto(srvA.url);
  await page.waitForSelector('#painel[data-passo]');
  const comFalha = await page.evaluate(() => localStorage.getItem('editor-reels:ultimo-projeto'));
  await ctx.unroute(`**/api/projects/${p.slug}`);
  await api(srvA, 'GET', '/api/projects');
  // projeto que nao existe mais (404): ai sim esquece
  await page.evaluate(() => localStorage.setItem('editor-reels:ultimo-projeto', 'nao-existe'));
  await page.goto(srvA.url);
  await page.waitForSelector('#painel[data-passo]');
  const com404 = await page.evaluate(() => localStorage.getItem('editor-reels:ultimo-projeto'));
  const r = { comFalha, com404, slug: p.slug };
  await ctx.close();
  return r;
});

await browser.close();
for (const s of srvs) s.parar();
process.stdout.write(JSON.stringify(out));

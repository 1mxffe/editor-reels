// Teste de tela do modo "Juntar vários trechos" (passo Vídeo) contra o servidor REAL em modo
// de teste: enviar varios arquivos, progresso e cancelamento, reordenar (botoes, teclado e
// arrastar), remover, montar, confirmacao antes de apagar cortes/legendas, troca de Reel no
// meio do envio, nomes hostis e 375 px. Quem afirma e o pytest.
//
// Uso: node tests/js/app_flow_d.mjs <config.json>
// config: {tmp, screens, root, brand, slugs: {...}, clipes: {a,b,c,lixo,texto}}
import fs from 'node:fs';
import path from 'node:path';
import { iniciarServidor, api, esperar, require_ } from './helpers.mjs';

const { chromium } = require_('playwright');
const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
const DOCTOR_OK = {
  estado: 'READY',
  itens: [{ name: 'python >= 3.11', ok: true, required: true },
    { name: 'ffmpeg', ok: true, required: true }, { name: 'ffprobe', ok: true, required: true }],
};
const LONGO = 120000;

const browser = await chromium.launch();
const out = {};
const visivel = {};
let page = null;

const srv = await iniciarServidor({ root: cfg.root, brand: cfg.brand, doctor: DOCTOR_OK, test_mode: true }, cfg.tmp);

async function contexto(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...opts });
  ctx.setDefaultTimeout(30000);
  return ctx;
}
async function abrir(ctx, ultimo) {
  const pg = await ctx.newPage();
  const erros = [];
  pg.on('pageerror', (e) => erros.push(String(e)));
  pg.on('console', (m) => {
    if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) erros.push(m.text());
  });
  await pg.addInitScript((s) => {
    try { localStorage.setItem('editor-reels:ultimo-projeto', s); } catch { /* sem storage */ }
  }, ultimo);
  await pg.goto(srv.url);
  await pg.waitForSelector('#painel[data-passo]');
  pg.__erros = erros;
  page = pg;
  return pg;
}
const semRolagem = (pg) => pg.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
  bodyScroll: document.body.scrollWidth,
  estouram: [...document.querySelectorAll('#painel *')].filter((e) => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.right > document.documentElement.clientWidth + 1 && !e.closest('.sr-only');
  }).map((e) => e.className || e.tagName).slice(0, 8),
}));
const textoVisivel = (pg) => pg.evaluate(() => document.body.innerText);
async function screenshot(pg, nome) {
  if (!cfg.screens) return;
  fs.mkdirSync(cfg.screens, { recursive: true });
  await pg.screenshot({ path: path.join(cfg.screens, nome), fullPage: true });
}
async function cenario(nome, fn) {
  try {
    out[nome] = await fn();
  } catch (e) {
    let painel = '';
    try { painel = page ? (await page.textContent('#painel', { timeout: 1000 })).replace(/\s+/g, ' ') : ''; } catch { /* sem pagina */ }
    out[nome] = { error: String(e && e.stack || e) + (painel ? `\n[painel] ${painel.slice(0, 1500)}` : '') };
  }
}
async function modoJuntar(pg) {
  await pg.click('#modo-juntar');
  await pg.waitForSelector('#arquivos-clipes', { state: 'attached' });
}
const nomes = (pg) => pg.$$eval('#clipes-lista .clipe .clipe-nome', (l) => l.map((x) => x.textContent));
const contar = (pg) => pg.$$eval('#clipes-lista .clipe', (l) => l.length);
const esperarClipes = (pg, n) => esperar(async () => (await contar(pg)) === n, LONGO, 100);
const ocioso = (pg) => esperar(async () => !(await pg.$('#tarefa:not([hidden])[data-estado="rodando"]')), LONGO, 200);
const foco = (pg) => pg.evaluate(() => {
  const a = document.activeElement;
  const li = a && a.closest ? a.closest('.clipe') : null;
  return { acao: a && a.dataset ? a.dataset.acao || '' : '', arquivo: li ? li.dataset.arquivo : '', id: a ? a.id : '' };
});
const arquivosDaLista = (pg) => pg.$$eval('#clipes-lista .clipe', (l) => l.map((x) => x.dataset.arquivo));
const atrasar = (pg, ms) => pg.route('**/api/projects/*/clipes', async (route) => {
  if (route.request().method() === 'PUT') await new Promise((ok) => setTimeout(ok, ms));
  await route.continue();
});
const lerDados = async (slug, rota) => (await api(srv, 'GET', `/api/projects/${slug}${rota}`)).json;

const S = cfg.slugs;
const C = cfg.clipes;

// ============================ enviar, ordenar, remover, montar (um Reel so, em sequencia)
await cenario('enviar', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.principal);
  const r = {};
  r.modosAntes = await pg.$$eval('.modo-escolha button', (b) => b.map((x) => [x.textContent, x.getAttribute('aria-pressed')]));
  r.umSoVisivel = await pg.isVisible('#arquivo-video') || await pg.isVisible('.soltar');
  await modoJuntar(pg);
  r.modosDepois = await pg.$$eval('.modo-escolha button', (b) => b.map((x) => [x.textContent, x.getAttribute('aria-pressed')]));
  r.listaVaziaTexto = await pg.textContent('#clipes-vazio');
  r.montarDesligado = await pg.$eval('#clipes-montar', (b) => b.disabled);
  r.inputMultiplo = await pg.$eval('#arquivos-clipes', (i) => i.multiple);
  // progresso: o envio e atrasado de proposito para dar tempo de ver as duas barras
  await atrasar(pg, 700);
  await pg.setInputFiles('#arquivos-clipes', [C.a, C.b, C.c]);
  await pg.waitForSelector('#clipes-envio:not([hidden])');
  r.envio = {
    texto: await pg.textContent('#clipes-envio-texto'),
    barras: await pg.$$eval('#clipes-envio progress', (p) => p.map((x) => x.id)),
    cancelar: await pg.isVisible('#clipes-cancelar'),
    zonaDesligada: await pg.$eval('#painel-juntar .soltar', (z) => z.classList.contains('desligada')),
    montarDesligado: await pg.$eval('#clipes-montar', (b) => b.disabled),
  };
  await esperarClipes(pg, 3);
  await esperar(async () => await pg.isHidden('#clipes-envio'), LONGO, 100);
  await pg.unroute('**/api/projects/*/clipes');
  r.depoisDoEnvio = await nomes(pg);
  r.metas = await pg.$$eval('#clipes-lista .clipe-meta', (l) => l.map((x) => x.textContent));
  r.total = await pg.textContent('#clipes-total');
  r.avisosVisiveis = await pg.isVisible('#clipes-avisos');
  r.estadoApi = (await lerDados(S.principal, '')).clipes;
  r.visivelLista = await textoVisivel(pg);
  r.erros = pg.__erros;
  visivel.lista = r.visivelLista;
  await ctx.close();
  return r;
});

await cenario('ordem', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.principal);
  const r = {};
  r.modoAoAbrir = await pg.getAttribute('#modo-juntar', 'aria-pressed');
  await pg.waitForSelector('#clipes-lista .clipe');
  const antes = await arquivosDaLista(pg);
  r.antes = await nomes(pg);
  r.subirDoPrimeiro = await pg.$eval('#clipes-lista .clipe:first-child [data-acao="subir"]', (b) => b.disabled);
  r.descerDoUltimo = await pg.$eval('#clipes-lista .clipe:last-child [data-acao="descer"]', (b) => b.disabled);
  r.rotuloBotao = await pg.$eval('#clipes-lista .clipe:first-child [data-acao="descer"]', (b) => b.getAttribute('aria-label'));
  // teclado: foco no "Descer" do primeiro e Enter
  await pg.focus('#clipes-lista .clipe:first-child [data-acao="descer"]');
  await pg.keyboard.press('Enter');
  await esperar(async () => (await nomes(pg))[1] === r.antes[0], 10000, 50);
  r.depoisDescer = await nomes(pg);
  r.focoDepoisDescer = await foco(pg);
  r.focoNoMovido = r.focoDepoisDescer.arquivo === antes[0];
  // Shift+Tab leva ao "Subir" do mesmo trecho; Espaco aciona e o foco fica no trecho movido
  await pg.keyboard.press('Shift+Tab');
  r.focoShiftTab = (await foco(pg)).acao;
  await pg.keyboard.press('Space');
  await esperar(async () => (await nomes(pg))[0] === r.antes[0], 10000, 50);
  r.depoisSubir = await nomes(pg);
  r.focoDepoisSubir = await foco(pg);
  // servidor guardou a ordem
  r.ordemNoServidor = (await lerDados(S.principal, '/clipes')).clipes.map((c) => c.nome);
  // arrastar o ultimo para o primeiro lugar
  await pg.dragAndDrop('#clipes-lista .clipe:nth-child(3)', '#clipes-lista .clipe:nth-child(1)');
  await esperar(async () => (await nomes(pg))[0] === r.antes[2], 10000, 50);
  r.depoisArrastar = await nomes(pg);
  r.ordemNoServidorDepoisArrastar = (await lerDados(S.principal, '/clipes')).clipes.map((c) => c.nome);
  // montagem passa a "desatualizada" so depois de montada; antes nao diz nada
  r.situacaoAntes = await pg.isVisible('#clipes-situacao');
  // remover o do meio, com foco indo para um vizinho
  const meio = (await arquivosDaLista(pg))[1];
  await pg.click(`#clipes-lista .clipe[data-arquivo="${meio}"] [data-acao="remover"]`);
  await esperarClipes(pg, 2);
  r.depoisRemover = await nomes(pg);
  r.focoDepoisRemover = await foco(pg);
  r.totalDepois = await pg.textContent('#clipes-total');
  // reenviar o removido
  await pg.setInputFiles('#arquivos-clipes', [C.a]);
  await esperarClipes(pg, 3);
  await esperar(async () => await pg.isHidden('#clipes-envio'), LONGO, 100);
  r.final = await nomes(pg);
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

await cenario('montar', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.principal);
  const r = {};
  await pg.waitForSelector('#clipes-lista .clipe');
  r.ordemAntes = await nomes(pg);
  r.cortesBloqueado = await pg.$eval('#passos .passo[data-passo="cortes"]', (b) => b.getAttribute('aria-disabled'));
  await pg.click('#clipes-montar');
  await pg.waitForSelector('#tarefa:not([hidden])[data-estado="rodando"]');
  r.progresso = await pg.textContent('#tarefa-texto');
  r.detalhesFechados = await pg.$eval('#tarefa details', (d) => !d.open);
  r.montarEscondido = await pg.isHidden('#clipes-montar');
  r.botoesDuranteDesligados = await pg.$$eval('#clipes-lista .clipe button', (b) => b.every((x) => x.disabled));
  r.zonaDesligada = await pg.$eval('#painel-juntar .soltar', (z) => z.classList.contains('desligada'));
  r.cancelavel = await pg.isVisible('#tarefa-cancelar');
  await pg.waitForSelector('#video-info', { timeout: LONGO });
  await esperarClipes(pg, 3);
  await esperar(async () => (await pg.textContent('#clipes-situacao')).trim() !== '', 10000, 50);
  await esperar(async () => ((await pg.$eval('#player-video', (v) => v.getAttribute('src') || '')).includes('entrada.mp4')), 10000, 50);
  r.tituloInfo = await pg.textContent('#video-info h2');
  r.cortesLiberado = await pg.$eval('#passos .passo[data-passo="cortes"]', (b) => b.getAttribute('aria-disabled'));
  r.videoPronto = await pg.$eval('#passos .passo[data-passo="video"]', (b) => b.dataset.estado);
  r.playerSrc = await pg.$eval('#player-video', (v) => v.getAttribute('src') || '');
  r.playerRotulo = await pg.textContent('#player-legenda');
  r.situacao = await pg.textContent('#clipes-situacao');
  r.tarefaEscondida = await pg.isHidden('#tarefa');
  r.irParaCortes = await pg.textContent('#video-info .botao');
  r.estado = await lerDados(S.principal, '');
  r.visivel = await textoVisivel(pg);
  visivel.montado = r.visivel;
  await screenshot(pg, 'juntar-montado-1280.png');
  // mudar a ordem depois de montar -> "montagem desatualizada" na tela
  await pg.click('#clipes-lista .clipe:first-child [data-acao="descer"]');
  await esperar(async () => (await nomes(pg))[0] !== r.ordemAntes[0], 10000, 50);
  r.situacaoDesatualizada = await pg.textContent('#clipes-situacao');
  // seguir para Cortes
  await pg.click('#video-info .botao');
  await pg.waitForSelector('#painel[data-passo="cortes"]');
  r.passoSeguinte = await pg.getAttribute('#painel', 'data-passo');
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ============================ cancelar o envio
await cenario('cancelar', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.cancelar);
  const r = {};
  await modoJuntar(pg);
  await atrasar(pg, 3000);
  await pg.setInputFiles('#arquivos-clipes', [C.a, C.b, C.c]);
  await pg.waitForSelector('#clipes-cancelar:not([hidden])');
  await pg.click('#clipes-cancelar');
  await pg.waitForSelector('#clipes-avisos:not([hidden])');
  await pg.unroute('**/api/projects/*/clipes');
  r.aviso = await pg.textContent('#clipes-avisos');
  r.envioEscondido = await pg.isHidden('#clipes-envio');
  r.lista = await contar(pg);
  r.montarDesligado = await pg.$eval('#clipes-montar', (b) => b.disabled);
  r.noServidor = (await lerDados(S.cancelar, '/clipes')).clipes.length;
  // fechar o aviso
  await pg.click('#clipes-avisos-fechar');
  r.avisoFechado = await pg.isHidden('#clipes-avisos');
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ============================ arquivos ruins, soltar arquivos, nomes hostis
await cenario('ruins', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.ruins);
  const r = {};
  await modoJuntar(pg);
  const hostil = '<img src=x onerror="window.__pwn=1">.mp4';
  await pg.setInputFiles('#arquivos-clipes', [
    { name: 'lixo.mp4', mimeType: 'video/mp4', buffer: fs.readFileSync(C.lixo) },
    { name: 'notas.txt', mimeType: 'text/plain', buffer: fs.readFileSync(C.texto) },
    { name: hostil, mimeType: 'video/mp4', buffer: fs.readFileSync(C.c) },
    { name: 'sem.extensao', mimeType: 'video/mp4', buffer: fs.readFileSync(C.c) },
    { name: 'vazio.mp4', mimeType: 'video/mp4', buffer: Buffer.alloc(0) },
  ]);
  await pg.waitForSelector('#clipes-avisos:not([hidden])');
  await esperar(async () => await pg.isHidden('#clipes-envio'), LONGO, 100);
  r.aviso = await pg.innerText('#clipes-avisos');
  r.lista = await nomes(pg);
  r.pwn = await pg.evaluate(() => window.__pwn === undefined);
  r.imgsNaLista = await pg.$$eval('#clipes-lista img, #clipes-avisos img', (e) => e.length);
  r.noServidor = (await lerDados(S.ruins, '/clipes')).clipes.length;
  // arquivo com limite de tamanho do cliente (config do servidor): tamanho acima de max_upload
  r.visivel = await textoVisivel(pg);
  visivel.ruins = r.visivel;
  // soltar arquivos na area (drop com DataTransfer)
  await pg.click('#clipes-avisos-fechar');
  const b64 = fs.readFileSync(C.c).toString('base64');
  const dt = await pg.evaluateHandle(async (dados) => {
    const t = new DataTransfer();
    const bin = Uint8Array.from(atob(dados), (c) => c.charCodeAt(0));
    t.items.add(new File([bin], 'solto-na-area.mp4', { type: 'video/mp4' }));
    return t;
  }, b64);
  await pg.dispatchEvent('#painel-juntar .soltar', 'drop', { dataTransfer: dt });
  await esperar(async () => (await nomes(pg)).includes('solto-na-area'), LONGO, 100);
  r.depoisDoDrop = await nomes(pg);
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ============================ confirmacao antes de apagar o que depende do video atual
await cenario('confirmar', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.confirmar);
  const r = {};
  r.passoAoAbrir = await pg.getAttribute('#painel', 'data-passo');
  await pg.click('#passos .passo[data-passo="video"]');
  await pg.waitForSelector('#painel[data-passo="video"]');
  await modoJuntar(pg);
  await pg.setInputFiles('#arquivos-clipes', [C.a, C.b]);
  await esperarClipes(pg, 2);
  await esperar(async () => await pg.isHidden('#clipes-envio'), LONGO, 100);
  r.situacaoAntes = await pg.textContent('#clipes-situacao');
  await pg.click('#clipes-montar');
  await pg.waitForSelector('#clipes-confirmar:not([hidden])');
  r.itens = await pg.$$eval('#clipes-perde li', (l) => l.map((x) => x.textContent));
  r.titulo = await pg.textContent('#clipes-confirmar-titulo');
  r.botao = await pg.textContent('#clipes-confirmar-sim');
  r.focoNaConfirmacao = (await foco(pg)).id;
  r.tarefaIniciada = await pg.isVisible('#tarefa');
  r.estadoSemConfirmar = (await lerDados(S.confirmar, '')).etapas;
  r.visivelConfirmacao = await textoVisivel(pg);
  visivel.confirmacao = r.visivelConfirmacao;
  // 375 px com o aviso aberto
  await pg.setViewportSize({ width: 375, height: 800 });
  r.rolagem375 = await semRolagem(pg);
  await screenshot(pg, 'juntar-confirmar-375.png');
  await pg.setViewportSize({ width: 1280, height: 800 });
  // voltar nao muda nada e devolve o foco ao botao Montar
  await pg.click('#clipes-confirmar-nao');
  r.confirmacaoFechou = await pg.isHidden('#clipes-confirmar');
  r.focoVoltou = (await foco(pg)).id;
  r.estadoDepoisDeVoltar = (await lerDados(S.confirmar, '')).etapas;
  // agora confirma
  await pg.click('#clipes-montar');
  await pg.waitForSelector('#clipes-confirmar:not([hidden])');
  await pg.click('#clipes-confirmar-sim');
  await pg.waitForSelector('#tarefa:not([hidden])[data-estado="rodando"]');
  await esperar(async () => (await pg.textContent('#video-info h2')) === 'Vídeo montado', LONGO, 200);
  r.estadoDepois = (await lerDados(S.confirmar, '')).etapas;
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ============================ trocar de Reel no meio do envio
await cenario('troca', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, S.trocaA);
  const r = {};
  await modoJuntar(pg);
  await atrasar(pg, 1200);
  await pg.setInputFiles('#arquivos-clipes', [C.a, C.b]);
  await pg.waitForSelector('#clipes-envio:not([hidden])');
  await pg.click('#btn-trocar-projeto');
  await pg.waitForSelector(`#lista-projetos .projeto[data-slug="${S.trocaB}"]`);
  await pg.click(`#lista-projetos .projeto[data-slug="${S.trocaB}"]`);
  await pg.waitForSelector('#painel[data-passo="video"]');
  r.cabecalho = await pg.textContent('#projeto-atual');
  await modoJuntar(pg);
  // espera o envio do Reel A terminar (2 x 1,2 s) e confere que nada vazou para o B
  await esperar(async () => (await lerDados(S.trocaA, '/clipes')).clipes.length === 2, LONGO, 200);
  await pg.waitForTimeout(500);
  await pg.unroute('**/api/projects/*/clipes');
  r.listaB = await contar(pg);
  r.envioVisivelNoB = await pg.isVisible('#clipes-envio');
  r.avisosNoB = await pg.isVisible('#clipes-avisos');
  r.noServidorA = (await lerDados(S.trocaA, '/clipes')).clipes.length;
  r.noServidorB = (await lerDados(S.trocaB, '/clipes')).clipes.length;
  r.toasts = await pg.$$eval('#toasts .toast', (t) => t.map((x) => x.textContent));
  // voltando ao Reel A, a lista dele esta la
  await pg.click('#btn-trocar-projeto');
  await pg.click(`#lista-projetos .projeto[data-slug="${S.trocaA}"]`);
  await pg.waitForSelector('#clipes-lista .clipe');
  r.listaAVoltando = await contar(pg);
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ============================ 375 px
await cenario('estreito', async () => {
  const ctx = await contexto({ viewport: { width: 375, height: 800 } });
  const pg = await abrir(ctx, S.estreito);
  const r = {};
  await modoJuntar(pg);
  const longo = 'um-nome-de-arquivo-muito-muito-longo-que-nao-quebra-em-lugar-nenhum-mesmo-assim-ficar-dentro-da-tela-1234567890';
  await pg.setInputFiles('#arquivos-clipes', [
    { name: `${longo}.mp4`, mimeType: 'video/mp4', buffer: fs.readFileSync(C.a) },
    { name: 'dois.mp4', mimeType: 'video/mp4', buffer: fs.readFileSync(C.b) },
    { name: 'tres.mp4', mimeType: 'video/mp4', buffer: fs.readFileSync(C.c) },
  ]);
  await esperarClipes(pg, 3);
  await esperar(async () => await pg.isHidden('#clipes-envio'), LONGO, 100);
  r.rolagemLista = await semRolagem(pg);
  r.botoesAltura = await pg.$$eval('#clipes-lista .clipe button', (b) => b.map((x) => Math.round(x.getBoundingClientRect().height)));
  await screenshot(pg, 'juntar-lista-375.png');
  await atrasar(pg, 800);
  await pg.setInputFiles('#arquivos-clipes', [C.c]);
  await pg.waitForSelector('#clipes-envio:not([hidden])');
  r.rolagemEnvio = await semRolagem(pg);
  await esperarClipes(pg, 4);
  await pg.unroute('**/api/projects/*/clipes');
  await esperar(async () => await pg.isHidden('#clipes-envio'), LONGO, 100);
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

out.visivel = visivel;
await browser.close();
srv.parar();
process.stdout.write(JSON.stringify(out));

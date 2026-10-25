// Teste de tela do passo Estilo contra o servidor REAL em modo de teste: abas, cartoes com
// quadros de exemplo (Chromium de verdade), "Usar" + "Aplicar estilo" (preview novo), "mais
// parecido com este", formulario de efeitos e avisos do banco. Quem afirma e o pytest.
//
// Uso: node tests/js/app_flow_c.mjs <config.json>
// config: {tmp, screens, roots: {a, b}, brands: {a, b}, slugs: {principal, aplicar, hostil},
//          banco_hostil, fonts_dir, preview_copia}
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
const LONGO = 240000;

const browser = await chromium.launch();
const out = {};
const srvs = [];
const visivel = {};
let page = null;

async function servidor(qual, extra = {}) {
  const s = await iniciarServidor({ root: cfg.roots[qual], brand: cfg.brands[qual], doctor: DOCTOR_OK, test_mode: true, ...extra }, cfg.tmp);
  srvs.push(s);
  return s;
}
async function contexto(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...opts });
  ctx.setDefaultTimeout(30000);
  return ctx;
}
async function abrir(ctx, srv, ultimo) {
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
  // elementos do painel que passam da borda direita da janela (o body esconde o excesso)
  estouram: [...document.querySelectorAll('#painel *')].filter((e) => {
    const b = e.getBoundingClientRect();
    return b.width > 0 && b.right > document.documentElement.clientWidth + 1 && !e.closest('.sr-only');
  }).map((e) => e.className || e.tagName).slice(0, 8),
}));
const textoVisivel = (pg) => pg.evaluate(() => document.body.innerText);
async function screenshot(pg, nome) {
  if (!cfg.screens) return;
  fs.mkdirSync(cfg.screens, { recursive: true });
  await pg.evaluate(() => Promise.all([...document.images].map((i) => (i.complete ? 0
    : new Promise((ok) => { i.onload = ok; i.onerror = ok; })))));
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
async function irPasso(pg, id) {
  await pg.click(`#passos .passo[data-passo="${id}"]`);
  await pg.waitForSelector(`#painel[data-passo="${id}"]`);
}
async function abrirAba(pg, aba) {
  await pg.click(`#tab-estilo-${aba}`);
  await pg.waitForSelector(`#aba-estilo-${aba}:not([hidden])`);
}
/** Espera os n quadros de exemplo da aba carregarem de verdade (naturalWidth > 0). */
const exemplosProntos = (pg, aba, n) => pg.waitForFunction(([a, k]) => {
  const imgs = [...document.querySelectorAll(`#grade-${a} img.estilo-img`)];
  return imgs.length === k && imgs.every((i) => i.complete && i.naturalWidth > 0);
}, [aba, n], { timeout: LONGO });
const ocioso = (pg) => esperar(async () => !(await pg.$('#tarefa:not([hidden])[data-estado="rodando"]')), LONGO, 200);
const ordem = (pg, aba) => pg.$$eval(`#grade-${aba} .estilo-cartao`, (ls) => ls.map((l) => l.dataset.id));
const situacao = async (pg) => { await pg.waitForSelector('#estilo-situacao'); return pg.$eval('#estilo-situacao', (e) => e.textContent); };

const srvA = await servidor('a');
const P = cfg.slugs.principal;
const U = cfg.slugs.aplicar;

// ================================================== abas e cartoes
await cenario('abas', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvA, P);
  const r = { estados: await pg.$$eval('#passos .passo', (bs) => Object.fromEntries(bs.map((b) => [b.dataset.passo, b.getAttribute('aria-disabled')]))) };
  await irPasso(pg, 'estilo');
  await pg.waitForSelector('#tab-estilo-paletas');
  r.abas = await pg.$$eval('[role="tab"]', (ts) => ts.map((t) => t.textContent));
  // esqueleto + barra de progresso cancelavel enquanto os exemplos nao chegam
  await pg.waitForSelector('#grade-paletas .esqueleto', { state: 'attached' });
  r.esqueletos = await pg.$$eval('#grade-paletas .esqueleto', (e) => e.length);
  await pg.waitForSelector('#tarefa:not([hidden])[data-estado="rodando"]');
  r.tarefaTexto = await pg.$eval('#tarefa-texto', (e) => e.textContent);
  r.cancelavel = await pg.$eval('#tarefa-cancelar', (b) => !b.hidden && !b.disabled);
  await exemplosProntos(pg, 'paletas', 4);
  r.paletas = await pg.$$eval('#grade-paletas .estilo-cartao', (ls) => ls.map((l) => ({
    id: l.dataset.id, nome: l.querySelector('.estilo-nome').textContent, desc: l.querySelector('.estilo-desc').textContent,
    src: l.querySelector('img').getAttribute('src'), w: l.querySelector('img').naturalWidth, h: l.querySelector('img').naturalHeight,
    usar: !!l.querySelector('.estilo-usar'), parecido: !!l.querySelector('.estilo-parecido'),
  })));
  r.escolhidoInicial = await pg.$$eval('#grade-paletas [data-escolhido="true"]', (ls) => ls.map((l) => l.dataset.id));
  r.situacaoInicial = await situacao(pg);
  visivel['estilo-paletas'] = await textoVisivel(pg);
  await screenshot(pg, 'estilo-paletas-1280.png');
  await ocioso(pg);
  // legendas e efeitos: cada aba dispara os seus exemplos
  await abrirAba(pg, 'legendas');
  await exemplosProntos(pg, 'legendas', 4);
  r.legendas = await ordem(pg, 'legendas');
  r.posicoes = await pg.$$eval('#legenda-posicao option', (o) => o.map((x) => x.textContent));
  r.tamanhos = await pg.$$eval('#legenda-tamanho option', (o) => o.map((x) => x.textContent));
  visivel['estilo-legendas'] = await textoVisivel(pg);
  await ocioso(pg);
  await abrirAba(pg, 'efeitos');
  await exemplosProntos(pg, 'efeitos', 10);
  r.efeitos = await ordem(pg, 'efeitos');
  r.efeitoBotao = await pg.$eval('#grade-efeitos .estilo-adicionar', (b) => b.textContent);
  visivel['estilo-efeitos'] = await textoVisivel(pg);
  await ocioso(pg);
  // voltar a uma aba pronta nao refaz o trabalho
  await abrirAba(pg, 'paletas');
  r.refeito = !!(await pg.$('#tarefa:not([hidden])[data-estado="rodando"]'));
  await abrirAba(pg, 'notas');
  visivel['estilo-notas'] = await textoVisivel(pg);
  r.notas = await pg.$eval('#aba-estilo-notas', (e) => e.innerText);
  await abrirAba(pg, 'fontes');
  r.fontes = await pg.$$eval('#lista-fontes .fonte', (ls) => ls.map((l) => ({
    nome: l.dataset.nome, desabilitado: l.querySelector('button').disabled, selo: !!l.querySelector('.selo'),
    fonte: l.querySelector('.fonte-nome').style.fontFamily,
  })));
  r.fontesAjuda = await pg.$eval('#fontes-ajuda', (e) => e.textContent);
  visivel['estilo-fontes'] = await textoVisivel(pg);
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== usar + aplicar
await cenario('aplicar', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvA, U);
  await irPasso(pg, 'estilo');
  const r = { situacaoAntes: null };
  await pg.waitForSelector('#grade-paletas .estilo-cartao');
  r.situacaoAntes = await situacao(pg);
  r.estiloAntes = (await api(srvA, 'GET', `/api/projects/${U}/estilo`)).json;
  r.playerAntes = await pg.$eval('#player-video', (v) => v.getAttribute('src'));
  await pg.click('#grade-paletas [data-id="grafite"] .estilo-usar');
  r.escolhida = await pg.$$eval('#grade-paletas [data-escolhido="true"]', (ls) => ls.map((l) => l.dataset.id));
  r.pressionado = await pg.$eval('#grade-paletas [data-id="grafite"] .estilo-usar', (b) => b.getAttribute('aria-pressed'));
  r.situacaoDepois = await situacao(pg);
  r.estiloSemAplicar = (await api(srvA, 'GET', `/api/projects/${U}/estilo`)).json; // so grava ao aplicar
  await abrirAba(pg, 'legendas');
  await pg.click('#grade-legendas [data-id="faixa-azul"] .estilo-usar');
  await pg.selectOption('#legenda-posicao', 'meio');
  await pg.selectOption('#legenda-tamanho', 'G');
  await esperar(async () => !(await pg.$eval('#estilo-aplicar', (b) => b.disabled)), LONGO, 200);
  await pg.click('#estilo-aplicar');
  await pg.waitForSelector('#tarefa:not([hidden])[data-estado="rodando"]');
  r.progresso = await pg.$eval('#tarefa-texto', (e) => e.textContent);
  r.aplicarDuranteDesligado = await pg.$eval('#estilo-aplicar', (b) => b.disabled);
  await ocioso(pg);
  await esperar(async () => (await pg.$('#estilo-situacao')) && (await pg.$eval('#estilo-situacao', (e) => e.textContent).catch(() => '')) === 'Estilo aplicado.', 60000, 200);
  r.situacaoFinal = await situacao(pg);
  r.estiloDepois = (await api(srvA, 'GET', `/api/projects/${U}/estilo`)).json;
  await esperar(async () => /preview\.mp4.*[?&]v=/.test(await pg.$eval('#player-video', (v) => v.getAttribute('src') || '')), 30000, 100);
  r.playerDepois = await pg.$eval('#player-video', (v) => v.getAttribute('src'));
  r.escolhidaDepois = await pg.$$eval('#grade-legendas [data-escolhido="true"]', (ls) => ls.map((l) => l.dataset.id));
  r.posicaoDepois = await pg.$eval('#legenda-posicao', (s) => s.value);
  fs.copyFileSync(path.join(cfg.roots.a, U, 'saida', 'preview.mp4'), cfg.preview_copia);
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== mais parecido com este
await cenario('parecido', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvA, P);
  await irPasso(pg, 'estilo');
  await pg.waitForSelector('#grade-paletas .estilo-cartao');
  const r = { antes: await ordem(pg, 'paletas') };
  const api_ = (await api(srvA, 'GET', `/api/banco/paletas/${r.antes[3]}/variacoes?projeto=${P}`)).json;
  r.esperadas = api_.variacoes.map((v) => v.nome);
  await pg.click(`#grade-paletas [data-id="${r.antes[3]}"] .estilo-parecido`);
  await pg.waitForSelector('#parecidos-paletas .variacao');
  r.depois = await ordem(pg, 'paletas');
  r.alvo = r.antes[3];
  r.variacoes = await pg.$$eval('#parecidos-paletas .variacao', (ls) => ls.map((l) => l.dataset.nome));
  r.titulo = await pg.$eval('#parecidos-paletas h3', (e) => e.textContent);
  r.cores = await pg.$$eval('#parecidos-paletas .cor', (cs) => cs.map((c) => c.style.background).filter(Boolean).length);
  // legenda: a variacao pode ser usada (posicao e tamanho)
  await abrirAba(pg, 'legendas');
  await pg.waitForSelector('#grade-legendas .estilo-cartao');
  await pg.click('#grade-legendas [data-id="faixa-azul"] .estilo-parecido');
  await pg.waitForSelector('#parecidos-legendas .variacao');
  await pg.click('#parecidos-legendas [data-nome="Faixa azul no meio"] .estilo-usar-variacao');
  r.posicaoVariacao = await pg.$eval('#legenda-posicao', (s) => s.value);
  await ocioso(pg);
  r.situacao = await situacao(pg);
  // nada foi aplicado: as escolhas ficam so na tela
  r.estiloSalvo = (await api(srvA, 'GET', `/api/projects/${P}/estilo`)).json;
  await ctx.close();
  return r;
});

// ================================================== efeitos: formulario e graficos.json
await cenario('efeitos', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvA, P);
  // um card antigo ja existe: o efeito entra sem apagar
  await api(srvA, 'PUT', `/api/projects/${P}/graficos`, { cards: [
    { id: 'card-1', title: 'Prazo de 15 dias úteis', body: null, at: 1, dur: 2, material: null }] });
  await irPasso(pg, 'estilo');
  await abrirAba(pg, 'efeitos');
  await pg.waitForSelector('#grade-efeitos .estilo-cartao');
  const r = {};
  // calendario: escolha, numero inteiro com limites, lista e texto
  await pg.click('#grade-efeitos [data-id="calendario"] .estilo-adicionar');
  await pg.waitForSelector('#efeito-form');
  r.rotulos = await pg.$$eval('#efeito-form label, #efeito-form legend', (ls) => ls.map((l) => l.textContent));
  r.ajudas = await pg.$$eval('#efeito-form .ajuda', (ls) => ls.map((l) => l.textContent));
  r.maxlegenda = await pg.$eval('#ef-legenda', (i) => i.getAttribute('maxlength'));
  r.momentoInicial = await pg.$eval('#efeito-momento', (i) => i.value);
  r.duracaoInicial = await pg.$eval('#efeito-duracao', (i) => i.value);
  await pg.fill('#ef-ano', '3000');
  await pg.click('#efeito-salvar');
  await pg.waitForSelector('#efeito-form .campo-erro:not([hidden])');
  r.errosCampos = await pg.$$eval('#efeito-form .campo-erro:not([hidden])', (ls) => ls.map((l) => l.textContent));
  r.erroGeral = await pg.$eval('#efeito-erro', (e) => (e.hidden ? '' : e.textContent));
  r.focoNoPrimeiroErro = await pg.evaluate(() => document.activeElement.id);
  await pg.fill('#ef-ano', '2026');
  await pg.selectOption('#ef-mes', 'março');
  await pg.fill('#efeito-duracao', '9');
  await pg.fill('#efeito-form fieldset input >> nth=0', '5');
  for (let i = 0; i < 12; i++) {
    const b = await pg.$('#efeito-form .estilo-lista button:has-text("Adicionar item"):not([disabled])');
    if (!b) break;
    await b.click();
  }
  r.itensDias = await pg.$$eval('#efeito-form fieldset .estilo-item', (ls) => ls.length);
  r.adicionarDesligado = await pg.$eval('#efeito-form fieldset > button', (b) => b.disabled);
  await pg.click('#efeito-salvar');
  await pg.waitForSelector('#efeito-erro:not([hidden])');
  r.erroDuracao = await pg.$eval('#efeito-erro', (e) => e.textContent);
  await pg.click('#efeito-cancelar');
  r.formFechou = !(await pg.$('#efeito-form'));

  // palavra-destaque: preenche, erro do servidor por extenso, depois salva
  await pg.click('#grade-efeitos [data-id="palavra-destaque"] .estilo-adicionar');
  await pg.waitForSelector('#efeito-form');
  await pg.fill('#ef-palavra', 'PRAZO');
  await pg.fill('#efeito-momento', '40');
  await pg.fill('#efeito-duracao', '1,5');
  await pg.click('#efeito-salvar');
  await pg.waitForSelector('#efeito-erro:not([hidden])');
  r.erroServidor = await pg.$eval('#efeito-erro', (e) => e.textContent);
  r.palavraGravada = await pg.$eval('#ef-palavra', (i) => i.value);
  await pg.fill('#efeito-momento', '1,5');
  await pg.click('#efeito-salvar');
  await pg.waitForSelector('#efeitos-no-video .estilo-no-video-item');
  r.graficosDepois = (await api(srvA, 'GET', `/api/projects/${P}/graficos`)).json.cards;
  r.listados = await pg.$$eval('#efeitos-no-video .estilo-no-video-item', (ls) => ls.map((l) => l.textContent));

  // polaroides: imagem = quadro do video, com o segundo escolhido
  await pg.click('#grade-efeitos [data-id="polaroides"] .estilo-adicionar');
  await pg.waitForSelector('#efeito-form');
  await pg.selectOption('#efeito-form .estilo-imagem select', 'quadro');
  r.segundoPadrao = await pg.$eval('#efeito-form .estilo-segundo', (i) => i.value);
  await pg.fill('#efeito-form .estilo-segundo', '2');
  await pg.fill('#efeito-momento', '0,5');
  await pg.fill('#efeito-duracao', '2');
  await pg.click('#efeito-salvar');
  await esperar(async () => (await api(srvA, 'GET', `/api/projects/${P}/graficos`)).json.cards.length === 3, 20000, 100);
  r.polaroide = (await api(srvA, 'GET', `/api/projects/${P}/graficos`)).json.cards.find((c) => c.efeito === 'polaroides');

  // o passo Graficos mostra o efeito sem quebrar
  await irPasso(pg, 'graficos');
  await pg.waitForSelector('#cards-lista .card-item');
  r.graficosItens = await pg.$$eval('#cards-lista .card-titulo', (ls) => ls.map((l) => l.textContent));

  // remover
  await irPasso(pg, 'estilo');
  await abrirAba(pg, 'efeitos');
  await pg.waitForSelector('#efeitos-no-video .estilo-no-video-item >> nth=1');
  const antes = await pg.$$eval('#efeitos-no-video .efeito-remover', (b) => b.length);
  await pg.click('#efeitos-no-video .efeito-remover >> nth=0');
  await esperar(async () => (await pg.$$('#efeitos-no-video .efeito-remover')).length === antes - 1, 20000, 100);
  r.depoisRemover = (await api(srvA, 'GET', `/api/projects/${P}/graficos`)).json.cards.map((c) => c.id);
  r.erros2 = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== largura 375 + capturas
await cenario('scroll375', async () => {
  const ctx = await contexto({ viewport: { width: 375, height: 812 } });
  const pg = await abrir(ctx, srvA, P);
  const medidas = {};
  const alvos = [];
  const medir = async (tela) => {
    medidas[tela] = await semRolagem(pg);
    alvos.push(...await pg.$$eval('#painel button, #painel input, #painel textarea, #painel select, #painel summary',
      (els, t) => els.filter((e) => e.offsetParent !== null && !e.closest('.sr-only')).map((e) => {
        const b = e.getBoundingClientRect();
        return { tela: t, id: e.id || e.className, w: b.width, h: b.height };
      }), tela));
  };
  await irPasso(pg, 'estilo');
  await exemplosProntos(pg, 'paletas', 4);
  await medir('paletas');
  await screenshot(pg, 'estilo-paletas-375.png');
  await abrirAba(pg, 'fontes'); await medir('fontes');
  await abrirAba(pg, 'legendas'); await exemplosProntos(pg, 'legendas', 4); await medir('legendas');
  await abrirAba(pg, 'efeitos'); await exemplosProntos(pg, 'efeitos', 10); await medir('efeitos');
  await pg.click('#grade-efeitos [data-id="polaroides"] .estilo-adicionar');
  await pg.waitForSelector('#efeito-form');
  await medir('efeitos-form');
  await pg.click('#efeito-cancelar');
  await abrirAba(pg, 'notas'); await medir('notas');
  const r = { medidas, alvos, erros: pg.__erros };
  await ctx.close();
  // escuro (so para olhar)
  for (const [larg, alt, nome] of [[1280, 800, 'estilo-paletas-1280-escuro.png'], [375, 812, 'estilo-efeitos-375-escuro.png']]) {
    const c = await contexto({ colorScheme: 'dark', viewport: { width: larg, height: alt } });
    const pe = await abrir(c, srvA, P);
    await irPasso(pe, 'estilo');
    if (larg === 1280) await exemplosProntos(pe, 'paletas', 4);
    else { await abrirAba(pe, 'efeitos'); await exemplosProntos(pe, 'efeitos', 10); await pe.click('#grade-efeitos [data-id="calendario"] .estilo-adicionar'); await pe.waitForSelector('#efeito-form'); }
    await screenshot(pe, nome);
    await c.close();
  }
  return r;
});

// ================================================== banco com item hostil, item invalido e outra fonte
const srvB = await servidor('b', { banco_raiz: cfg.banco_hostil, fonts_dir: cfg.fonts_dir });
await cenario('hostil', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvB, cfg.slugs.hostil);
  await irPasso(pg, 'estilo');
  await pg.waitForSelector('#grade-paletas .estilo-cartao');
  const r = {};
  r.imgsDentroDoTexto = await pg.$$eval('#grade-paletas .estilo-nome img, #grade-paletas .estilo-desc img, #grade-paletas script', (e) => e.length);
  r.nomes = await pg.$$eval('#grade-paletas .estilo-nome', (ls) => ls.map((l) => l.textContent));
  r.descs = await pg.$$eval('#grade-paletas .estilo-desc', (ls) => ls.map((l) => l.textContent));
  r.pwn = await pg.evaluate(() => window.__pwn === undefined);
  await pg.click('#grade-paletas [data-id="hostil"] .estilo-parecido');
  await pg.waitForSelector('#parecidos-paletas .variacao');
  r.imgsNasVariacoes = await pg.$$eval('#parecidos-paletas img, #parecidos-paletas script', (e) => e.length);
  r.variacaoTexto = await pg.$$eval('#parecidos-paletas .variacao strong', (ls) => ls.map((l) => l.textContent));
  r.pwnDepois = await pg.evaluate(() => window.__pwn === undefined);
  r.aviso = await pg.$eval('#aviso-banco summary', (s) => s.textContent);
  r.avisoFechado = await pg.$eval('#aviso-banco details', (d) => !d.open);
  r.avisoMotivos = await pg.$$eval('#aviso-banco li', (ls) => ls.map((l) => l.textContent));
  r.avisoVisivel = await pg.$eval('#aviso-banco', (e) => e.innerText);
  await pg.click('#aviso-banco summary');
  r.avisoAberto = await pg.$eval('#aviso-banco', (e) => e.innerText);
  await abrirAba(pg, 'fontes');
  r.fontes = await pg.$$eval('#lista-fontes .fonte', (ls) => ls.map((l) => ({
    nome: l.dataset.nome, desabilitado: l.querySelector('button').disabled, selo: !!l.querySelector('.selo'),
    aviso: l.querySelector('.ajuda') ? l.querySelector('.ajuda').textContent : '',
  })));
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

out.visivel = { telas: visivel };
await browser.close();
for (const s of srvs) s.parar();
process.stdout.write(JSON.stringify(out));

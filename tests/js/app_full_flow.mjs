// Fluxo unico na tela, do projeto novo ate o Reel final, contra o servidor REAL em modo
// de teste (transcricao falsa). Depois confere uma segunda aba no mesmo projeto.
// Quem afirma e o pytest (tests/test_app_full_flow.py).
//
// Uso: node tests/js/app_full_flow.mjs <config.json>
// config: {tmp, video, brand}
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
const srv = await iniciarServidor({ root: path.join(cfg.tmp, 'projects'), brand: cfg.brand, doctor: DOCTOR_OK,
  test_mode: true }, cfg.tmp, { REEL_APP_FAKE_TRANSCRIBE: '1' });
const out = { externas: [] };

async function contexto() {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  ctx.setDefaultTimeout(30000);
  ctx.on('request', (rq) => {
    const u = rq.url();
    if (/^(data|blob|about):/.test(u)) return;
    if (!/^https?:\/\/127\.0\.0\.1[:/]/.test(u)) out.externas.push(u);
  });
  return ctx;
}
async function abrir(ctx, url) {
  const pg = await ctx.newPage();
  pg.__erros = [];
  pg.on('pageerror', (e) => pg.__erros.push(String(e)));
  pg.on('console', (m) => {
    if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) pg.__erros.push(m.text());
  });
  pg.on('response', (r) => { if (r.status() >= 500) pg.__erros.push(`HTTP ${r.status()} ${r.url()}`); });
  await pg.goto(url);
  await pg.waitForSelector('#painel[data-passo]');
  return pg;
}
const estados = (pg) => pg.$$eval('#passos .passo', (bs) => Object.fromEntries(bs.map((b) => [b.dataset.passo,
  { estado: b.dataset.estado, bloqueado: b.getAttribute('aria-disabled') === 'true' }])));
const ocupado = (pg) => esperar(async () => !(await pg.$('#painel [data-ocupado]')), 20000, 100);
const ocioso = (pg) => esperar(async () => !(await pg.$('#tarefa:not([hidden])[data-estado="rodando"]')), LONGO, 200);
async function irPasso(pg, id) {
  await pg.click(`#passos .passo[data-passo="${id}"]`);
  await pg.waitForSelector(`#painel[data-passo="${id}"]`);
}
async function abrirAba(pg, aba) {
  await pg.click(`#tab-estilo-${aba}`);
  await pg.waitForSelector(`#aba-estilo-${aba}:not([hidden])`);
}
const exemplosProntos = (pg, aba, n) => pg.waitForFunction(([a, k]) => {
  const imgs = [...document.querySelectorAll(`#grade-${a} img.estilo-img`)];
  return imgs.length === k && imgs.every((i) => i.complete && i.naturalWidth > 0);
}, [aba, n], { timeout: LONGO });

let slug = null;
let pg = null;
try {
  const ctx = await contexto();
  pg = await abrir(ctx, srv.url);

  // ---- criar projeto e enviar o video
  await irPasso(pg, 'video');
  await pg.fill('#novo-nome', 'Reel fluxo completo');
  await pg.click('#novo-criar');
  await pg.waitForSelector('#arquivo-video', { state: 'attached' });
  await pg.setInputFiles('#arquivo-video', cfg.video);
  await pg.waitForSelector('#video-info', { timeout: 30000 });
  slug = (await api(srv, 'GET', '/api/projects')).json.find((p) => p.nome === 'Reel fluxo completo').slug;
  out.slug = slug;
  await esperar(async () => (await estados(pg)).video.estado === 'pronto', 20000);

  // ---- reconhecer a fala e cortar uma palavra
  await irPasso(pg, 'cortes');
  await pg.click('#cortes-reconhecer');
  await pg.waitForSelector('#cortes-lista .corte', { timeout: 90000 });
  await ocioso(pg);
  const rev = (await api(srv, 'GET', `/api/projects/${slug}/revisao`)).json;
  const leia = rev.words.find((w) => w.w === 'Leia');
  const btn = `#cortes-palavras .palavra[data-i="${leia.i}"]`;
  await pg.click(btn);
  await esperar(async () => (await pg.getAttribute(btn, 'data-estado')) === 'cortada');
  await ocupado(pg);
  out.cortou = (await api(srv, 'GET', `/api/projects/${slug}/revisao`)).json.cuts
    .some((c) => c.active && c.kind === 'manual' && c.start <= (leia.start + leia.end) / 2 && c.end >= (leia.start + leia.end) / 2);

  // ---- legendas
  await irPasso(pg, 'legendas');
  await pg.waitForSelector('#lista-frases .frase textarea');
  await pg.click('#legendas-confirmar');
  await pg.waitForSelector('#painel[data-passo="preview"]');

  // ---- preview
  await pg.waitForSelector('#preview-gerar');
  await pg.click('#preview-gerar');
  await pg.waitForSelector('#preview-pronto', { timeout: LONGO });
  await esperar(async () => (await pg.$eval('#player-video', (v) => v.getAttribute('src') || '')).includes('preview.mp4'));

  // ---- estilo: paleta, legenda e 1 efeito; aplicar
  await irPasso(pg, 'estilo');
  await pg.waitForSelector('#grade-paletas .estilo-cartao');
  await pg.click('#grade-paletas [data-id="grafite"] .estilo-usar');
  await abrirAba(pg, 'legendas');
  await pg.waitForSelector('#grade-legendas .estilo-cartao');
  await pg.click('#grade-legendas [data-id="faixa-azul"] .estilo-usar');
  await pg.selectOption('#legenda-posicao', 'meio');
  await pg.selectOption('#legenda-tamanho', 'G');
  await abrirAba(pg, 'efeitos');
  await exemplosProntos(pg, 'efeitos', 10);
  await pg.click('#grade-efeitos [data-id="palavra-destaque"] .estilo-adicionar');
  await pg.waitForSelector('#efeito-form');
  await pg.fill('#ef-palavra', 'PRAZO');
  await pg.fill('#efeito-momento', '1,5');
  await pg.fill('#efeito-duracao', '1,5');
  await pg.click('#efeito-salvar');
  await pg.waitForSelector('#efeitos-no-video .estilo-no-video-item');
  await ocioso(pg);
  await esperar(async () => !(await pg.$eval('#estilo-aplicar', (b) => b.disabled)), LONGO, 200);
  await pg.click('#estilo-aplicar');
  await pg.waitForSelector('#tarefa:not([hidden])[data-estado="rodando"]');
  await ocioso(pg);
  await esperar(async () => (await pg.$eval('#estilo-situacao', (e) => e.textContent).catch(() => '')) === 'Estilo aplicado.', 120000, 200);

  // ---- capa
  await irPasso(pg, 'capa');
  await pg.waitForSelector('#capa-achar');
  await pg.click('#capa-achar');
  await pg.waitForSelector('#capa-candidatos .candidato >> nth=2', { timeout: LONGO });
  await pg.waitForFunction(() => [...document.querySelectorAll('#capa-candidatos img')].every((i) => i.complete && i.naturalWidth > 0));
  await pg.click('#capa-candidatos .candidato >> nth=1 >> .candidato-escolher');
  await pg.fill('#capa-gancho', '3 MITOS');
  await pg.fill('#capa-area', 'ISENÇÃO DE IR');
  await pg.fill('#capa-subtitulo', 'sobre a aposentadoria');
  await pg.click('#capa-gerar');
  await pg.waitForSelector('#capa-pronta img', { timeout: LONGO });
  await esperar(async () => (await estados(pg)).capa.estado === 'pronto', 30000);

  // ---- final
  await irPasso(pg, 'final');
  await pg.waitForSelector('#final-gerar');
  await pg.click('#final-gerar');
  await ocioso(pg);
  await esperar(async () => (await pg.$eval('#player-video', (v) => v.getAttribute('src') || '')).includes('final.mp4'), LONGO, 200);
  await pg.waitForSelector('#final-arquivos li');
  out.passos = await estados(pg);
  out.arquivosFinal = await pg.$$eval('#final-arquivos li', (lis) => lis.map((l) => l.textContent.replace(/\s+/g, ' ').trim()));
  out.estilo = JSON.parse(fs.readFileSync(path.join(srv.root, slug, 'estilo.json'), 'utf-8'));
  out.graficos = JSON.parse(fs.readFileSync(path.join(srv.root, slug, 'graficos.json'), 'utf-8'));
  out.errosAba1 = pg.__erros.slice();
  out.estado1 = (await api(srv, 'GET', `/api/projects/${slug}`)).json;

  // ---- segunda aba (outro contexto) no mesmo projeto
  const ctx2 = await contexto();
  const pg2 = await ctx2.newPage();
  pg2.__erros = [];
  pg2.on('pageerror', (e) => pg2.__erros.push(String(e)));
  pg2.on('console', (m) => { if (m.type() === 'error' && !m.text().startsWith('Failed to load resource')) pg2.__erros.push(m.text()); });
  await pg2.addInitScript((s) => { try { localStorage.setItem('editor-reels:ultimo-projeto', s); } catch { /* sem storage */ } }, slug);
  await pg2.goto(srv.url);
  await pg2.waitForSelector('#painel[data-passo]');
  await esperar(async () => (await estados(pg2)).final.estado === 'pronto', 20000);
  out.passos2 = await estados(pg2);
  out.estado2 = (await api(srv, 'GET', `/api/projects/${slug}`)).json;
  await irPasso(pg2, 'final');
  await pg2.waitForSelector('#final-arquivos li');
  out.arquivosFinal2 = await pg2.$$eval('#final-arquivos li', (lis) => lis.map((l) => l.textContent.replace(/\s+/g, ' ').trim()));
  await irPasso(pg2, 'estilo');
  await pg2.waitForSelector('#efeitos-no-video, #grade-paletas');
  await abrirAba(pg2, 'efeitos');
  await pg2.waitForSelector('#efeitos-no-video .estilo-no-video-item');
  out.efeitos2Antes = (await pg2.$$('#efeitos-no-video .estilo-no-video-item')).length;

  // acao da aba 1: remove o efeito; a aba 2 ve ao recarregar
  await irPasso(pg, 'estilo');
  await abrirAba(pg, 'efeitos');
  await pg.waitForSelector('#efeitos-no-video .efeito-remover');
  await pg.click('#efeitos-no-video .efeito-remover >> nth=0');
  await esperar(async () => (await api(srv, 'GET', `/api/projects/${slug}/graficos`)).json.cards.length === 0, 30000, 100);
  await pg2.reload();
  await pg2.waitForSelector('#painel[data-passo]');
  await irPasso(pg2, 'estilo');
  await abrirAba(pg2, 'efeitos');
  await pg2.waitForSelector('#grade-efeitos .estilo-cartao');
  out.efeitos2Depois = (await pg2.$$('#efeitos-no-video .estilo-no-video-item')).length;
  out.errosAba2 = pg2.__erros.slice();
  out.errosAba1Final = pg.__erros.slice();
  await ctx2.close();
  await ctx.close();
} catch (e) {
  let painel = '';
  try { painel = pg ? (await pg.textContent('#painel', { timeout: 1000 })).replace(/\s+/g, ' ') : ''; } catch { /* sem pagina */ }
  out.error = String(e && e.stack || e) + (painel ? `\n[painel] ${painel.slice(0, 1500)}` : '');
}
await browser.close();
srv.parar();
process.stdout.write(JSON.stringify(out));

// Teste de tela dos passos Gráficos (com a aba Materiais) e Capa contra o servidor
// REAL em modo de teste. Os projetos chegam prontos ate o Preview (montados no pytest).
//
// Uso: node tests/js/app_flow_b.mjs <config.json>
// config: {tmp, screens, foto, svg, roots: {com, sem}, brands: {com, sem}, slugs, mensagens_js}
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

const browser = await chromium.launch();
const out = {};
const srvs = [];
const visivel = {};
let page = null;

async function servidor(qual) {
  const s = await iniciarServidor({ root: cfg.roots[qual], brand: cfg.brands[qual], doctor: DOCTOR_OK, test_mode: true }, cfg.tmp);
  srvs.push(s);
  return s;
}

async function contexto(opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...opts });
  ctx.setDefaultTimeout(20000);
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

const estados = (pg) => pg.$$eval('#passos .passo', (bs) => Object.fromEntries(bs.map((b) => [b.dataset.passo, {
  estado: b.dataset.estado, bloqueado: b.getAttribute('aria-disabled') === 'true',
}])));

const semRolagem = (pg) => pg.evaluate(() => ({
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
  bodyScroll: document.body.scrollWidth,
}));

const textoVisivel = (pg) => pg.evaluate(() => document.body.innerText);

async function screenshot(pg, nome) {
  if (!cfg.screens) return;
  fs.mkdirSync(cfg.screens, { recursive: true });
  await pg.evaluate(() => document.fonts.ready.then(() => true));
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

const graficos = async (srv, slug) => (await api(srv, 'GET', `/api/projects/${slug}/graficos`)).json;
const ocioso = (pg) => esperar(async () => !(await pg.$('#tarefa:not([hidden])[data-estado="rodando"]')), 120000, 200);

const srvC = await servidor('com');
const srvS = await servidor('sem');
const G = cfg.slugs.graficos;
const C = cfg.slugs.capa;

// ================================================== gráficos e materiais
await cenario('graficos', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvC, G);
  const r = { bloqueado: (await estados(pg)).graficos.bloqueado };
  await irPasso(pg, 'graficos');
  await pg.waitForSelector('#tab-materiais');
  // ---- materiais
  await pg.click('#tab-materiais');
  await pg.setInputFiles('#arquivo-material', [cfg.foto, cfg.svg]);
  await pg.waitForSelector('#materiais-lista .material >> nth=1');
  await esperar(async () => (await pg.$('#materiais-enviando')) && pg.$eval('#materiais-enviando', (e) => e.hidden));
  r.materiais = await pg.$$eval('#materiais-lista .material', (ls) => ls.map((l) => l.dataset.nome));
  r.miniaturas = await pg.$$eval('#materiais-lista img', (is) => is.map((i) => i.getAttribute('src')));
  r.svgEmbutido = await pg.$$eval('#painel svg', (ss) => ss.filter((s) => !s.classList.contains('icone-traco')).length);
  await pg.waitForFunction(() => [...document.querySelectorAll('#materiais-lista img')].every((i) => i.complete));
  r.tituloPagina = await pg.title();
  visivel.materiais = await textoVisivel(pg);
  await screenshot(pg, 'materiais-1280.png');
  // o svg aberto direto no navegador nao roda o script (CSP sandbox)
  const aba = await ctx.newPage();
  await aba.goto(srvC.base + r.miniaturas.find((s) => s.includes('.svg')));
  await aba.waitForTimeout(300);
  r.tituloSvgAberto = await aba.title();
  await aba.close();

  // ---- cards
  await pg.click('#tab-cards');
  await pg.waitForSelector('#cards-vazio');
  await pg.click('#card-adicionar');
  await pg.waitForSelector('#card-form');
  await pg.click('#card-salvar');
  r.erroVazio = (await pg.textContent('#card-erro')).trim();
  // erro do servidor (titulo longo demais) aparece traduzido e o texto digitado fica
  await pg.$eval('#card-titulo', (i) => i.removeAttribute('maxlength'));
  await pg.fill('#card-titulo', 'x'.repeat(61));
  await pg.click('#card-salvar');
  await pg.waitForFunction(() => /letras/.test(document.querySelector('#card-erro').textContent));
  r.erroServidor = (await pg.textContent('#card-erro')).trim();
  r.textoNaoSumiu = await pg.inputValue('#card-titulo');
  await pg.fill('#card-titulo', 'Prazo de 15 dias úteis');
  await pg.fill('#card-texto', 'Conte só os dias de expediente.');
  await pg.fill('#card-momento', '1,5');
  await pg.selectOption('#card-duracao', '4');
  await pg.selectOption('#card-imagem', 'materiais/Retrato-do-Dr-Silva.png');
  await pg.waitForSelector('.card-imagem-previa img');
  await screenshot(pg, 'graficos-form-1280.png');
  await pg.click('#card-salvar');
  await pg.waitForSelector('#cards-lista .card-item');
  await pg.click('#card-adicionar');
  await pg.fill('#card-titulo', 'Guarde os comprovantes');
  await pg.fill('#card-momento', '3');
  await pg.click('#card-salvar');
  await pg.waitForSelector('#cards-lista .card-item >> nth=1');
  r.depoisAdicionar = (await graficos(srvC, G)).cards;
  // editar
  await pg.click('#cards-lista .card-item[data-id="card-1"] .card-editar');
  await pg.fill('#card-titulo', 'Prazo de 15 dias corridos');
  await pg.click('#card-salvar');
  await pg.waitForSelector('#cards-lista .card-item[data-id="card-1"] .card-titulo:has-text("corridos")');
  r.depoisEditar = (await graficos(srvC, G)).cards;
  // manter / tirar do video (decisao da revisao)
  await pg.click('#cards-lista .card-item[data-id="card-2"] .card-manter');
  await pg.waitForSelector('#cards-lista .card-item[data-id="card-2"][data-fica="false"]');
  r.decisaoFora = (await graficos(srvC, G)).decisoes['card-2'];
  r.listaFica = await pg.getAttribute('#cards-lista .card-item[data-id="card-2"]', 'data-fica');
  await screenshot(pg, 'graficos-1280.png');
  visivel.graficos = await textoVisivel(pg);
  await pg.click('#cards-lista .card-item[data-id="card-2"] .card-manter');
  await pg.waitForSelector('#cards-lista .card-item[data-id="card-2"][data-fica="true"]');
  r.decisaoVolta = (await graficos(srvC, G)).decisoes['card-2'];
  // remover
  await pg.click('#cards-lista .card-item[data-id="card-2"] .card-remover');
  await esperar(async () => (await pg.$$('#cards-lista .card-item')).length === 1);
  r.depoisRemover = (await graficos(srvC, G)).cards;
  r.itensNaTela = (await pg.$$('#cards-lista .card-item')).length;
  // apagar material
  await pg.click('#tab-materiais');
  await pg.click('#materiais-lista .material[data-nome="icone-com-script.svg"] .material-apagar');
  await esperar(async () => (await pg.$$('#materiais-lista .material')).length === 1);
  r.materiaisDepoisApagar = await pg.$$eval('#materiais-lista .material', (ls) => ls.map((l) => l.dataset.nome));
  await esperar(async () => (await estados(pg)).graficos.estado === 'pronto');
  r.passoGraficos = (await estados(pg)).graficos.estado;
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== capa
await cenario('capa', async () => {
  // uma foto nos materiais (enviada pela API) para o "Usar esta foto"
  const up = await fetch(`${srvC.base}/api/projects/${C}/materiais`, {
    method: 'PUT', headers: { 'X-Token': srvC.token, 'X-Filename': encodeURIComponent('retrato.png') },
    body: fs.readFileSync(cfg.foto),
  });
  if (up.status !== 201) throw new Error('envio da foto falhou ' + up.status);
  const ctx = await contexto();
  const pg = await abrir(ctx, srvC, C);
  await irPasso(pg, 'capa');
  await pg.waitForSelector('#capa-sem-sorriso');
  const r = { avisoSorriso: (await pg.textContent('#capa-sem-sorriso')).replace(/\s+/g, ' ').trim() };
  r.finalBloqueado = (await estados(pg)).final.bloqueado;
  await screenshot(pg, 'capa-vazia-1280.png');
  await pg.click('#capa-achar');
  await pg.waitForSelector('#capa-candidatos .candidato >> nth=2', { timeout: 120000 });
  r.candidatos = (await pg.$$('#capa-candidatos .candidato')).length;
  await pg.waitForFunction(() => [...document.querySelectorAll('#capa-candidatos img')].every((i) => i.complete && i.naturalWidth > 0));
  r.imgsCandidatos = (await pg.$$('#capa-candidatos img')).length;
  r.larguras = await pg.$$eval('#capa-candidatos img', (is) => is.map((i) => i.naturalWidth));
  await pg.click('#capa-candidatos .candidato[data-rel="capa/candidato-2.png"] .candidato-escolher');
  r.escolhido = await pg.getAttribute('#capa-candidatos .candidato[data-escolhido="true"]', 'data-rel');
  await pg.fill('#capa-gancho', '3 MITOS');
  await pg.fill('#capa-area', 'ISENÇÃO DE IR');
  await pg.fill('#capa-subtitulo', 'sobre a aposentadoria');
  await pg.click('#capa-gerar');
  await pg.waitForSelector('#capa-pronta img', { timeout: 120000 });
  await pg.waitForFunction(() => { const i = document.querySelector('#capa-pronta img'); return i.complete && i.naturalWidth > 0; });
  r.pronta = await pg.$eval('#capa-pronta img', (i) => ({ naturalWidth: i.naturalWidth, naturalHeight: i.naturalHeight }));
  r.baixar = await pg.$eval('#capa-baixar', (a) => ({ href: a.getAttribute('href'), download: a.getAttribute('download') }));
  await esperar(async () => (await estados(pg)).capa.estado === 'pronto');
  r.passoCapa = (await estados(pg)).capa.estado;
  visivel.capa = await textoVisivel(pg);
  await screenshot(pg, 'capa-1280.png');
  // foto dos materiais
  await pg.selectOption('#capa-foto', 'materiais/retrato.png');
  await pg.click('#capa-usar-foto');
  await pg.waitForSelector('#capa-candidatos .candidato[data-rel="capa/foto.png"]', { timeout: 60000 });
  r.fotoEscolhida = await pg.getAttribute('#capa-candidatos .candidato[data-escolhido="true"]', 'data-rel');
  // gancho longo demais (o campo limita; aqui forçado): erro do script por extenso
  await ocioso(pg);
  await pg.$eval('#capa-gancho', (i) => i.removeAttribute('maxlength'));
  await pg.fill('#capa-gancho', 'GANCHO GANCHO GANCHO GANCHO GANCHO GANC');
  await pg.click('#capa-gerar');
  await pg.waitForSelector('#tarefa[data-estado="erro"]', { timeout: 60000 });
  r.erroGancho = (await pg.textContent('#tarefa .tarefa-sub')).trim();
  // recarregar a pagina mantem os textos (sessionStorage); achar de novo limpa a escolha
  await pg.reload();
  await pg.waitForSelector('#painel[data-passo]');
  await irPasso(pg, 'capa');
  await pg.waitForSelector('#capa-gancho');
  r.ganchoDepoisF5 = await pg.inputValue('#capa-gancho');
  r.escolhidoDepoisF5 = await pg.getAttribute('#capa-candidatos .candidato[data-escolhido="true"]', 'data-rel');
  await pg.click('#capa-achar');
  // Esperar por CONDICAO, nao por tempo: a tarefa "achar quadros" ainda pode nao ter aparecido
  // (o POST nao voltou) e os quadros antigos ja estao na grade; ler o estado nesse instante
  // pegava a escolha antiga (corrida do teste). A escolha so e apagada quando a tarefa termina
  // e a tela e redesenhada: espera-se esse desfecho e depois a tarefa ficar ociosa.
  await esperar(async () => (await pg.$$('#capa-candidatos .candidato[data-escolhido="true"]')).length === 0, 120000, 100);
  await ocioso(pg);
  await pg.waitForSelector('#capa-candidatos .candidato >> nth=2');
  r.escolhidosDepoisAchar = (await pg.$$('#capa-candidatos .candidato[data-escolhido="true"]')).length;
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== sem @ salvo
await cenario('semArroba', async () => {
  const ctx = await contexto();
  const pg = await abrir(ctx, srvS, cfg.slugs.semArroba);
  const r = { passos: await estados(pg) };
  await irPasso(pg, 'capa');
  await pg.waitForSelector('#capa-sem-arroba');
  r.aviso = (await pg.textContent('#capa-sem-arroba p')).trim();
  r.botao = (await pg.textContent('#capa-ir-instalacao')).trim();
  r.gerarDesligado = await pg.$eval('#capa-gerar', (b) => b.disabled);
  r.falta = (await pg.textContent('#capa-falta')).trim();
  await screenshot(pg, 'capa-sem-arroba-1280.png');
  await pg.click('#capa-ir-instalacao');
  await pg.waitForSelector('#painel[data-passo="instalacao"]');
  r.depoisClique = await pg.getAttribute('#painel', 'data-passo');
  r.erros = pg.__erros;
  await ctx.close();
  return r;
});

// ================================================== 375 px
await cenario('scroll375', async () => {
  const ctx = await contexto({ viewport: { width: 375, height: 800 } });
  const pg = await abrir(ctx, srvC, C);
  const medidas = {};
  const alvos = [];
  const medir = async (tela) => {
    medidas[tela] = await semRolagem(pg);
    alvos.push(...await pg.$$eval('#painel button, #painel input, #painel textarea, #painel select, #painel a.botao, #painel [role="button"]',
      (els, t) => els.filter((e) => e.offsetParent !== null && e.type !== 'file').map((e) => {
        const b = e.getBoundingClientRect();
        return { tela: t, id: e.id || e.className, w: b.width, h: b.height };
      }), tela));
    await screenshot(pg, `${tela}-375.png`);
  };
  // cards de exemplo neste projeto, para a lista aparecer
  await api(srvC, 'PUT', `/api/projects/${C}/graficos`, { cards: [
    { id: 'card-1', title: 'Prazo de 15 dias úteis para recorrer da decisão', body: 'Conte só os dias de expediente do fórum.', at: 1, dur: 3, material: 'materiais/retrato.png' },
    { id: 'card-2', title: 'Guarde os comprovantes', body: null, at: 3.5, dur: 2, material: null }] });
  await irPasso(pg, 'graficos');
  await pg.waitForSelector('#cards-lista .card-item >> nth=1');
  await medir('graficos');
  await pg.click('#card-adicionar');
  await pg.waitForSelector('#card-form');
  await medir('graficos-form');
  await pg.click('#card-cancelar');
  await pg.click('#tab-materiais');
  await pg.waitForSelector('#materiais-lista .material');
  await medir('materiais');
  await irPasso(pg, 'capa');
  await pg.waitForSelector('#capa-candidatos .candidato');
  await pg.waitForSelector('#capa-pronta img');
  await medir('capa');
  const r = { medidas, alvos, erros: pg.__erros };
  await ctx.close();
  // escuro (so screenshot, para olhar)
  const ctxE = await contexto({ colorScheme: 'dark' });
  const pe = await abrir(ctxE, srvC, C);
  await irPasso(pe, 'capa');
  await pe.waitForSelector('#capa-pronta img');
  await screenshot(pe, 'capa-1280-escuro.png');
  await ctxE.close();
  return r;
});

// ================================================== traducao de mensagens
await cenario('mensagens', async () => {
  const m = await import(pathToFileURL(cfg.mensagens_js).href);
  const brutos = [
    'gancho não cabe em 2 linhas: encurte',
    'gancho com 41 caracteres (máximo 28)',
    'gancho com mais de 2 linhas',
    'área com 30 caracteres (máximo 28)',
    'texto longo demais para a capa: encurte o subtítulo',
    "graficos.json, card 1 ('card-2'): título com 61 caracteres (máximo 60)",
    "graficos.json, card 0 ('card-1'): corpo com 150 caracteres (máximo 140)",
    "graficos.json, card 0 ('card-1'): dur deve ser número entre 1 e 6 s",
    "graficos.json, card 0 ('card-1'): at deve ser número >= 0 (segundos do vídeo cortado)",
    "graficos.json, card 0 ('card-1'): material não encontrado: materiais/sumiu.png",
    'card 2: a imagem precisa ser um dos materiais',
    "graficos.json: id repetido 'card-1'",
    'tipo de arquivo não aceito; use png, jpg, webp, svg ou mp4',
    'o conteúdo não é um arquivo png de verdade',
    'arquivo grande demais (máximo 200 MB)',
    'esse material não existe',
    'salve o @ do escritório na Instalação antes de gerar a capa',
    'handles vazio: informe o @ das redes oficiais antes de gerar a capa e salve com: python3 scripts/brand.py',
    'foto pequena demais: 300x400; use uma de pelo menos 600 px no lado menor',
    'nenhum quadro utilizável no vídeo (tudo escuro, estourado ou ilegível)',
    'capa: renderizador indisponível: Chromium do Playwright ausente: npx playwright install chromium',
    'o quadro escolhido não existe mais; procure os quadros de novo',
  ];
  return { pares: brutos.map((b) => [b, m.traduzir(b)]), generica: m.GENERICA };
});

out.visivel = { telas: visivel };
await browser.close();
for (const s of srvs) s.parar();
process.stdout.write(JSON.stringify(out));

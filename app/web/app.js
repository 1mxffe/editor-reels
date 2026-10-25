// Casca da pagina: barra de passos, painel, player e troca de projeto.
// Os passos de verdade vivem em passos/*.js e se registram via registrarPasso.
import {
  EDITOR_FECHADO, ORDEM, TOKEN, TOKEN_VALIDO, api, bloqueios, el, gravarUltimo, icone, lerUltimo, obrigatorio, passo,
  passoPronto, quandoChaveInvalida, registrarPasso, toast, urlArquivo, Erro,
} from './nucleo.js';
import { criarPlayer } from './player.js';
import { descobrir, quandoTerminar } from './tarefa.js';
import './passos/instalacao.js';
import './passos/video.js';
import './passos/cortes.js';
import './passos/legendas.js';
import './passos/preview.js';
import './passos/graficos.js';
import './passos/capa.js';
import './passos/final.js';

export { api, el, toast, registrarPasso, urlArquivo, Erro };

const app = {
  slug: null,
  estado: null,
  atual: null,
  config: null,
  brand: null,
  player: null,
};

// ------------------------------------------------------------------ erro fatal
function fatal(titulo, texto) {
  document.getElementById('fatal-titulo').textContent = titulo;
  document.getElementById('fatal-texto').textContent = texto;
  document.getElementById('fatal').hidden = false;
}

quandoChaveInvalida(() => fatal('A chave de acesso não vale mais',
  'O editor foi reiniciado ou o endereço foi copiado de outra janela. Feche esta aba e abra o editor de novo pelo ícone do Editor de Reels.'));

// ---------------------------------------------------------------- contexto
function ctxPara(id) {
  return {
    passo: id,
    slug: app.slug,
    estado: app.estado,
    /** Projeto aberto AGORA (o `slug` acima e o do momento em que a tela abriu). */
    slugAtual: () => app.slug,
    config: app.config,
    player: app.player,
    api,
    ir,
    atualizar,
    abrirProjeto,
    fecharProjeto,
    get brand() { return app.brand; },
    set brand(v) { app.brand = v; },
  };
}

// ------------------------------------------------------------- barra de passos
function rotuloEstado(estado, bloqueado) {
  if (bloqueado) return 'Bloqueado';
  return { pronto: 'Pronto', andamento: 'Agora', pendente: 'A fazer' }[estado];
}

function pintarPassos() {
  const lista = document.querySelector('#passos ol');
  const trava = bloqueios(app.estado);
  const itens = ORDEM.map((p, i) => {
    const pronto = passoPronto(p.id, app.estado);
    const estado = pronto ? 'pronto' : (app.atual === p.id ? 'andamento' : 'pendente');
    const bloqueado = p.id === 'video' ? false : trava[p.id];
    const marca = pronto ? icone('ok', 'passo-marca') : bloqueado ? icone('cadeado', 'passo-marca')
      : el('span', { class: 'passo-numero' }, String(i + 1));
    const botao = el('button', {
      type: 'button', class: 'passo', 'data-passo': p.id, 'data-estado': estado,
      'aria-disabled': bloqueado ? 'true' : 'false',
      'aria-current': app.atual === p.id ? 'step' : null,
      title: bloqueado ? 'Termine o passo anterior primeiro' : p.resumo,
      onclick: () => ir(p.id),
    },
    el('span', { class: 'passo-bola' }, marca),
    el('span', { class: 'passo-titulo' }, p.titulo),
    el('span', { class: 'passo-estado' }, rotuloEstado(estado, bloqueado)));
    return el('li', {}, botao);
  });
  const foco = document.activeElement && document.activeElement.closest('#passos')
    ? document.activeElement.dataset.passo : null;
  lista.replaceChildren(...itens);
  if (foco) {
    const b = lista.querySelector(`[data-passo="${foco}"]`);
    if (b) b.focus();
  }
  document.getElementById('btn-instalacao').classList.toggle('ativo', app.atual === 'instalacao');
  document.getElementById('btn-instalacao').setAttribute('aria-current', app.atual === 'instalacao' ? 'page' : 'false');
}

function pintarProjeto() {
  const caixa = document.getElementById('projeto-atual');
  if (!app.slug || !app.estado) {
    caixa.replaceChildren();
    return;
  }
  caixa.replaceChildren(
    el('span', { class: 'projeto-rotulo' }, 'Reel'),
    el('strong', { class: 'projeto-nome', title: app.estado.nome }, app.estado.nome),
    el('button', { type: 'button', id: 'btn-trocar-projeto', class: 'botao botao-topo', onclick: fecharProjeto },
      'Outros Reels'));
}

function pintarPlayer() {
  if (!app.player) return;
  const arq = app.estado && app.estado.arquivos;
  document.body.toggleAttribute('data-tem-video', !!(app.slug && arq && (arq.final || arq.preview || arq.entrada)));
  if (!app.slug || !arq) return app.player.limpar();
  const def = passo(app.atual);
  const escolha = def && typeof def.video === 'function' ? def.video(app.estado, app.slug) : null;
  if (escolha && escolha.rel) {
    app.player.definir(app.slug, escolha.rel, { rotulo: escolha.rotulo || '', versao: escolha.versao || '' });
  } else if (arq.final) app.player.definir(app.slug, arq.final, { rotulo: 'Versão final' });
  else if (arq.preview) app.player.definir(app.slug, arq.preview, { rotulo: 'Prévia mais recente' });
  else if (arq.entrada) app.player.definir(app.slug, arq.entrada, { rotulo: 'Vídeo original' });
  else app.player.limpar();
}

// ------------------------------------------------------------ navegacao
function render() {
  const painel = document.getElementById('painel');
  const id = app.atual;
  const def = passo(id);
  const indice = ORDEM.findIndex((p) => p.id === id);
  const topo = el('header', { class: 'painel-topo' },
    el('p', { class: 'sobretitulo' }, indice >= 0 ? `Passo ${indice + 1} de ${ORDEM.length}` : 'Antes de começar'),
    el('h1', { id: 'painel-titulo' }, def.tituloPainel || def.titulo));
  const corpo = el('div', { class: 'painel-corpo' });
  painel.dataset.passo = id;
  document.body.dataset.tela = id;
  painel.setAttribute('aria-labelledby', 'painel-titulo');
  painel.replaceChildren(topo, corpo);
  try {
    def.render(corpo, ctxPara(id));
  } catch (e) {
    console.warn(e);
    corpo.append(el('p', { class: 'mensagem-erro', role: 'alert' },
      'Algo deu errado ao abrir este passo. Recarregue a página; o que você já fez continua guardado.'));
  }
}

/** Abre um passo (ou 'instalacao'). Passo bloqueado so mostra um aviso. */
async function ir(id, { focar = false } = {}) {
  if (id !== 'instalacao' && id !== 'video' && bloqueios(app.estado)[id]) {
    await atualizar({ repintarPainel: false });
    if (bloqueios(app.estado)[id]) {
      toast('Termine o passo anterior antes de abrir este.', 'info');
      return;
    }
  }
  app.atual = id;
  pintarPassos();
  pintarPlayer();
  render();
  if (focar) document.getElementById('painel').focus();
  if (app.slug) atualizar({ repintarPainel: false });
}

/** Recarrega o estado do projeto e repinta barra, cabecalho e player. */
async function atualizar({ repintarPainel = false } = {}) {
  const slug = app.slug;
  if (slug) {
    try {
      const estado = await api('GET', `/api/projects/${encodeURIComponent(slug)}`);
      if (app.slug !== slug) return; // resposta de um Reel que ja nao esta aberto
      app.estado = estado;
    } catch (e) {
      if (app.slug !== slug) return;
      if (e.status === 404 || e.status === 400) {
        toast('Este Reel não existe mais. Escolha outro ou crie um novo.', 'erro');
        fecharProjeto();
        return;
      }
      toast(e.mensagem, 'erro');
    }
  }
  pintarPassos();
  pintarProjeto();
  pintarPlayer();
  if (repintarPainel) render();
}

async function abrirProjeto(slug, { passoInicial = null } = {}) {
  app.slug = slug;
  app.estado = null;
  gravarUltimo(slug);
  descobrir(slug); // trabalho em andamento deste Reel (ex.: depois de recarregar)
  await atualizar();
  if (app.slug !== slug) return; // outro Reel foi aberto enquanto este carregava
  ir(passoInicial || proximoPasso());
}

function fecharProjeto() {
  app.slug = null;
  app.estado = null;
  gravarUltimo(null);
  pintarProjeto();
  pintarPlayer();
  ir('video');
}

function proximoPasso() {
  const trava = bloqueios(app.estado);
  const p = ORDEM.find((x) => !trava[x.id] && obrigatorio(x.id) && !passoPronto(x.id, app.estado));
  return p ? p.id : 'final';
}

// ---------------------------------------------------------------- teclado
function emCampo(alvo) {
  if (!alvo || alvo === document.body) return false;
  return !!alvo.closest('input, textarea, select, button, a, summary, [contenteditable], [role="button"]');
}

document.addEventListener('keydown', (e) => {
  if (e.code !== 'Space' || e.repeat || e.altKey || e.ctrlKey || e.metaKey) return;
  if (emCampo(e.target) || !app.player || !app.player.temVideo()) return;
  e.preventDefault();
  app.player.alternar();
});

// soltar um arquivo fora da area certa nao deve abrir o video no lugar do editor
for (const ev of ['dragover', 'drop']) {
  window.addEventListener(ev, (e) => {
    if (!e.target.closest || !e.target.closest('.soltar')) e.preventDefault();
  });
}

// ------------------------------------------------------------------ batida
// Avisa o editor que a pagina continua aberta; sem batida nem pedido (e sem trabalho
// rodando) ele fecha sozinho depois de 30 minutos. O Chrome atrasa os timers de aba
// escondida, por isso tambem se bate ao voltar para a aba. Uma falha e silenciosa
// (a proxima tenta de novo); varias seguidas mostram que o editor foi fechado.
const BATIDA_MS = 10_000;
const FALHAS_PARA_AVISAR = 3;
let falhasSeguidas = 0;
let avisoFechado = false;
function batida() {
  fetch('/api/heartbeat', { method: 'POST', headers: { 'X-Token': TOKEN }, keepalive: true })
    .then((r) => r.arrayBuffer().then(() => {
      falhasSeguidas = 0;
      if (avisoFechado) { avisoFechado = false; document.getElementById('fatal').hidden = true; }
    }))
    .catch(() => {
      falhasSeguidas += 1;
      if (falhasSeguidas >= FALHAS_PARA_AVISAR && !avisoFechado) {
        avisoFechado = true;
        fatal('O editor foi fechado', EDITOR_FECHADO);
      }
    });
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && TOKEN_VALIDO) batida();
});
window.addEventListener('focus', () => { if (TOKEN_VALIDO) batida(); });

// ----------------------------------------------------------------- inicio
async function iniciar() {
  if (!TOKEN_VALIDO) {
    fatal('Abra o editor pelo ícone', 'Esta página precisa ser aberta pelo ícone do Editor de Reels; ela não tem a chave de acesso.');
    return;
  }
  batida();
  setInterval(batida, BATIDA_MS);
  app.player = criarPlayer();
  pintarPassos();
  let config;
  let brand;
  try {
    [config, brand] = await Promise.all([api('GET', '/api/config'), api('GET', '/api/brand')]);
  } catch (e) {
    if (e.status !== 401) fatal('Não foi possível falar com o editor', e.mensagem);
    return;
  }
  app.config = config;
  app.brand = brand;

  const ultimo = lerUltimo();
  if (ultimo) {
    try {
      app.estado = await api('GET', `/api/projects/${encodeURIComponent(ultimo)}`);
      app.slug = ultimo;
    } catch (e) {
      // so esquece o Reel se ele nao existe mais; queda de rede nao apaga nada
      if (e.status === 404 || e.status === 400) gravarUltimo(null);
    }
  }
  let doctor = null;
  try { doctor = await api('GET', '/api/doctor'); } catch { /* a tela de instalacao tenta de novo */ }
  const precisaInstalar = !brand.completa || !doctor
    || !['READY', 'READY WITH LIMITS'].includes(doctor.estado_codigo);
  pintarProjeto();
  pintarPlayer();
  if (app.slug) descobrir(app.slug);
  ir(precisaInstalar ? 'instalacao' : app.slug ? proximoPasso() : 'video');
}

// fim de um trabalho do Reel aberto: recarrega o estado; a tela repinta se o trabalho e dela
quandoTerminar((slug, job) => {
  if (slug !== app.slug) return;
  const def = passo(app.atual);
  const daTela = !!(def && Array.isArray(def.tarefas) && def.tarefas.includes(job.tipo));
  atualizar({ repintarPainel: daTela });
});

document.getElementById('btn-instalacao').addEventListener('click', () => ir('instalacao', { focar: true }));
iniciar();

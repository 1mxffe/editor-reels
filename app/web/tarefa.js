// Trabalhos longos do Reel (reconhecer a fala, procurar cortes, montar preview/final):
// comecar, acompanhar (consulta a cada segundo), cancelar e retomar depois de recarregar
// a pagina. O acompanhamento vive aqui, fora das telas: trocar de passo nao o interrompe.
import { api, el, relogio } from './nucleo.js';
import { traduzir } from './mensagens.js';

const INTERVALO = 900;
export const ROTULOS = {
  transcrever: 'Reconhecendo a fala do vídeo',
  cortes: 'Procurando pausas e repetições',
  preview: 'Montando o preview',
  final: 'Montando a versão final',
  'capa-candidatos': 'Procurando quadros no vídeo',
  capa: 'Desenhando a capa',
  quadros: 'Preparando os exemplos',
  'aplicar-estilo': 'Aplicando o estilo e montando o preview',
};
const FALHAS = {
  transcrever: 'Não deu para reconhecer a fala.',
  cortes: 'Não deu para procurar os cortes.',
  preview: 'Não deu para montar o preview.',
  final: 'Não deu para montar a versão final.',
  'capa-candidatos': 'Não deu para preparar os quadros.',
  capa: 'Não deu para gerar a capa.',
  quadros: 'Não deu para preparar os exemplos.',
  'aplicar-estilo': 'Não deu para aplicar o estilo.',
};
// o que comeca sozinho quando o anterior termina bem
const SEGUINTE = { transcrever: 'cortes' };

const porReel = new Map(); // slug -> {job, seguindo, ouvintes, versoes, semResposta}
let aoTerminar = () => {};

function reg(slug) {
  if (!porReel.has(slug)) {
    porReel.set(slug, { job: null, seguindo: null, ouvintes: new Set(), versoes: {}, semResposta: false });
  }
  return porReel.get(slug);
}

function avisar(slug) {
  const r = reg(slug);
  for (const fn of [...r.ouvintes]) {
    try { fn(r.job); } catch (e) { console.warn(e); }
  }
}

const pausa = (ms) => new Promise((ok) => setTimeout(ok, ms));

/** Chamado uma vez pelo app: o que fazer quando um trabalho do Reel termina. */
export function quandoTerminar(fn) { aoTerminar = fn; }

/** Ultimo trabalho conhecido do Reel (rodando ou terminado nesta pagina), ou null. */
export function tarefaDe(slug) { return slug ? reg(slug).job : null; }

export function rodando(slug, tipos) {
  const j = tarefaDe(slug);
  return !!(j && j.estado === 'rodando' && (!tipos || tipos.includes(j.tipo)));
}

/** Marca de versao do ultimo arquivo gerado por `tipo` nesta pagina (para recarregar o player). */
export function versaoDe(slug, tipo) { return (slug && reg(slug).versoes[tipo]) || ''; }

export function ouvir(slug, fn) {
  const r = reg(slug);
  r.ouvintes.add(fn);
  return () => r.ouvintes.delete(fn);
}

/** Comeca um trabalho e passa a acompanha-lo. Lanca Erro (com .mensagem) se nao der. */
export async function iniciarTarefa(slug, tipo, opcoes = {}) {
  let resp;
  try {
    resp = await api('POST', `/api/projects/${encodeURIComponent(slug)}/jobs/${tipo}`, opcoes);
  } catch (e) {
    if (e.codigo === 'tarefa_rodando') {
      await descobrir(slug);
      e.mensagem = 'Já tem um trabalho em andamento neste Reel. Espere terminar.';
    } else if (e.codigo === 'revisao_em_andamento') {
      e.mensagem = 'O editor ainda está salvando uma mudança. Tente de novo em alguns segundos.';
    }
    throw e;
  }
  const r = reg(slug);
  r.job = { id: resp.job_id, tipo, estado: 'rodando', mensagem: '', log: [], inicio: new Date().toISOString() };
  avisar(slug);
  seguir(slug, resp.job_id);
  return resp.job_id;
}

/** Procura no servidor um trabalho em andamento do Reel (depois de recarregar a pagina). */
export async function descobrir(slug) {
  const r = reg(slug);
  if (r.seguindo) return;
  let dados;
  try {
    dados = await api('GET', `/api/projects/${encodeURIComponent(slug)}/jobs`);
  } catch {
    return; // sem conexao agora: a tela continua com o que tem
  }
  if (dados && dados.ativo && !r.seguindo) {
    r.job = dados.ativo;
    avisar(slug);
    seguir(slug, dados.ativo.id);
  }
}

export async function cancelarTarefa(slug) {
  const j = tarefaDe(slug);
  if (!j || j.estado !== 'rodando') return;
  await api('POST', `/api/jobs/${encodeURIComponent(j.id)}/cancelar`, {});
  j.cancelando = true;
  avisar(slug);
}

async function seguir(slug, id) {
  const r = reg(slug);
  if (r.seguindo === id) return;
  r.seguindo = id;
  let falhas = 0;
  while (r.seguindo === id) {
    await pausa(INTERVALO);
    let job;
    try {
      job = await api('GET', `/api/jobs/${encodeURIComponent(id)}`);
      falhas = 0;
    } catch (e) {
      if (e.status === 404) {
        job = { ...(r.job || {}), id, estado: 'erro', mensagem: '' };
      } else {
        falhas += 1; // falha passageira: o trabalho pode seguir rodando no servidor
        r.semResposta = falhas > 3;
        avisar(slug);
        continue;
      }
    }
    if (r.seguindo !== id) return;
    r.semResposta = false;
    if (r.job && r.job.id === id && r.job.cancelando) job.cancelando = true;
    if (job.estado === 'rodando') {
      r.job = job;
      avisar(slug);
      continue;
    }
    r.seguindo = null;
    if (job.estado === 'ok') r.versoes[job.tipo === 'aplicar-estilo' ? 'preview' : job.tipo] = job.fim || String(Date.now());
    const prox = job.estado === 'ok' && SEGUINTE[job.tipo];
    if (prox) {
      try {
        await iniciarTarefa(slug, prox);
        aoTerminar(slug, job);
        return;
      } catch (e) {
        job = { tipo: prox, estado: 'erro', mensagem: e.mensagem || '', log: [] };
      }
    }
    r.job = job;
    avisar(slug);
    aoTerminar(slug, job);
    return;
  }
}

// ------------------------------------------------------------ tela
function decorrido(job) {
  const t = Date.parse(job.inicio || '');
  return Number.isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null;
}

/**
 * Quadro do trabalho em andamento (ou do ultimo que deu errado/foi cancelado) para os
 * `tipos` dados. `aoMudar(ocupado)` avisa a tela para esconder os botoes enquanto roda.
 */
export function quadroTarefa(slug, tipos, { aoMudar = () => {}, extra = {} } = {}) {
  const titulo = el('p', { id: 'tarefa-texto', class: 'tarefa-titulo' });
  const sub = el('p', { class: 'tarefa-sub suave' });
  const barra = el('div', { class: 'barra-andando', 'aria-hidden': 'true' }, el('span'));
  const cancelar = el('button', { type: 'button', id: 'tarefa-cancelar', class: 'botao botao-secundario' }, 'Cancelar');
  const log = el('pre', { class: 'tarefa-log' });
  const detalhes = el('details', { class: 'detalhes tarefa-detalhes' }, el('summary', {}, 'Detalhes'), log);
  const caixa = el('div', { id: 'tarefa', class: 'cartao tarefa', hidden: true, 'aria-live': 'polite' },
    el('div', { class: 'tarefa-linha' }, el('div', { class: 'tarefa-textos' }, titulo, sub), cancelar),
    barra, detalhes);
  let relogioTela = null;

  cancelar.addEventListener('click', async () => {
    cancelar.disabled = true;
    try {
      await cancelarTarefa(slug);
    } catch (e) {
      cancelar.disabled = false;
      sub.textContent = e.mensagem;
    }
  });

  function pintar(job) {
    if (!caixa.isConnected && caixa.dataset.montado) { parar(); return; }
    const meu = job && tipos.includes(job.tipo) ? job : null;
    const ativo = !!(meu && meu.estado === 'rodando');
    const mostrar = ativo || !!(meu && (meu.estado === 'erro' || meu.estado === 'cancelado'));
    caixa.hidden = !mostrar;
    caixa.dataset.estado = meu ? meu.estado : '';
    aoMudar(ativo);
    if (!mostrar) { pararRelogio(); return; }
    const linhas = Array.isArray(meu.log) ? meu.log : [];
    if (log.textContent !== linhas.join('\n')) log.textContent = linhas.join('\n');
    detalhes.hidden = linhas.length === 0;
    barra.hidden = !ativo;
    cancelar.hidden = !ativo;
    if (ativo) {
      cancelar.disabled = !!meu.cancelando;
      titulo.textContent = meu.cancelando ? 'Cancelando…' : `${ROTULOS[meu.tipo] || 'Trabalhando'}…`;
      const seg = decorrido(meu);
      const partes = [];
      if (seg !== null) partes.push(`Começou há ${relogio(seg)}.`);
      if (reg(slug).semResposta) partes.push('Sem resposta do editor; tentando de novo…');
      else if (extra[meu.tipo]) partes.push(extra[meu.tipo]);
      else partes.push('Pode trocar de passo; o trabalho continua.');
      sub.textContent = partes.join(' ');
      if (!relogioTela) relogioTela = setInterval(() => pintar(tarefaDe(slug)), 1000);
    } else {
      pararRelogio();
      if (meu.estado === 'cancelado') {
        titulo.textContent = 'Cancelado.';
        sub.textContent = 'Nada foi alterado. Quando quiser, comece de novo.';
      } else {
        titulo.textContent = FALHAS[meu.tipo] || 'Não deu certo.';
        // "a tarefa falhou (codigo N)" nao explica nada: o motivo fica nos detalhes
        const msg = /^a tarefa falhou/i.test(meu.mensagem || '') ? '' : meu.mensagem;
        if (msg) sub.textContent = traduzir(msg);
        else sub.textContent = linhas.length ? 'Abra os detalhes para ver o que aconteceu, ou tente de novo.' : 'Tente de novo.';
      }
    }
  }

  function pararRelogio() {
    if (relogioTela) { clearInterval(relogioTela); relogioTela = null; }
  }
  const sair = ouvir(slug, (job) => pintar(job));
  function parar() { pararRelogio(); sair(); }

  // primeira pintura depois de entrar na pagina
  queueMicrotask(() => { caixa.dataset.montado = '1'; pintar(tarefaDe(slug)); });
  pintar(tarefaDe(slug));
  return caixa;
}

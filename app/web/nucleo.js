// Nucleo da pagina: chamadas a API, criacao de elementos (sempre textContent),
// avisos e o registro dos passos. Os modulos de passo (passos/*.js) importam daqui.

const META = document.querySelector('meta[name="reel-token"]');
export const TOKEN = (META && META.content) || '';
export const TOKEN_VALIDO = TOKEN !== '' && TOKEN !== '{{TOKEN}}';

/** Erro de chamada a API com mensagem pronta para mostrar (`.mensagem`). */
export class Erro extends Error {
  constructor(mensagem, status = 0, codigo = null) {
    super(mensagem);
    this.mensagem = mensagem;
    this.status = status;
    this.codigo = codigo;
  }
}

const SEM_CONEXAO = 'Sem conexão com o editor. Confira se a janela do editor continua aberta e tente de novo.';
let aoPerderChave = () => {};

/** Chamado uma vez pelo app: o que fazer quando o servidor recusa a chave (401). */
export function quandoChaveInvalida(fn) { aoPerderChave = fn; }

/** Primeira letra maiuscula e ponto final, para mensagens vindas do servidor. */
export function frase(texto) {
  const t = String(texto || '').trim();
  if (!t) return '';
  const f = t[0].toUpperCase() + t.slice(1);
  return /[.!?…]$/.test(f) ? f : f + '.';
}

/** api(metodo, caminho, corpo?) -> json. Manda X-Token; lanca Erro com .mensagem. */
export async function api(metodo, caminho, corpo) {
  const opts = { method: metodo, headers: { 'X-Token': TOKEN } };
  if (corpo !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(corpo);
  }
  let resp;
  try {
    resp = await fetch(caminho, opts);
  } catch {
    throw new Erro(SEM_CONEXAO);
  }
  let dados = null;
  try { dados = await resp.json(); } catch { /* sem corpo JSON */ }
  if (!resp.ok) {
    if (resp.status === 401) aoPerderChave();
    const msg = dados && typeof dados.erro === 'string' ? frase(dados.erro)
      : `O editor respondeu com um erro (${resp.status}). Tente de novo.`;
    throw new Erro(msg, resp.status, dados && dados.codigo);
  }
  return dados;
}

/** URL de um arquivo do projeto para <video>/<img> (a chave vai no endereco). */
export function urlArquivo(slug, rel, versao) {
  const v = versao ? `&v=${encodeURIComponent(versao)}` : '';
  return `/api/projects/${encodeURIComponent(slug)}/arquivos/${rel.split('/').map(encodeURIComponent).join('/')}`
    + `?t=${encodeURIComponent(TOKEN)}${v}`;
}

const SVG = 'http://www.w3.org/2000/svg'; // namespace, nao e endereco de rede

/**
 * el(tag, props, ...filhos): cria um elemento. Texto SEMPRE por textContent/nos de
 * texto; nunca HTML. props: class, text, on<evento>, dataset, hidden e atributos.
 */
export function el(tag, props, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = String(v);
    else if (k === 'dataset') Object.assign(e.dataset, v);
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
    else if (k === 'hidden') e.hidden = true;
    else if (k in e && typeof v !== 'string') e[k] = v;
    else e.setAttribute(k, v === true ? '' : String(v));
  }
  for (const f of filhos.flat()) {
    if (f === null || f === undefined || f === false) continue;
    e.append(f instanceof Node ? f : document.createTextNode(String(f)));
  }
  return e;
}

const ICONES = {
  ok: ['M5 12.5l4.5 4.5L19 7.5'],
  falta: ['M7 7l10 10', 'M17 7L7 17'],
  cadeado: ['M7 11V8a5 5 0 0 1 10 0v3', 'M5.5 11h13v9.5h-13z'],
  seta: ['M5 12h14', 'M13 6l6 6-6 6'],
  enviar: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 15v4.5h16V15'],
  relogio: ['M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17Z', 'M12 7.5V12l3 2'],
  video: ['M6 2.5h12v19H6z', 'M10.5 9.5v5l4-2.5z'],
  copiar: ['M8.5 8.5h11v11h-11z', 'M15.5 8.5v-4h-11v11h4'],
  atualizar: ['M19.5 12a7.5 7.5 0 1 1-2.2-5.3', 'M19.5 4v4.5H15'],
  pasta: ['M3.5 6.5h6l2 2h9v10h-17z'],
};

/** Icone de traco (SVG montado por createElementNS, sem HTML). */
export function icone(nome, classe = 'icone') {
  const s = document.createElementNS(SVG, 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('aria-hidden', 'true');
  s.setAttribute('class', classe + ' icone-traco');
  for (const d of ICONES[nome] || []) {
    const p = document.createElementNS(SVG, 'path');
    p.setAttribute('d', d);
    s.append(p);
  }
  return s;
}

/** Aviso passageiro no canto da tela. tipo: 'info' | 'ok' | 'erro'. */
export function toast(msg, tipo = 'info') {
  const caixa = document.getElementById('toasts');
  if (!caixa) return;
  const t = el('div', { class: `toast toast-${tipo}` }, msg);
  caixa.append(t);
  setTimeout(() => t.classList.add('saindo'), 4500);
  setTimeout(() => t.remove(), 5000);
}

/** Tamanho em MB por extenso no formato brasileiro (2,5 MB; 1,2 GB). */
export function tamanho(bytes) {
  const fmt = (n) => n.toLocaleString('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 });
  if (bytes >= 1024 ** 3) return `${fmt(bytes / 1024 ** 3)} GB`;
  return `${fmt(bytes / 1024 ** 2)} MB`;
}

/** 75.4 -> "1:15" */
export function relogio(seg) {
  if (!Number.isFinite(seg) || seg < 0) return '0:00';
  const s = Math.floor(seg);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// ------------------------------------------------------------------ passos
/** Ordem fixa dos passos. `opcional` nao bloqueia o seguinte. */
export const ORDEM = [
  { id: 'video', titulo: 'Vídeo', resumo: 'Envie o vídeo gravado' },
  { id: 'cortes', titulo: 'Cortes', resumo: 'Tire pausas e repetições' },
  { id: 'legendas', titulo: 'Legendas', resumo: 'Confira o texto na tela' },
  { id: 'estilo', titulo: 'Estilo', resumo: 'Cores, letras e efeitos' },
  { id: 'preview', titulo: 'Preview', resumo: 'Assista a uma prévia' },
  { id: 'graficos', titulo: 'Gráficos', resumo: 'Cards de destaque (opcional)', opcional: true },
  { id: 'capa', titulo: 'Capa', resumo: 'Quadro e texto da capa' },
  { id: 'final', titulo: 'Final', resumo: 'Gere o Reel pronto' },
];

const registro = new Map();

function emBreve(container, ctx) {
  const passo = ORDEM.find((p) => p.id === ctx.passo) || {};
  container.append(el('div', { class: 'em-breve cartao' },
    icone('relogio', 'icone-grande'),
    el('span', { class: 'selo' }, 'Em breve'),
    el('p', {}, `O passo "${passo.titulo || ''}" ainda está sendo preparado.`),
    el('p', { class: 'suave' }, 'Tudo o que você já fez neste Reel continua guardado.')));
}

for (const p of ORDEM) registro.set(p.id, { ...p, render: emBreve, placeholder: true });

/**
 * registrarPasso({id, titulo, render(container, ctx), pronto?(estado)}): troca o
 * conteudo "Em breve" de um passo pelo de verdade. `pronto(estado)` decide se o
 * passo esta concluido (padrao: estado.etapas[id] === 'pronto').
 */
export function registrarPasso(def) {
  if (!def || !def.id || typeof def.render !== 'function') throw new Error('passo inválido');
  const base = registro.get(def.id) || { id: def.id };
  registro.set(def.id, { ...base, ...def, placeholder: false });
}

export function passo(id) { return registro.get(id); }

export function passoPronto(id, estado) {
  const p = registro.get(id);
  if (!estado || !p) return false;
  if (typeof p.pronto === 'function') return !!p.pronto(estado);
  return !!(estado.etapas && estado.etapas[id] === 'pronto');
}

/** {id: bloqueado?}: um passo so abre quando os anteriores obrigatorios estao prontos. */
export function bloqueios(estado) {
  const out = {};
  let livre = true;
  for (const p of ORDEM) {
    out[p.id] = !livre;
    if (!estado) livre = false;
    else if (!passoPronto(p.id, estado) && !p.opcional) livre = false;
  }
  return out;
}

// ----------------------------------------------------------- armazenamento
const CHAVE_ULTIMO = 'editor-reels:ultimo-projeto';

export function lerUltimo() {
  try { return localStorage.getItem(CHAVE_ULTIMO); } catch { return null; }
}

export function gravarUltimo(slug) {
  try {
    if (slug) localStorage.setItem(CHAVE_ULTIMO, slug);
    else localStorage.removeItem(CHAVE_ULTIMO);
  } catch { /* navegador sem armazenamento: so nao lembra */ }
}

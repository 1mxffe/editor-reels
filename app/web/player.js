// Player vertical da coluna esquerda: Tocar/Pausar, -5 s, +5 s e tempo.
// Sem controles nativos; o video vem de GET /api/projects/<slug>/arquivos/<rel> (Range).
import { relogio, urlArquivo } from './nucleo.js';

export function criarPlayer() {
  const video = document.getElementById('player-video');
  const vazio = document.getElementById('player-vazio');
  const play = document.getElementById('player-play');
  const menos = document.getElementById('player-menos5');
  const mais = document.getElementById('player-mais5');
  const tempo = document.getElementById('player-tempo');
  const legenda = document.getElementById('player-legenda');
  video.controls = false;
  let atual = null; // "slug|rel"
  let esperas = [];

  const temVideo = () => !!atual;

  function pintar() {
    const tocando = temVideo() && !video.paused && !video.ended;
    play.classList.toggle('tocando', tocando);
    play.setAttribute('aria-label', tocando ? 'Pausar' : 'Tocar');
    tempo.textContent = `${relogio(video.currentTime || 0)} / ${relogio(temVideo() ? video.duration : 0)}`;
    for (const b of [play, menos, mais]) b.disabled = !temVideo();
    vazio.hidden = temVideo();
    video.hidden = !temVideo();
  }

  function pular(delta) {
    if (!temVideo()) return;
    const dur = Number.isFinite(video.duration) ? video.duration : Infinity;
    video.currentTime = Math.min(Math.max(0, (video.currentTime || 0) + delta), dur);
    pintar();
  }

  function alternar() {
    if (!temVideo()) return;
    if (video.paused || video.ended) video.play().catch(() => pintar());
    else video.pause();
  }

  play.addEventListener('click', alternar);
  menos.addEventListener('click', () => pular(-5));
  mais.addEventListener('click', () => pular(5));
  for (const ev of ['play', 'pause', 'ended', 'timeupdate', 'durationchange', 'loadedmetadata', 'seeked']) {
    video.addEventListener(ev, pintar);
  }
  video.addEventListener('loadedmetadata', () => {
    const fila = esperas;
    esperas = [];
    for (const r of fila) r(metadados());
  });
  video.addEventListener('error', () => {
    const fila = esperas;
    esperas = [];
    for (const r of fila) r(null);
  });

  function metadados() {
    if (!temVideo() || video.readyState < 1) return null;
    return { duracao: video.duration, largura: video.videoWidth, altura: video.videoHeight };
  }

  pintar();
  return {
    video,
    alternar,
    temVideo,
    /** Mostra um arquivo do projeto. forcar recarrega mesmo se for o mesmo endereco. */
    definir(slug, rel, { forcar = false, rotulo = '' } = {}) {
      const chave = `${slug}|${rel}`;
      legenda.textContent = rotulo;
      if (chave === atual && !forcar) return;
      atual = chave;
      video.src = urlArquivo(slug, rel, forcar ? String(Date.now()) : '');
      video.load();
      pintar();
    },
    limpar() {
      atual = null;
      legenda.textContent = '';
      video.pause();
      video.removeAttribute('src');
      video.load();
      pintar();
    },
    /** Promise com {duracao, largura, altura} do video carregado (ou null). */
    metadados() {
      const m = metadados();
      if (m || !temVideo()) return Promise.resolve(m);
      return new Promise((r) => esperas.push(r));
    },
  };
}

// Passo 3, Legendas: o texto que aparece na tela, frase por frase. Cada edicao vai
// presa ao texto automatico que a pessoa viu (caption_edits {idx: {text, base_text}}):
// se os cortes mudarem depois, o servidor recusa em vez de trocar outra frase.
import { api, el, icone, registrarPasso, toast } from '../nucleo.js';
import { cutToOriginalTime, tempoFino } from '../tempo.js';
import { traduzir } from '../mensagens.js';

const MAX_LINHAS = 2;

function linhas(texto) {
  return texto.split('\n').filter((l) => l.trim()).length;
}

/** "Legenda da frase 0: ..." do servidor usa o indice; a tela numera a partir de 1. */
function erroDoServidor(e, idx) {
  if (e.status === 409) return 'Espere o trabalho em andamento terminar e tente de novo.';
  return traduzir(e.mensagem);
}

function itemFrase(ctx, estado, p) {
  const area = el('textarea', {
    class: 'frase-texto', rows: '2', maxlength: '500', spellcheck: 'true',
    'aria-label': `Legenda da frase ${p.idx + 1}`, 'aria-describedby': `frase-erro-${p.idx}`,
  });
  area.value = p.text;
  const tag = el('span', { class: 'frase-tag' });
  const desfazer = el('button', { type: 'button', class: 'botao botao-secundario botao-pequeno frase-desfazer' },
    'Voltar ao automático');
  const erro = el('p', { id: `frase-erro-${p.idx}`, class: 'frase-erro mensagem-erro', role: 'alert', hidden: true });
  const aviso = el('p', { class: 'frase-aviso mensagem-info', hidden: true });
  const tempo = el('button', {
    type: 'button', class: 'botao botao-secundario botao-pequeno frase-tempo',
    'aria-label': `Ver a frase ${p.idx + 1} no vídeo, em ${tempoFino(p.start)}`,
    onclick: () => ctx.player.irPara(cutToOriginalTime(p.start, estado.ativos) + 0.01),
  }, `Ver no vídeo · ${tempoFino(p.start)}`);
  const li = el('li', { class: 'frase', 'data-idx': String(p.idx) },
    el('div', { class: 'frase-topo' }, el('strong', {}, `Frase ${p.idx + 1}`), tempo, tag, desfazer),
    area, erro, aviso);

  function pintar() {
    const atual = estado.frases[p.idx];
    tag.textContent = atual.edited ? 'Editada' : '';
    tag.hidden = !atual.edited;
    desfazer.hidden = !atual.edited;
    li.dataset.editada = String(!!atual.edited);
    if (atual.stale) {
      aviso.textContent = 'Os cortes mudaram e a edição antiga desta frase não vale mais. Ela voltou ao texto automático.';
      aviso.hidden = false;
    } else aviso.hidden = true;
  }

  async function enviar(texto) {
    const atual = estado.frases[p.idx];
    erro.hidden = true;
    if (linhas(texto) > MAX_LINHAS) {
      erro.textContent = `Use no máximo ${MAX_LINHAS} linhas por legenda. Junte as linhas ou corte palavras.`;
      erro.hidden = false;
      return;
    }
    if (texto.trim() === atual.text.trim() && texto.trim() !== '') return;
    li.dataset.ocupado = '1';
    try {
      const rev = await api('PUT', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`,
        { caption_edits: { [String(p.idx)]: { text: texto, base_text: atual.base_text } } });
      estado.atualizar(rev);
      const nova = estado.frases[p.idx];
      if (document.activeElement !== area || texto.trim() === '') area.value = nova.text;
      pintar();
      ctx.atualizar();
    } catch (e) {
      erro.textContent = erroDoServidor(e, p.idx);
      erro.hidden = false;
    } finally {
      delete li.dataset.ocupado;
    }
  }

  // o confirmar espera de verdade pelas gravacoes em curso (estado.pendentes)
  const guardar = (t) => { const pr = enviar(t); estado.pendentes.add(pr); pr.finally(() => estado.pendentes.delete(pr)); };
  area.addEventListener('change', () => guardar(area.value));
  desfazer.addEventListener('click', () => { area.value = ''; guardar(''); });
  pintar();
  return li;
}

registrarPasso({
  id: 'legendas',
  pronto: (estado) => estado.legendas_confirmadas === true && !estado.legendas_desatualizado,
  video: (estado) => (estado.arquivos.entrada ? { rel: estado.arquivos.entrada, rotulo: 'Vídeo original' } : null),
  render(container, ctx) {
    const lista = el('ol', { id: 'lista-frases', class: 'frases' }, el('li', { class: 'suave' }, 'Carregando as frases…'));
    const velho = ctx.estado.legendas_desatualizado === true;
    const confirmado = ctx.estado.legendas_confirmadas === true && !velho;
    const pendentes = new Set();
    const confirmar = el('button', { type: 'button', id: 'legendas-confirmar', class: 'botao botao-primario' },
      (confirmado || velho) ? 'Confirmar de novo' : 'Confirmar legendas');
    const seguir = el('button', { type: 'button', class: 'botao botao-secundario', onclick: () => ctx.ir('preview') },
      'Ir para Preview', icone('seta'));
    confirmar.addEventListener('click', async () => {
      confirmar.disabled = true;
      // o que ainda esta no campo (sem sair dele) tambem vale
      const foco = document.activeElement;
      if (foco && foco.classList && foco.classList.contains('frase-texto')) foco.blur();
      await new Promise((r) => setTimeout(r, 0)); // deixa o "change" do campo disparar
      await Promise.allSettled([...pendentes]);
      if (lista.querySelector('.frase-erro:not([hidden])')) {
        toast('Corrija as frases marcadas antes de confirmar.', 'erro');
        confirmar.disabled = false;
        return;
      }
      try {
        await api('PUT', `/api/projects/${encodeURIComponent(ctx.slug)}/etapas/legendas`, { confirmado: true });
        toast('Legendas confirmadas.', 'ok');
        await ctx.atualizar();
        ctx.ir('preview');
      } catch (e) {
        toast(traduzir(e.mensagem), 'erro');
        confirmar.disabled = false;
      }
    });
    container.append(...[
      el('p', { class: 'lead' }, 'Confira o texto que vai aparecer na tela. Cada frase tem no máximo 2 linhas; '
        + 'para quebrar a linha, aperte Enter. As mudanças ficam guardadas ao sair do campo.'),
      confirmado ? el('p', { class: 'mensagem-info' }, 'Legendas confirmadas. Se mudar alguma frase, confirme de novo.') : null,
      velho ? el('p', { id: 'aviso-desatualizado', class: 'mensagem-aviso', role: 'status' },
        'Você mudou os cortes ou as legendas depois de confirmar. Confira as frases e confirme de novo.') : null,
      lista,
      el('div', { class: 'acoes' }, confirmar, confirmado ? seguir : null)].filter(Boolean));

    api('GET', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`).then((rev) => {
      if (!lista.isConnected) return;
      const estado = {
        pendentes,
        frases: rev.phrases, ativos: rev.cuts.filter((c) => c.active),
        atualizar(r) { this.frases = r.phrases; this.ativos = r.cuts.filter((c) => c.active); },
      };
      if (!rev.phrases.length) {
        lista.replaceChildren(el('li', { class: 'vazio' }, el('p', {}, 'Nenhuma frase para legendar.'),
          el('p', { class: 'suave' }, 'Volte aos Cortes: talvez o vídeo inteiro tenha sido cortado.')));
        return;
      }
      lista.replaceChildren(...rev.phrases.map((p) => itemFrase(ctx, estado, p)));
    }).catch((e) => {
      lista.replaceChildren(el('li', { class: 'mensagem-erro', role: 'alert' }, traduzir(e.mensagem)));
    });
  },
});

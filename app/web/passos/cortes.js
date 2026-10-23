// Passo 2, Cortes: reconhecer a fala, procurar pausas/muletas/repeticoes e decidir o que
// sai. Cada clique ja grava no Reel (PUT /revisao com cuts_removed / cuts_added).
import { api, el, icone, registrarPasso, relogio } from '../nucleo.js';
import { iniciarTarefa, quadroTarefa, rodando } from '../tarefa.js';
import { segundos, tempoFino } from '../tempo.js';
import { traduzir } from '../mensagens.js';

const TIPOS = ['transcrever', 'cortes'];
const AVISO_MODELO = 'Na primeira vez baixa o modelo de voz; pode demorar alguns minutos.';
const ROTULO_CORTE = {
  silence: 'Pausa',
  filler: 'Muleta',
  repeat: 'Palavra repetida',
  manual: 'Trecho que você cortou',
};

const meio = (w) => (w.start + w.end) / 2;
const dentro = (c, t) => c.start <= t && t <= c.end;

/** Cortes mostrados: os ativos e os desligados que nenhum ativo cobre (sem repetir). */
function cortesDaLista(rev) {
  const ativos = rev.cuts.filter((c) => c.active);
  const vistos = new Set();
  const desligados = rev.cuts.filter((c) => {
    // corte da pessoa desfeito (palavra trazida de volta) some da lista: nao e mais um corte
    if (c.active || c.kind === 'manual' || ativos.some((a) => a.start <= c.start && c.end <= a.end)) return false;
    const k = `${c.start}|${c.end}`;
    if (vistos.has(k)) return false;
    vistos.add(k);
    return true;
  });
  return [...ativos, ...desligados].sort((a, b) => a.start - b.start || a.end - b.end);
}

/** Nome do corte; um desligado que foi ligado de novo volta como manual, mas e o mesmo trecho. */
function tipoDoCorte(rev, c) {
  if (c.kind !== 'manual') return c.kind;
  const original = rev.cuts.find((x) => !x.active && x.kind !== 'manual' && x.start === c.start && x.end === c.end);
  return original ? original.kind : c.kind;
}

const faixa = (c) => `${c.start}-${c.end}`;

function palavrasDoCorte(rev, c) {
  return rev.words.filter((w) => dentro(c, meio(w))).map((w) => w.w).join(' ');
}

function mensagemDeErro(e) {
  if (e.status === 409) return 'Espere o trabalho em andamento terminar e tente de novo.';
  return traduzir(e.mensagem);
}

function telaRevisao(ctx, area) {
  const erro = el('p', { id: 'cortes-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
  const economia = el('dd', { id: 'cortes-economia' }, '…');
  const original = el('dd', {}, '…');
  const depois = el('dd', {}, '…');
  const resumo = el('div', { id: 'cortes-resumo', class: 'cartao resumo-cortes' },
    el('dl', {},
      el('div', { class: 'destaque' }, el('dt', {}, 'Tempo economizado'), economia),
      el('div', {}, el('dt', {}, 'Vídeo gravado'), original),
      el('div', {}, el('dt', {}, 'Depois dos cortes'), depois)));
  const palavras = el('div', { id: 'cortes-palavras', class: 'palavras', role: 'group',
    'aria-label': 'Texto do vídeo, palavra por palavra' });
  const lista = el('ul', { id: 'cortes-lista', class: 'cortes' });
  const proximo = el('button', { type: 'button', class: 'botao botao-primario', onclick: () => ctx.ir('legendas') },
    'Ir para Legendas', icone('seta'));
  area.replaceChildren(
    resumo, erro,
    el('section', { class: 'secao', 'aria-labelledby': 'tit-texto' },
      el('h2', { id: 'tit-texto' }, 'Texto do vídeo'),
      el('p', { class: 'ajuda' }, 'Toque numa palavra para tirá-la do vídeo; toque de novo para trazê-la de volta. '
        + 'As riscadas já vão sair. O vídeo ao lado pula para a palavra tocada.'),
      palavras),
    el('section', { class: 'secao', 'aria-labelledby': 'tit-cortes' },
      el('h2', { id: 'tit-cortes' }, 'Cortes encontrados'),
      el('p', { class: 'ajuda' }, 'Desligue um corte para manter aquele trecho no vídeo.'),
      lista),
    el('div', { class: 'acoes' }, proximo));

  let rev = null;
  let ocupado = false;

  function ocupar(sim) {
    ocupado = sim;
    if (sim) area.dataset.ocupado = '1'; else delete area.dataset.ocupado;
    for (const b of area.querySelectorAll('.palavra, .pausa, [role="switch"]')) b.disabled = sim;
  }

  async function salvar(decisoes) {
    if (ocupado) return;
    if (rodando(ctx.slug)) { mostrarErro('Espere o trabalho em andamento terminar e tente de novo.'); return; }
    erro.hidden = true;
    ocupar(true);
    try {
      rev = await api('PUT', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`, decisoes);
      if (!area.isConnected) return;
      pintar();
      ctx.atualizar();
    } catch (e) {
      mostrarErro(mensagemDeErro(e));
    } finally {
      ocupar(false);
    }
  }

  function mostrarErro(texto) {
    erro.textContent = texto;
    erro.hidden = false;
  }

  function clicarPalavra(w) {
    ctx.player.irPara(w.start); // o player mostra o video original
    const ativos = rev.cuts.filter((c) => c.active && dentro(c, meio(w)));
    if (ativos.length) { salvar({ cuts_removed: ativos.map((c) => c.id) }); return; }
    // a fala reconhecida pode passar do fim do video por milissegundos
    const start = Math.max(0, w.start);
    const end = Math.min(w.end, rev.duration);
    if (end <= start) { mostrarErro('Essa palavra fica depois do fim do vídeo; não há o que cortar.'); return; }
    salvar({ cuts_added: [{ start, end }] });
  }

  function alternarCorte(c) {
    if (c.active) salvar({ cuts_removed: [c.id] });
    else salvar({ cuts_added: [{ start: c.start, end: c.end }] });
  }

  function pintar() {
    const ativos = rev.cuts.filter((c) => c.active);
    economia.textContent = segundos(rev.duration - rev.kept_duration);
    original.textContent = relogio(rev.duration);
    depois.textContent = relogio(rev.kept_duration);

    // texto: palavras e as pausas sem palavra, na ordem do tempo
    const itens = rev.words.map((w) => ({ t: w.start, w }));
    for (const c of cortesDaLista(rev)) {
      if (!rev.words.some((w) => dentro(c, meio(w)))) itens.push({ t: c.start, c });
    }
    itens.sort((a, b) => a.t - b.t || (a.c ? -1 : 1));
    palavras.replaceChildren(...itens.map((it) => {
      if (it.w) {
        const cortada = ativos.some((c) => dentro(c, meio(it.w)));
        return el('button', {
          type: 'button', class: 'palavra', 'data-i': String(it.w.i),
          'data-estado': cortada ? 'cortada' : 'mantida', 'aria-pressed': String(cortada),
          title: `${tempoFino(it.w.start)} · ${cortada ? 'sai do vídeo; toque para trazer de volta' : 'toque para tirar'}`,
          onclick: () => clicarPalavra(it.w),
        }, it.w.w);
      }
      const ligado = !!it.c.active;
      return el('button', {
        type: 'button', class: 'pausa', 'data-corte': it.c.id, 'data-estado': ligado ? 'cortada' : 'mantida',
        'aria-pressed': String(ligado), 'aria-label': `Pausa de ${segundos(it.c.end - it.c.start)}${ligado ? ', vai sair' : ', fica'}`,
        onclick: () => alternarCorte(it.c),
      }, `pausa ${segundos(it.c.end - it.c.start)}`);
    }));
    if (!rev.words.length) {
      palavras.replaceChildren(el('p', { class: 'suave' }, 'Nenhuma fala reconhecida neste vídeo.'));
    }

    const cortes = cortesDaLista(rev);
    lista.replaceChildren(...(cortes.length ? cortes.map((c) => {
      const texto = palavrasDoCorte(rev, c);
      const nome = ROTULO_CORTE[tipoDoCorte(rev, c)] || 'Corte';
      const chave = el('button', {
        type: 'button', role: 'switch', class: 'interruptor', 'aria-checked': String(!!c.active),
        'aria-label': `${nome} em ${tempoFino(c.start)}: ${c.active ? 'vai sair do vídeo' : 'fica no vídeo'}`,
        onclick: () => alternarCorte(c),
      }, el('span', { class: 'interruptor-trilho', 'aria-hidden': 'true' }, el('span', { class: 'interruptor-bola' })),
      el('span', { class: 'interruptor-texto' }, c.active ? 'Cortar' : 'Manter'));
      return el('li', { class: 'corte', 'data-id': c.id, 'data-faixa': faixa(c), 'data-ativo': String(!!c.active) },
        el('div', { class: 'corte-info' },
          el('strong', {}, nome),
          el('span', { class: 'suave' }, `${tempoFino(c.start)} a ${tempoFino(c.end)} · ${segundos(c.end - c.start)}`),
          texto ? el('span', { class: 'corte-fala' }, `“${texto}”`) : el('span', { class: 'corte-fala suave' }, 'Silêncio')),
        chave);
    }) : [el('li', { class: 'vazio' }, el('p', {}, 'Nenhuma pausa ou repetição encontrada.'),
      el('p', { class: 'suave' }, 'Se quiser, toque nas palavras acima para cortar.'))]));
  }

  api('GET', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`).then((r) => {
    if (!area.isConnected) return;
    rev = r;
    pintar();
  }).catch((e) => {
    area.replaceChildren(el('p', { class: 'mensagem-erro', role: 'alert' }, traduzir(e.mensagem)));
  });
}

function botaoComecar(ctx, id, texto, tipo, erro) {
  const b = el('button', { type: 'button', id, class: 'botao botao-primario' }, texto);
  b.addEventListener('click', async () => {
    b.disabled = true;
    erro.hidden = true;
    try {
      await iniciarTarefa(ctx.slug, tipo);
    } catch (e) {
      erro.textContent = traduzir(e.mensagem);
      erro.hidden = false;
    } finally {
      b.disabled = false;
    }
  });
  return b;
}

registrarPasso({
  id: 'cortes',
  tarefas: TIPOS,
  video: (estado) => (estado.arquivos.entrada ? { rel: estado.arquivos.entrada, rotulo: 'Vídeo original' } : null),
  render(container, ctx) {
    const etapas = ctx.estado.etapas;
    const erro = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
    let acoes;
    if (etapas.transcricao !== 'pronto') {
      acoes = el('div', { class: 'cartao comecar' },
        el('h2', {}, 'Primeiro, o editor ouve o vídeo'),
        el('p', {}, 'Ele escreve o que foi falado e marca as pausas longas, os “né”, “ãh” e as palavras repetidas. Depois você confere.'),
        botaoComecar(ctx, 'cortes-reconhecer', 'Reconhecer a fala do vídeo', 'transcrever', erro),
        el('p', { id: 'cortes-aviso-modelo', class: 'ajuda' }, AVISO_MODELO));
    } else if (etapas.cortes !== 'pronto') {
      acoes = el('div', { class: 'cartao comecar' },
        el('h2', {}, 'Falta procurar os cortes'),
        el('p', {}, 'A fala já foi reconhecida. Agora o editor procura pausas e repetições.'),
        botaoComecar(ctx, 'cortes-detectar', 'Procurar pausas e repetições', 'cortes', erro));
    } else {
      acoes = el('div', { class: 'cortes-revisao' });
      telaRevisao(ctx, acoes);
    }
    const quadro = quadroTarefa(ctx.slug, TIPOS, {
      aoMudar: (ocupado) => { acoes.hidden = ocupado; },
      extra: { transcrever: AVISO_MODELO },
    });
    container.append(
      el('p', { class: 'lead' }, 'Tire do vídeo as pausas, as muletas e o que saiu errado. Nada se perde: dá para voltar atrás a qualquer momento.'),
      quadro, erro, acoes);
  },
});

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

const DICA = 'Dica: arraste sobre várias palavras ou segure Shift e clique para marcar um trecho.';
const FIM_FRASE = /[.!?…]["”')\]]*$/;
const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;

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
  const modoBotao = el('button', { type: 'button', id: 'cortes-modo', class: 'botao botao-secundario sel-botao',
    'aria-pressed': 'false', title: 'Com esta opção ligada, tocar numa palavra só marca; arrastar marca várias.' },
  'Marcar várias palavras');
  const selTitulo = el('strong', { id: 'cortes-sel-titulo' });
  const selTrecho = el('span', { id: 'cortes-sel-trecho', class: 'sel-trecho' });
  const selInfo = el('p', { id: 'cortes-sel-info', class: 'sel-info', 'aria-live': 'polite', 'aria-atomic': 'true' },
    selTitulo, selTrecho);
  const selCortar = el('button', { type: 'button', id: 'cortes-sel-cortar', class: 'botao sel-botao' });
  const selRestaurar = el('button', { type: 'button', id: 'cortes-sel-restaurar', class: 'botao sel-botao' });
  const selLimpar = el('button', { type: 'button', id: 'cortes-sel-limpar', class: 'botao botao-secundario sel-botao' },
    'Limpar seleção');
  const barra = el('div', { id: 'cortes-barra', class: 'barra-selecao', role: 'region',
    'aria-label': 'Palavras marcadas', hidden: true },
  selInfo, el('div', { class: 'sel-acoes' }, selCortar, selRestaurar, selLimpar));
  const proximo = el('button', { type: 'button', class: 'botao botao-primario', onclick: () => ctx.ir('legendas') },
    'Ir para Legendas', icone('seta'));
  area.replaceChildren(
    resumo, erro,
    el('section', { class: 'secao', 'aria-labelledby': 'tit-texto' },
      el('h2', { id: 'tit-texto' }, 'Texto do vídeo'),
      el('p', { class: 'ajuda' }, 'Toque numa palavra para tirá-la do vídeo; toque de novo para trazê-la de volta. '
        + 'As riscadas já vão sair. O vídeo ao lado pula para a palavra tocada.'),
      el('p', { id: 'cortes-dica', class: 'ajuda' }, DICA),
      el('div', { class: 'palavras-ferramentas' }, modoBotao),
      palavras),
    el('section', { class: 'secao', 'aria-labelledby': 'tit-cortes' },
      el('h2', { id: 'tit-cortes' }, 'Cortes encontrados'),
      el('p', { class: 'ajuda' }, 'Desligue um corte para manter aquele trecho no vídeo.'),
      lista),
    el('div', { class: 'acoes' }, proximo),
    barra);

  let rev = null;
  let ocupado = false;
  const sel = new Set();      // posicoes (w.i) das palavras marcadas, ainda sem gravar
  let ancora = null;          // ultima palavra clicada: ponto de partida do Shift+clique
  let foco = 0;               // palavra que recebe o Tab (so uma por vez)
  let devolverFoco = false;
  let modo = false;           // "Marcar várias": o toque marca e desmarca palavras
  let arrasto = null;
  let suprimir = false;       // o clique que termina um arrasto nao corta a palavra
  let pendente = null;        // clique simples espera o duplo clique em potencial

  function ocupar(sim) {
    ocupado = sim;
    if (sim) area.dataset.ocupado = '1'; else delete area.dataset.ocupado;
    for (const b of area.querySelectorAll('.palavra, .pausa, [role="switch"], .sel-botao')) b.disabled = sim;
  }

  async function salvar(decisoes, limpar = false) {
    if (ocupado) return false;
    if (rodando(ctx.slug)) { mostrarErro('Espere o trabalho em andamento terminar e tente de novo.'); return false; }
    erro.hidden = true;
    devolverFoco = palavras.contains(document.activeElement);
    ocupar(true);
    try {
      rev = await api('PUT', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`, decisoes);
      if (!area.isConnected) return true;
      if (limpar) sel.clear();
      pintar();
      ctx.atualizar();
      return true;
    } catch (e) {
      mostrarErro(mensagemDeErro(e));
      return false;
    } finally {
      ocupar(false);
    }
  }

  function mostrarErro(texto) {
    erro.textContent = texto;
    erro.hidden = false;
  }

  const cortesDaPalavra = (w) => rev.cuts.filter((c) => c.active && dentro(c, meio(w)));
  const estaCortada = (i) => cortesDaPalavra(rev.words[i]).length > 0;

  function clicarPalavra(w) {
    sel.clear();
    const ativos = cortesDaPalavra(w);
    if (ativos.length) { salvar({ cuts_removed: ativos.map((c) => c.id) }); return; }
    // a fala reconhecida pode passar do fim do video por milissegundos
    const start = Math.max(0, w.start);
    const end = Math.min(w.end, rev.duration);
    if (end <= start) { mostrarErro('Essa palavra fica depois do fim do vídeo; não há o que cortar.'); return; }
    salvar({ cuts_added: [{ start, end }] });
  }

  // ---------------------------------------------------------------- selecao
  const entre = (a, b) => {
    const [de, ate] = a <= b ? [a, b] : [b, a];
    return Array.from({ length: ate - de + 1 }, (_, k) => de + k);
  };

  function definir(ids) {
    sel.clear();
    for (const i of ids) sel.add(i);
    atualizarSelecao();
  }

  /** Trechos seguidos da selecao -> uma janela [start, fim do video] por trecho. */
  function janelas() {
    const ids = [...sel].sort((a, b) => a - b);
    const grupos = [];
    for (const i of ids) {
      const g = grupos[grupos.length - 1];
      if (g && g[g.length - 1] === i - 1) g.push(i); else grupos.push([i]);
    }
    return grupos.map((g) => ({
      ids: g,
      start: Math.max(0, rev.words[g[0]].start),
      end: Math.min(rev.words[g[g.length - 1]].end, rev.duration),
    }));
  }

  function resumoDoTrecho(ids) {
    const texto = ids.map((i) => rev.words[i].w).join(' ');
    return texto.length > 64 ? `${texto.slice(0, 30)} … ${texto.slice(-30)}` : texto;
  }

  function atualizarSelecao() {
    for (const b of palavras.querySelectorAll('.palavra')) {
      if (sel.has(Number(b.dataset.i))) b.dataset.sel = '1'; else delete b.dataset.sel;
    }
    if (!rev || !sel.size) { barra.hidden = true; return; }
    const ids = [...sel].sort((a, b) => a - b);
    const cortadas = ids.filter(estaCortada).length;
    const inteiras = ids.length - cortadas;
    const tempo = janelas().reduce((t, j) => t + Math.max(0, j.end - j.start), 0);
    selTitulo.textContent = `${plural(ids.length, 'palavra selecionada', 'palavras selecionadas')}`;
    selTrecho.textContent = `“${resumoDoTrecho(ids)}” · ${segundos(tempo)}`;
    selCortar.textContent = `Cortar ${plural(inteiras, 'palavra', 'palavras')}`;
    selRestaurar.textContent = `Restaurar ${plural(cortadas, 'palavra', 'palavras')}`;
    selCortar.hidden = inteiras === 0;
    selRestaurar.hidden = cortadas === 0;
    selCortar.className = `botao sel-botao ${cortadas > inteiras ? 'botao-secundario' : 'botao-primario'}`;
    selRestaurar.className = `botao sel-botao ${cortadas > inteiras ? 'botao-primario' : 'botao-secundario'}`;
    barra.hidden = false;
  }

  async function cortarSelecao() {
    const novas = janelas().filter((j) => j.ids.some((i) => !estaCortada(i))).filter((j) => j.end > j.start)
      .map((j) => ({ start: j.start, end: j.end }));
    if (!novas.length) { mostrarErro('Esse trecho fica depois do fim do vídeo; não há o que cortar.'); return; }
    await salvar({ cuts_added: novas }, true);
  }

  async function restaurarSelecao() {
    const ids = new Set();
    for (const i of sel) for (const c of cortesDaPalavra(rev.words[i])) ids.add(c.id);
    if (!ids.size) return;
    await salvar({ cuts_removed: [...ids] }, true);
  }

  function agirNaSelecao() {
    const cortadas = [...sel].filter(estaCortada).length;
    return cortadas > sel.size - cortadas ? restaurarSelecao() : cortarSelecao();
  }

  function limparSelecao() {
    sel.clear();
    atualizarSelecao();
  }

  function selecionarFrase(i) {
    const p = rev.words;
    let de = i;
    while (de > 0 && !FIM_FRASE.test(p[de - 1].w)) de -= 1;
    let ate = i;
    while (ate < p.length - 1 && !FIM_FRASE.test(p[ate].w)) ate += 1;
    ancora = i;
    definir(entre(de, ate));
  }

  function aoClicar(e, w) {
    if (suprimir) return;
    foco = w.i;
    if (e.detail === 0) { // teclado (Enter ou Espaço)
      if (sel.size) agirNaSelecao(); else { ctx.player.irPara(w.start); clicarPalavra(w); }
      return;
    }
    if (e.shiftKey) {
      definir(entre(ancora === null ? w.i : ancora, w.i));
      if (ancora === null) ancora = w.i;
      return;
    }
    if (e.ctrlKey || e.metaKey || modo) {
      ancora = w.i;
      const novo = new Set(sel);
      if (novo.has(w.i)) novo.delete(w.i); else novo.add(w.i);
      definir(novo);
      return;
    }
    clearTimeout(pendente);
    pendente = null;
    if (e.detail >= 2) { selecionarFrase(w.i); return; }
    ancora = w.i;
    ctx.player.irPara(w.start); // o player mostra o video original
    // espera um instante: um segundo clique seguido seleciona a frase em vez de cortar
    pendente = setTimeout(() => { pendente = null; if (area.isConnected) clicarPalavra(w); }, 230);
  }

  // arrastar com mouse, caneta ou dedo
  function palavraEm(x, y) {
    const b = document.elementFromPoint(x, y);
    return b && b.closest ? b.closest('.palavra') : null;
  }

  function terminarArrasto() {
    window.removeEventListener('pointermove', moverArrasto);
    window.removeEventListener('pointerup', soltarArrasto);
    window.removeEventListener('pointercancel', soltarArrasto);
    if (arrasto && arrasto.ativo) {
      suprimir = true;
      setTimeout(() => { suprimir = false; }, 60);
    }
    arrasto = null;
  }

  function moverArrasto(e) {
    if (!arrasto || e.pointerId !== arrasto.id) return;
    const b = palavraEm(e.clientX, e.clientY);
    if (!arrasto.ativo) {
      if (!b || Number(b.dataset.i) === arrasto.de) return;
      arrasto.ativo = true;
      clearTimeout(pendente);
      pendente = null;
    }
    if (b) {
      foco = Number(b.dataset.i);
      definir(entre(arrasto.de, foco));
    }
  }

  function soltarArrasto(e) {
    if (arrasto && e.pointerId === arrasto.id) {
      if (arrasto.ativo) ancora = arrasto.de;
      terminarArrasto();
    }
  }

  palavras.addEventListener('pointerdown', (e) => {
    const b = e.target.closest ? e.target.closest('.palavra') : null;
    if (!b || b.disabled || ocupado || (e.pointerType === 'mouse' && e.button !== 0)) return;
    arrasto = { de: Number(b.dataset.i), id: e.pointerId, ativo: false };
    window.addEventListener('pointermove', moverArrasto);
    window.addEventListener('pointerup', soltarArrasto);
    window.addEventListener('pointercancel', soltarArrasto);
  });

  // teclado: setas movem o foco, Shift+setas estendem a selecao
  function vizinho(atual, dir) {
    const botoes = [...palavras.querySelectorAll('.palavra')];
    const p = botoes.indexOf(atual);
    if (dir === 'ArrowLeft') return botoes[Math.max(0, p - 1)];
    if (dir === 'ArrowRight') return botoes[Math.min(botoes.length - 1, p + 1)];
    if (dir === 'Home') return botoes[0];
    if (dir === 'End') return botoes[botoes.length - 1];
    const sinal = dir === 'ArrowDown' ? 1 : -1;
    const r = atual.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    let melhor = atual;
    let nota = Infinity;
    for (const b of botoes) {
      const q = b.getBoundingClientRect();
      const dy = sinal * (q.top - r.top);
      if (dy < r.height * 0.5) continue;
      const n = dy * 1000 + Math.abs(q.left + q.width / 2 - cx);
      if (n < nota) { nota = n; melhor = b; }
    }
    return melhor;
  }

  palavras.addEventListener('keydown', (e) => {
    const b = e.target.closest ? e.target.closest('.palavra') : null;
    if (!b || !['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    e.preventDefault();
    const alvo = vizinho(b, e.key);
    const i = Number(alvo.dataset.i);
    if (e.shiftKey) {
      if (ancora === null) ancora = Number(b.dataset.i);
      definir(entre(ancora, i));
    } else {
      ancora = i;
    }
    focar(i);
  });

  function focar(i) {
    foco = i;
    for (const x of palavras.querySelectorAll('.palavra')) x.tabIndex = Number(x.dataset.i) === i ? 0 : -1;
    const b = palavras.querySelector(`.palavra[data-i="${i}"]`);
    if (b) b.focus({ preventScroll: false });
  }

  const aoTeclar = (e) => {
    if (!area.isConnected) { document.removeEventListener('keydown', aoTeclar); return; }
    if (e.key === 'Escape' && sel.size) { e.preventDefault(); limparSelecao(); }
  };
  document.addEventListener('keydown', aoTeclar);

  selCortar.addEventListener('click', cortarSelecao);
  selRestaurar.addEventListener('click', restaurarSelecao);
  selLimpar.addEventListener('click', limparSelecao);
  modoBotao.addEventListener('click', () => {
    modo = !modo;
    modoBotao.setAttribute('aria-pressed', String(modo));
    palavras.dataset.modo = modo ? '1' : '0';
  });

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
          type: 'button', class: 'palavra', 'data-i': String(it.w.i), tabindex: it.w.i === foco ? '0' : '-1',
          'data-estado': cortada ? 'cortada' : 'mantida', 'aria-pressed': String(cortada),
          title: `${tempoFino(it.w.start)} · ${cortada ? 'sai do vídeo; toque para trazer de volta' : 'toque para tirar'}`,
          onclick: (e) => aoClicar(e, it.w),
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

    atualizarSelecao();
    if (devolverFoco) {
      devolverFoco = false;
      const b = palavras.querySelector(`.palavra[data-i="${foco}"]`);
      if (b) b.focus({ preventScroll: true });
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

// Passo 6, Gráficos (opcional): cards de destaque por cima do vídeo (graficos.json) e,
// na aba Materiais, as imagens e vídeos de apoio do Reel (pasta materiais/).
// Miniaturas sempre por <img src> do endereço do arquivo: nada de HTML vindo de fora
// (um SVG enviado nunca é colocado dentro da página).
import { TOKEN, api, el, icone, registrarPasso, relogio, tamanho, toast, urlArquivo } from '../nucleo.js';
import { traduzir } from '../mensagens.js';
import { versaoDe } from '../tarefa.js';

const TITULO_MAX = 60;
const TEXTO_MAX = 140;
const DURACOES = [1, 2, 3, 4, 5, 6];
const ACEITOS = '.png,.jpg,.jpeg,.webp,.svg,.mp4,image/png,image/jpeg,image/webp,image/svg+xml,video/mp4';
const abaAberta = new Map(); // slug -> 'cards' | 'materiais'

const rota = (slug, resto) => `/api/projects/${encodeURIComponent(slug)}/${resto}`;
const segundos = (n) => `${String(Math.round(n * 10) / 10).replace('.', ',')} s`;

function novoId(cards) {
  const usados = new Set(cards.map((c) => c.id));
  for (let i = cards.length + 1; ; i++) {
    const id = `card-${i}`;
    if (!usados.has(id)) return id;
  }
}

/** "3,5" ou "1:05" -> segundos (ou NaN). */
function lerMomento(texto) {
  const t = String(texto || '').trim().replace(',', '.');
  const m = t.match(/^(\d+):([0-5]?\d(?:\.\d+)?)$/);
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  return /^\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
}

function contador(campo, max) {
  const c = el('span', { class: 'contador suave', 'aria-live': 'polite' });
  const pintar = () => {
    const n = campo.value.trim().length;
    c.textContent = `${n} de ${max}`;
    c.classList.toggle('contador-cheio', n >= max);
  };
  campo.addEventListener('input', pintar);
  pintar();
  return c;
}

function miniatura(slug, mat, classe = 'miniatura') {
  if (mat.tipo === 'video') {
    return el('span', { class: `${classe} miniatura-video`, 'aria-hidden': 'true' }, icone('video', 'icone-grande'));
  }
  return el('img', { class: classe, src: urlArquivo(slug, mat.rel), alt: '' });
}

// ------------------------------------------------------------------ materiais
function abaMateriais(ctx, estadoTela) {
  const slug = ctx.slug;
  const erro = el('p', { id: 'materiais-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
  const lista = el('ul', { id: 'materiais-lista', class: 'materiais' });
  const vazio = el('p', { id: 'materiais-vazio', class: 'suave' }, 'Nenhum material ainda. É opcional: o Reel sai bem sem eles.');
  const andamento = el('p', { id: 'materiais-enviando', class: 'mensagem-info', role: 'status', hidden: true });
  const entrada = el('input', { id: 'arquivo-material', type: 'file', class: 'sr-only', accept: ACEITOS, multiple: true });
  const zona = el('label', { class: 'soltar soltar-baixo', for: 'arquivo-material' },
    icone('enviar', 'icone-grande'),
    el('strong', {}, 'Enviar fotos, ícones ou vídeos'),
    el('span', { class: 'suave' }, 'Clique para escolher ou solte os arquivos aqui. PNG, JPG, WEBP, SVG ou MP4.'));

  function pintar() {
    const mats = estadoTela.materiais;
    vazio.hidden = mats.length > 0;
    lista.replaceChildren(...mats.map((m) => el('li', { class: 'material', 'data-nome': m.nome },
      miniatura(slug, m),
      el('div', { class: 'material-info' },
        el('strong', { class: 'material-nome', title: m.nome }, m.nome),
        el('span', { class: 'suave' }, `${m.tipo === 'video' ? 'Vídeo' : 'Imagem'} · ${m.tamanho < 1024 * 1024 ? `${Math.max(1, Math.round(m.tamanho / 1024))} KB` : tamanho(m.tamanho)}`)),
      el('button', {
        type: 'button', class: 'botao botao-secundario material-apagar', 'aria-label': `Apagar ${m.nome}`,
        onclick: () => apagar(m),
      }, icone('lixo')))));
  }

  async function apagar(m) {
    erro.hidden = true;
    try {
      const r = await api('DELETE', rota(slug, `materiais/${encodeURIComponent(m.nome)}`));
      estadoTela.materiais = r.materiais;
      pintar();
      estadoTela.aoMudarMateriais();
      toast(`"${m.nome}" foi apagado.`, 'ok');
    } catch (e) {
      erro.textContent = traduzir(e.mensagem);
      erro.hidden = false;
    }
  }

  async function enviar(arquivos) {
    erro.hidden = true;
    const falhas = [];
    let i = 0;
    for (const arq of arquivos) {
      i += 1;
      andamento.textContent = `Enviando ${i} de ${arquivos.length}: ${arq.name}…`;
      andamento.hidden = false;
      let resp;
      try {
        resp = await fetch(rota(slug, 'materiais'), {
          method: 'PUT', body: arq,
          headers: { 'X-Token': TOKEN, 'X-Filename': encodeURIComponent(arq.name) },
        });
      } catch {
        falhas.push(`${arq.name}: sem conexão com o editor.`);
        continue;
      }
      if (!resp.ok) {
        let msg = '';
        try { msg = (await resp.json()).erro || ''; } catch { /* sem corpo */ }
        falhas.push(`${arq.name}: ${traduzir(msg) || 'não deu para enviar.'}`);
      }
    }
    andamento.hidden = true;
    try {
      estadoTela.materiais = (await api('GET', rota(slug, 'materiais'))).materiais;
    } catch { /* fica a lista anterior */ }
    pintar();
    estadoTela.aoMudarMateriais();
    if (falhas.length) {
      erro.textContent = falhas.join(' ');
      erro.hidden = false;
    } else {
      toast(arquivos.length > 1 ? 'Materiais enviados.' : 'Material enviado.', 'ok');
    }
  }

  entrada.addEventListener('change', () => {
    const arquivos = [...entrada.files];
    entrada.value = '';
    if (arquivos.length) enviar(arquivos);
  });
  zona.addEventListener('dragover', (e) => { e.preventDefault(); zona.classList.add('ativa'); });
  zona.addEventListener('dragleave', () => zona.classList.remove('ativa'));
  zona.addEventListener('drop', (e) => {
    e.preventDefault();
    zona.classList.remove('ativa');
    const arquivos = [...(e.dataTransfer && e.dataTransfer.files) || []];
    if (arquivos.length) enviar(arquivos);
  });
  estadoTela.pintarMateriais = pintar;
  pintar();
  return el('div', { id: 'aba-materiais', class: 'secao', role: 'tabpanel', 'aria-labelledby': 'tab-materiais' },
    el('p', { class: 'ajuda' }, 'Fotos, ícones, vídeos e inspirações do escritório. As imagens podem aparecer dentro dos cards.'),
    entrada, zona, andamento, erro, vazio, lista);
}

// ---------------------------------------------------------------------- cards
function formulario(ctx, estadoTela, card, aoFechar) {
  const imagens = estadoTela.materiais.filter((m) => m.tipo === 'imagem');
  const titulo = el('input', { id: 'card-titulo', type: 'text', maxlength: String(TITULO_MAX), autocomplete: 'off',
    placeholder: 'Ex.: Prazo de 15 dias úteis' });
  titulo.value = card.title || '';
  const texto = el('textarea', { id: 'card-texto', rows: '3', maxlength: String(TEXTO_MAX),
    placeholder: 'Opcional. Uma frase curta que explica o título.' });
  texto.value = card.body || '';
  const momento = el('input', { id: 'card-momento', type: 'text', inputmode: 'decimal', autocomplete: 'off',
    'aria-describedby': 'card-momento-ajuda' });
  momento.value = String(Math.round((card.at || 0) * 10) / 10).replace('.', ',');
  const usarPonto = el('button', { type: 'button', id: 'card-usar-ponto', class: 'botao botao-secundario' },
    icone('relogio'), el('span', {}, 'Usar o ponto do vídeo'));
  usarPonto.addEventListener('click', () => {
    const t = ctx.player && ctx.player.temVideo() ? ctx.player.agora() : 0;
    momento.value = String(Math.round(t * 10) / 10).replace('.', ',');
  });
  const duracao = el('select', { id: 'card-duracao' },
    ...DURACOES.map((d) => el('option', { value: String(d), selected: Math.round(card.dur || 3) === d },
      d === 1 ? '1 segundo' : `${d} segundos`)));
  const imagem = el('select', { id: 'card-imagem' },
    el('option', { value: '' }, 'Sem imagem'),
    ...imagens.map((m) => el('option', { value: m.rel, selected: card.material === m.rel }, m.nome)));
  if (card.material && !imagens.some((m) => m.rel === card.material)) {
    imagem.append(el('option', { value: card.material, selected: true }, `${card.material.split('/').pop()} (não está mais nos materiais)`));
  }
  const previa = el('div', { class: 'card-imagem-previa' });
  const pintarPrevia = () => {
    const m = imagens.find((x) => x.rel === imagem.value);
    previa.replaceChildren(...(m ? [miniatura(ctx.slug, m, 'miniatura miniatura-grande')] : []));
  };
  imagem.addEventListener('change', pintarPrevia);
  pintarPrevia();
  const erro = el('p', { id: 'card-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
  const salvar = el('button', { type: 'submit', id: 'card-salvar', class: 'botao botao-primario' }, icone('ok'), el('span', {}, 'Salvar card'));
  const cancelar = el('button', { type: 'button', id: 'card-cancelar', class: 'botao botao-secundario', onclick: aoFechar }, 'Cancelar');

  const campo = (rotulo, id, controle, ...extra) => el('div', { class: 'campo' },
    el('label', { for: id }, rotulo), controle, ...extra);
  const form = el('form', { id: 'card-form', class: 'cartao formulario card-form', novalidate: true },
    el('h3', {}, card.id ? 'Editar card' : 'Novo card'),
    campo('Título', 'card-titulo', titulo, contador(titulo, TITULO_MAX)),
    campo('Texto (opcional)', 'card-texto', texto, contador(texto, TEXTO_MAX)),
    el('div', { class: 'campo-dupla' },
      campo('Aparece aos (segundos)', 'card-momento', momento,
        el('span', { id: 'card-momento-ajuda', class: 'ajuda' }, 'Conta no preview, já com os cortes.')),
      campo('Fica na tela por', 'card-duracao', duracao)),
    usarPonto,
    campo('Imagem dos materiais', 'card-imagem', imagem, previa,
      imagens.length ? null : el('span', { class: 'ajuda' }, 'Para pôr uma imagem, envie na aba Materiais.')),
    erro,
    el('div', { class: 'acoes' }, salvar, cancelar));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    erro.hidden = true;
    const t = titulo.value.trim();
    const at = lerMomento(momento.value);
    let msg = '';
    if (!t) msg = 'Escreva o título do card.';
    else if (!Number.isFinite(at)) msg = 'O momento precisa ser um número de segundos, por exemplo 3 ou 3,5.';
    if (msg) {
      erro.textContent = msg;
      erro.hidden = false;
      return;
    }
    const novo = { id: card.id || novoId(estadoTela.cards), title: t, body: texto.value.trim() || null,
      at: Math.round(at * 100) / 100, dur: Number(duracao.value), material: imagem.value || null };
    const cards = card.id ? estadoTela.cards.map((c) => (c.id === card.id ? novo : c)) : [...estadoTela.cards, novo];
    salvar.disabled = true;
    try {
      await estadoTela.gravar(cards);
      toast(card.id ? 'Card atualizado.' : 'Card adicionado.', 'ok');
      aoFechar();
    } catch (err) {
      erro.textContent = traduzir(err.mensagem);
      erro.hidden = false;
    } finally {
      salvar.disabled = false;
    }
  });
  queueMicrotask(() => titulo.focus());
  return form;
}

function abaCards(ctx, estadoTela) {
  const slug = ctx.slug;
  const lista = el('ul', { id: 'cards-lista', class: 'cards' });
  const vazio = el('div', { id: 'cards-vazio', class: 'cartao vazio-cards' },
    el('p', {}, 'Nenhum card ainda.'),
    el('p', { class: 'suave' }, 'Um card é um quadro com título (e um texto curto) que aparece por cima do vídeo por alguns segundos. Use para destacar um número, um prazo ou uma regra.'));
  const erro = el('p', { id: 'cards-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
  const lugarForm = el('div');
  const adicionar = el('button', { type: 'button', id: 'card-adicionar', class: 'botao botao-primario' },
    icone('mais'), el('span', {}, 'Adicionar card'));
  const podeDecidir = ctx.estado.etapas.transcricao === 'pronto';

  function abrirForm(card) {
    erro.hidden = true;
    adicionar.hidden = true;
    lugarForm.replaceChildren(formulario(ctx, estadoTela, card, fecharForm));
  }
  function fecharForm() {
    lugarForm.replaceChildren();
    adicionar.hidden = false;
    pintar();
  }
  adicionar.addEventListener('click', () => {
    const agora = ctx.player && ctx.player.temVideo() ? ctx.player.agora() : 0;
    abrirForm({ at: agora, dur: 3 });
  });

  async function remover(c) {
    erro.hidden = true;
    try {
      await estadoTela.gravar(estadoTela.cards.filter((x) => x.id !== c.id));
      toast('Card removido.', 'ok');
    } catch (e) {
      erro.textContent = traduzir(e.mensagem);
      erro.hidden = false;
    }
  }

  async function alternar(c, botao) {
    const manter = estadoTela.decisoes[c.id] === 'drop';
    botao.disabled = true;
    erro.hidden = true;
    try {
      const rev = await api('PUT', rota(slug, 'revisao'), { graphics: { [c.id]: manter ? 'keep' : 'drop' } });
      estadoTela.decisoes = (rev && rev.graphics) || { ...estadoTela.decisoes, [c.id]: manter ? 'keep' : 'drop' };
      pintar();
    } catch (e) {
      erro.textContent = e.status === 409 ? 'Espere o trabalho em andamento terminar e tente de novo.' : traduzir(e.mensagem);
      erro.hidden = false;
      botao.disabled = false;
    }
  }

  function pintar() {
    const cards = estadoTela.cards.slice().sort((a, b) => a.at - b.at);
    vazio.hidden = cards.length > 0;
    lista.replaceChildren(...cards.map((c) => {
      const fica = estadoTela.decisoes[c.id] !== 'drop';
      const mat = c.material && estadoTela.materiais.find((m) => m.rel === c.material);
      const chave = el('button', {
        type: 'button', role: 'switch', class: 'interruptor card-manter', 'aria-checked': String(fica),
        'aria-label': `Card "${c.title}": ${fica ? 'aparece no vídeo' : 'fica fora do vídeo'}`,
        disabled: !podeDecidir, onclick: (e) => alternar(c, e.currentTarget),
      }, el('span', { class: 'interruptor-trilho', 'aria-hidden': 'true' }, el('span', { class: 'interruptor-bola' })),
      el('span', { class: 'interruptor-texto' }, fica ? 'Manter' : 'Fora'));
      return el('li', { class: 'cartao card-item', 'data-id': c.id, 'data-fica': String(fica) },
        mat ? miniatura(slug, mat) : el('span', { class: 'miniatura miniatura-vazia', 'aria-hidden': 'true' }, icone('nota', 'icone-grande')),
        el('div', { class: 'card-info' },
          el('strong', { class: 'card-titulo' }, c.title),
          c.body ? el('span', { class: 'card-texto' }, c.body) : null,
          el('span', { class: 'suave card-quando' }, `Aos ${relogio(c.at)} · por ${segundos(c.dur)}`)),
        el('div', { class: 'card-acoes' },
          chave,
          el('button', { type: 'button', class: 'botao botao-secundario card-editar', 'aria-label': `Editar card "${c.title}"`,
            onclick: () => abrirForm(c) }, icone('lapis')),
          el('button', { type: 'button', class: 'botao botao-secundario card-remover', 'aria-label': `Remover card "${c.title}"`,
            onclick: () => remover(c) }, icone('lixo'))));
    }));
  }
  estadoTela.pintarCards = pintar;
  pintar();
  return el('div', { id: 'aba-cards', class: 'secao', role: 'tabpanel', 'aria-labelledby': 'tab-cards' },
    podeDecidir ? null : el('p', { class: 'ajuda' }, 'O botão Manter/Fora aparece depois que o vídeo passar pelo passo Cortes.'),
    erro, vazio, lista, lugarForm, el('div', { class: 'acoes' }, adicionar));
}

registrarPasso({
  id: 'graficos',
  tituloPainel: 'Gráficos',
  video: (estado, slug) => (estado.arquivos.preview
    ? { rel: estado.arquivos.preview, rotulo: 'Preview', versao: versaoDe(slug, 'preview') } : null),
  render(container, ctx) {
    const slug = ctx.slug;
    const carregando = el('p', { class: 'carregando' }, 'Carregando os cards…');
    const erroGeral = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
    container.append(
      el('p', { class: 'lead' }, 'Cards de destaque por cima do vídeo. É opcional: sem cards, o Reel sai só com as legendas.'),
      carregando, erroGeral);

    const estadoTela = {
      cards: [], decisoes: {}, materiais: [],
      pintarCards: () => {}, pintarMateriais: () => {},
      aoMudarMateriais() { this.pintarCards(); },
      async gravar(cards) {
        const r = await api('PUT', rota(slug, 'graficos'), { cards });
        this.cards = r.cards;
        this.decisoes = r.decisoes || {};
        this.pintarCards();
        ctx.atualizar();
      },
    };

    Promise.all([api('GET', rota(slug, 'graficos')), api('GET', rota(slug, 'materiais'))]).then(([g, m]) => {
      if (!carregando.isConnected || ctx.slugAtual() !== slug) return;
      estadoTela.cards = g.cards;
      estadoTela.decisoes = g.decisoes || {};
      estadoTela.materiais = m.materiais;
      const abas = [
        { id: 'cards', rotulo: 'Cards', painel: abaCards(ctx, estadoTela) },
        { id: 'materiais', rotulo: 'Materiais', painel: abaMateriais(ctx, estadoTela) },
      ];
      const botoes = abas.map((a) => el('button', {
        type: 'button', role: 'tab', id: `tab-${a.id}`, class: 'aba', 'aria-controls': `aba-${a.id}`,
        onclick: () => abrir(a.id),
      }, a.rotulo));
      function abrir(id) {
        abaAberta.set(slug, id);
        abas.forEach((a, i) => {
          const sel = a.id === id;
          botoes[i].setAttribute('aria-selected', String(sel));
          botoes[i].tabIndex = sel ? 0 : -1;
          a.painel.hidden = !sel;
        });
      }
      const lista = el('div', { class: 'abas', role: 'tablist', 'aria-label': 'Gráficos e materiais' }, ...botoes);
      lista.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
        const i = botoes.indexOf(document.activeElement);
        if (i < 0) return;
        const j = (i + (e.key === 'ArrowRight' ? 1 : botoes.length - 1)) % botoes.length;
        botoes[j].focus();
        abrir(abas[j].id);
      });
      carregando.replaceWith(lista, ...abas.map((a) => a.painel));
      abrir(abaAberta.get(slug) || 'cards');
    }).catch((e) => {
      carregando.remove();
      erroGeral.textContent = traduzir(e.mensagem);
      erroGeral.hidden = false;
    });
  },
});

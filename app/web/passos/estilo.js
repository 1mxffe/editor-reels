// Passo 4, Estilo (opcional): escolhe paleta, fonte, legenda e efeitos a partir do banco
// do escritorio. Cada cartao mostra um quadro de exemplo do proprio video (tarefa
// "quadros", em cache). As escolhas so valem ao "Aplicar estilo" (estilo.json + preview novo).
// Nomes e descricoes do banco sao SEMPRE texto (el/textContent); nada de HTML vindo de fora.
import { api, el, icone, registrarPasso, relogio, toast, urlArquivo } from '../nucleo.js';
import { traduzir } from '../mensagens.js';
import { iniciarTarefa, ouvir, quadroTarefa, rodando, versaoDe } from '../tarefa.js';

const ABAS = [
  { id: 'paletas', rotulo: 'Paletas', tipo: 'paleta', exemplo: true },
  { id: 'fontes', rotulo: 'Fontes' },
  { id: 'legendas', rotulo: 'Legendas', tipo: 'legenda', exemplo: true },
  { id: 'efeitos', rotulo: 'Efeitos', tipo: 'efeito', exemplo: true },
  { id: 'notas', rotulo: 'Notas' },
];
const POSICOES = [['baixo', 'Em baixo'], ['meio', 'No meio']];
const TAMANHOS = [['P', 'Pequena'], ['M', 'Média'], ['G', 'Grande']];
const FONTES_ACEITAS = ['Poppins'];
const PADRAO = { paleta: 'marca', fonte: 'Poppins', legenda: { estilo: 'faixa-azul', posicao: 'baixo', tamanho: 'M' } };
const HEX = /^#[0-9a-f]{6}$/i;

const abaAberta = new Map(); // slug -> id da aba
const pendente = new Map(); // slug -> escolhas ainda nao aplicadas
const cacheQuadros = new Map(); // slug|aba|estilo|duracao -> {id do item: caminho do quadro}

const rota = (slug, resto) => `/api/projects/${encodeURIComponent(slug)}/${resto}`;
const mesmo = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const copia = (o) => JSON.parse(JSON.stringify(o));
const segundos = (n) => `${String(Math.round(n * 10) / 10).replace('.', ',')} s`;
const numero = (n) => String(Math.round(n * 100) / 100).replace('.', ',');
const rotuloDe = (lista, v) => (lista.find(([k]) => k === v) || [v, String(v)])[1];

function lerNumero(texto) {
  const t = String(texto || '').trim().replace(',', '.');
  return /^-?\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
}

/** "3,5" ou "1:05" -> segundos (ou NaN). */
function lerMomento(texto) {
  const t = String(texto || '').trim().replace(',', '.');
  const m = t.match(/^(\d+):([0-5]?\d(?:\.\d+)?)$/);
  if (m) return Number(m[1]) * 60 + Number(m[2]);
  return /^\d+(\.\d+)?$/.test(t) ? Number(t) : NaN;
}

const so = (aplicado) => ({ paleta: aplicado.paleta, fonte: aplicado.fonte, legenda: { ...aplicado.legenda } });

/** {id do item: caminho} a partir dos PNGs da tarefa (quadros/<tipo>-<id>-<16 hex>.png). */
function mapear(saidas, tipo) {
  const mapa = {};
  for (const rel of saidas || []) {
    const m = String(rel).split('/').pop().match(/^(paleta|legenda|efeito)-(.+)-[0-9a-f]{16}\.png$/);
    if (m && m[1] === tipo) mapa[m[2]] = rel;
  }
  return mapa;
}

function campoDe(rotulo, id, controle, ...extra) {
  return el('div', { class: 'campo' }, el('label', { for: id }, rotulo), controle, ...extra);
}

// ------------------------------------------------------------ campos dos efeitos
function ajudaDoCampo(c) {
  const p = [];
  p.push(c.obrigatorio ? 'Obrigatório.' : 'Opcional.');
  if (c.tipo === 'texto') {
    if (c.max) p.push(`Até ${c.max} letras.`);
    if (c.min) p.push(`Pelo menos ${c.min} letras.`);
  } else if (c.tipo === 'numero') {
    const lim = c.min !== undefined && c.max !== undefined ? `entre ${numero(c.min)} e ${numero(c.max)}`
      : c.max !== undefined ? `até ${numero(c.max)}` : c.min !== undefined ? `a partir de ${numero(c.min)}` : '';
    p.push(`${c.inteiro ? 'Número inteiro' : 'Número'}${lim ? ` ${lim}` : ''}.`);
  }
  if (c.itens) p.push(`De ${c.itens.min} a ${c.itens.max} itens.`);
  return p.join(' ');
}

/** Um valor de campo: {no, ler() -> {vazio, valor, erro}}. */
function controleDe(c, id, ambiente) {
  const rot = c.rotulo;
  if (c.tipo === 'escolha') {
    const sel = el('select', { id }, c.obrigatorio ? null : el('option', { value: '' }, 'Sem escolha'),
      ...c.opcoes.map((o) => el('option', { value: o }, o)));
    return { no: sel, foco: sel, ler: () => (sel.value === '' ? { vazio: true } : { valor: sel.value }) };
  }
  if (c.tipo === 'cor') {
    const inp = el('input', { id, type: 'color', value: '#ffffff' });
    return { no: inp, foco: inp, ler: () => ({ valor: inp.value.toLowerCase() }) };
  }
  if (c.tipo === 'numero') {
    const inp = el('input', { id, type: 'text', inputmode: 'decimal', autocomplete: 'off' });
    return {
      no: inp, foco: inp,
      ler() {
        if (!inp.value.trim()) return { vazio: true };
        const n = lerNumero(inp.value);
        if (!Number.isFinite(n)) return { erro: `${rot}: escreva um número, por exemplo 12.` };
        if (c.inteiro && n !== Math.floor(n)) return { erro: `${rot}: use um número inteiro, sem vírgula.` };
        if ((c.min !== undefined && n < c.min) || (c.max !== undefined && n > c.max)) {
          return { erro: `${rot}: use um número entre ${numero(c.min ?? 0)} e ${numero(c.max ?? 1000000)}.` };
        }
        return { valor: n };
      },
    };
  }
  if (c.tipo === 'imagem') {
    const sel = el('select', { id },
      c.obrigatorio || c.itens ? null : el('option', { value: '' }, 'Sem imagem'),
      ...ambiente.imagens.map((m) => el('option', { value: m.rel }, m.nome)),
      el('option', { value: 'quadro' }, 'Um quadro do vídeo'));
    const seg = el('input', { type: 'text', inputmode: 'decimal', autocomplete: 'off', class: 'estilo-segundo',
      'aria-label': `${rot}: segundo do quadro do vídeo`, hidden: true });
    const mostrar = () => {
      seg.hidden = sel.value !== 'quadro';
      if (!seg.hidden && !seg.value) seg.value = String(ambiente.momento()).replace('.', ',');
    };
    sel.addEventListener('change', mostrar);
    return {
      no: el('div', { class: 'estilo-imagem' }, sel, seg), foco: sel,
      ler() {
        if (sel.value === '') return { vazio: true };
        if (sel.value !== 'quadro') return { valor: sel.value };
        const s = lerNumero(seg.value);
        if (!Number.isFinite(s) || s < 0) return { erro: `${rot}: escreva o segundo do vídeo de onde tirar o quadro.` };
        return { valor: `quadro:${Math.round(s * 100) / 100}` };
      },
    };
  }
  const inp = el('input', { id, type: 'text', autocomplete: 'off', maxlength: String(c.max || 140) });
  return {
    no: inp, foco: inp,
    ler() {
      const t = inp.value.trim();
      if (!t) return { vazio: true };
      if (c.max && t.length > c.max) return { erro: `${rot}: use no máximo ${c.max} letras (tem ${t.length}).` };
      if (c.min && t.length < c.min) return { erro: `${rot}: use pelo menos ${c.min} letras.` };
      return { valor: t };
    },
  };
}

/** Campo do formulario do efeito: {no, ler() -> {vazio, valor, erro}, foco}. */
function campoEfeito(c, ambiente) {
  const base = `ef-${c.id}`;
  const ajuda = el('span', { class: 'ajuda', id: `${base}-ajuda` }, ajudaDoCampo(c));
  const erro = el('p', { class: 'mensagem-erro campo-erro', role: 'alert', hidden: true });
  const mostrarErro = (msg) => { erro.textContent = msg || ''; erro.hidden = !msg; };

  if (!c.itens) {
    const ctl = controleDe(c, base, ambiente);
    ctl.foco.setAttribute('aria-describedby', `${base}-ajuda`);
    return {
      no: campoDe(c.rotulo, base, ctl.no, ajuda, erro), foco: ctl.foco,
      ler() {
        const r = ctl.ler();
        if (r.erro) { mostrarErro(r.erro); return r; }
        if (r.vazio && c.obrigatorio) { const e = { erro: `${c.rotulo}: preencha este campo.` }; mostrarErro(e.erro); return e; }
        mostrarErro('');
        return r;
      },
    };
  }

  const lista = el('ul', { class: 'estilo-itens' });
  const linhas = [];
  const adicionar = el('button', { type: 'button', class: 'botao botao-secundario' }, icone('mais'), el('span', {}, 'Adicionar item'));
  function pintar() {
    lista.replaceChildren(...linhas.map((l, i) => {
      l.rotulo.textContent = `${c.rotulo}, item ${i + 1}`;
      return l.li;
    }));
    adicionar.disabled = linhas.length >= c.itens.max;
    linhas.forEach((l) => { l.tirar.disabled = linhas.length <= 1; });
  }
  function nova() {
    const id = `${base}-${linhas.length}-${Math.random().toString(36).slice(2, 6)}`;
    const ctl = controleDe(c, id, ambiente);
    const rotulo = el('label', { for: id, class: 'sr-only' });
    const tirar = el('button', { type: 'button', class: 'botao botao-secundario', 'aria-label': 'Tirar este item' }, icone('lixo'));
    const linha = { ctl, rotulo, tirar, li: el('li', { class: 'estilo-item' }, rotulo, ctl.no, tirar) };
    tirar.addEventListener('click', () => {
      linhas.splice(linhas.indexOf(linha), 1);
      pintar();
      if (linhas[0]) linhas[0].ctl.foco.focus();
    });
    linhas.push(linha);
    ctl.foco.setAttribute('aria-describedby', `${base}-ajuda`);
    pintar();
    return linha;
  }
  for (let i = 0; i < c.itens.min; i++) nova();
  if (!linhas.length) nova();
  adicionar.addEventListener('click', () => nova().ctl.foco.focus());
  return {
    no: el('fieldset', { class: 'estilo-lista campo' }, el('legend', {}, c.rotulo), ajuda, lista, adicionar, erro),
    foco: linhas[0].ctl.foco,
    ler() {
      const valores = [];
      for (const l of linhas) {
        const r = l.ctl.ler();
        if (r.erro) { mostrarErro(r.erro); return r; }
        if (!r.vazio) valores.push(r.valor);
      }
      if ((valores.length || c.obrigatorio) && valores.length < c.itens.min) {
        const e = { erro: `${c.rotulo}: preencha pelo menos ${c.itens.min} itens.` };
        mostrarErro(e.erro);
        return e;
      }
      mostrarErro('');
      return valores.length ? { valor: valores } : { vazio: true };
    },
  };
}

// ------------------------------------------------------------------ o passo
registrarPasso({
  id: 'estilo',
  opcional: true,
  tarefas: ['aplicar-estilo'],
  video: (estado, slug) => (estado.arquivos.preview
    ? { rel: estado.arquivos.preview, rotulo: 'Preview', versao: versaoDe(slug, 'preview') } : null),
  render(container, ctx) {
    const slug = ctx.slug;
    const carregando = el('p', { class: 'carregando' }, 'Carregando as opções…');
    container.append(
      el('p', { class: 'lead' }, 'Escolha as cores, a fonte, a legenda e os efeitos. O vídeo só muda quando você apertar Aplicar estilo. É opcional: sem isso, o Reel usa o estilo do escritório.'),
      carregando);
    Promise.all([
      api('GET', '/api/banco'),
      api('GET', rota(slug, 'estilo')).catch((e) => ({ falhou: e })),
      api('GET', rota(slug, 'graficos')).catch(() => ({ cards: [] })),
    ]).then(([banco, estilo, graficos]) => {
      if (!carregando.isConnected || ctx.slugAtual() !== slug) return;
      carregando.remove();
      montar(container, ctx, banco, estilo, graficos);
    }).catch((e) => {
      carregando.replaceWith(el('p', { class: 'mensagem-erro', role: 'alert' }, traduzir(e.mensagem)));
    });
  },
});

function montar(container, ctx, banco, estiloLido, graficos) {
  const slug = ctx.slug;
  const estiloIlegivel = !!estiloLido.falhou;
  const aplicado = estiloIlegivel ? { ...copia(PADRAO), cards: { estilo: 'vidro' } } : estiloLido;
  const base = so(aplicado);
  let sel = pendente.get(slug) ? copia(pendente.get(slug)) : copia(base);
  if (mesmo(sel, base)) pendente.delete(slug);
  const itens = { paleta: banco.paletas || [], legenda: banco.legendas || [], efeito: banco.efeitos || [] };
  const fontes = banco.fontes || [];

  const ex = {}; // aba -> {estado: nada|aguardando|preparando|pronto|erro, mapa, job, erro}
  const cartoes = { paletas: [], legendas: [], efeitos: [] };
  let abaAtual = abaAberta.get(slug) || 'paletas';
  if (!ABAS.some((a) => a.id === abaAtual)) abaAtual = 'paletas';
  let noVideo = (graficos.cards || []).filter((c) => c && typeof c === 'object' && c.efeito);

  const chave = (aba) => `${slug}|${aba}|${JSON.stringify(aplicado)}|${ctx.estado.duracao}`;
  for (const a of ABAS.filter((x) => x.exemplo)) {
    const c = cacheQuadros.get(chave(a.id));
    ex[a.id] = c ? { estado: 'pronto', mapa: c } : { estado: 'nada', mapa: {} };
  }

  // ----------------------------------------------------------- barra de aplicar
  const barraTexto = el('p', { id: 'estilo-situacao', class: 'estilo-situacao', role: 'status' });
  const aplicarErro = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
  const aplicar = el('button', { type: 'button', id: 'estilo-aplicar', class: 'botao botao-primario' },
    icone('ok'), el('span', {}, 'Aplicar estilo'));
  const barra = el('div', { id: 'estilo-barra', class: 'estilo-barra' }, barraTexto, aplicar);
  const podeAplicar = ctx.estado.etapas.transcricao === 'pronto' && ctx.estado.etapas.cortes === 'pronto';

  function guardar() {
    if (mesmo(sel, base)) pendente.delete(slug); else pendente.set(slug, copia(sel));
  }
  function atualizarBarra() {
    const mudou = !mesmo(sel, base);
    const ocupado = rodando(slug);
    barra.dataset.mudou = String(mudou);
    const base_ = mudou ? 'Mudanças não aplicadas.'
      : ctx.estado.etapas.estilo === 'pronto' ? 'Estilo aplicado.' : 'Usando o estilo padrão do escritório.';
    barraTexto.textContent = !podeAplicar ? 'Faça os cortes primeiro: o estilo é aplicado ao vídeo já cortado.'
      : ocupado ? `${base_} Para aplicar, espere o trabalho em andamento terminar.` : base_;
    aplicar.disabled = !podeAplicar || ocupado;
  }
  aplicar.addEventListener('click', async () => {
    aplicar.disabled = true;
    aplicarErro.hidden = true;
    const est = { paleta: sel.paleta, fonte: sel.fonte, legenda: { ...sel.legenda }, cards: aplicado.cards || { estilo: 'vidro' } };
    try {
      await iniciarTarefa(slug, 'aplicar-estilo', est);
    } catch (e) {
      aplicarErro.textContent = traduzir(e.mensagem);
      aplicarErro.hidden = false;
    }
    atualizarBarra();
  });

  // ------------------------------------------------------------ cartoes
  function marcar() {
    for (const aba of ['paletas', 'legendas']) {
      const escolhido = aba === 'paletas' ? sel.paleta : sel.legenda.estilo;
      for (const c of cartoes[aba]) {
        const e = c.item.id === escolhido;
        c.li.dataset.escolhido = String(e);
        c.usar.setAttribute('aria-pressed', String(e));
        c.usar.setAttribute('aria-label', e ? `${c.item.nome}: escolhido` : `Usar ${c.item.nome}`);
        c.texto.textContent = e ? 'Escolhido' : 'Usar';
      }
    }
    for (const f of fontesLinhas) {
      const e = f.fonte.nome === sel.fonte;
      f.li.dataset.escolhido = String(e);
      f.usar.setAttribute('aria-pressed', String(e));
      f.texto.textContent = e ? 'Escolhida' : 'Usar';
    }
    posicao.value = sel.legenda.posicao;
    tamanho.value = sel.legenda.tamanho;
    atualizarBarra();
  }
  function mudou() { guardar(); marcar(); }

  function pintarQuadros(aba) {
    const e = ex[aba];
    for (const c of cartoes[aba]) {
      const rel = e.mapa[c.item.id];
      let no;
      if (rel) {
        no = el('img', { class: 'estilo-img', src: urlArquivo(slug, rel), alt: `Exemplo: ${c.item.nome}` });
        no.addEventListener('error', () => no.replaceWith(el('div', { class: 'estilo-sem-exemplo' }, 'Sem exemplo')));
      } else if (e.estado === 'preparando' || e.estado === 'aguardando' || e.estado === 'nada') {
        no = el('div', { class: 'esqueleto', 'aria-hidden': 'true' });
      } else {
        no = el('div', { class: 'estilo-sem-exemplo' }, 'Sem exemplo');
      }
      c.figura.replaceChildren(no);
    }
    const st = status[aba];
    if (!st) return;
    const falhou = e.estado === 'erro';
    st.texto.textContent = e.estado === 'preparando' || e.estado === 'aguardando' ? 'Preparando os exemplos…'
      : falhou ? (e.erro || 'Os exemplos não ficaram prontos.') : '';
    st.texto.hidden = !st.texto.textContent;
    st.texto.classList.toggle('mensagem-erro', falhou);
    st.de_novo.hidden = !falhou;
  }

  function garantir(aba) {
    const e = ex[aba];
    if (!e || e.estado === 'pronto' || e.estado === 'preparando') return;
    const c = cacheQuadros.get(chave(aba));
    if (c) { e.mapa = c; e.estado = 'pronto'; pintarQuadros(aba); return; }
    if (rodando(slug)) { e.estado = 'aguardando'; pintarQuadros(aba); return; }
    e.estado = 'preparando';
    e.erro = '';
    e.job = null;
    pintarQuadros(aba);
    iniciarTarefa(slug, 'quadros', { aba }).then((id) => { e.job = id; }).catch((err) => {
      e.estado = 'erro';
      e.erro = traduzir(err.mensagem);
      pintarQuadros(aba);
    });
  }

  const status = {};
  function cartao(aba, item) {
    const figura = el('div', { class: 'estilo-quadro' });
    const cab = [el('h3', { class: 'estilo-nome' }, item.nome),
      item.descricao ? el('p', { class: 'estilo-desc suave' }, item.descricao) : null];
    const acoes = [];
    const li = el('li', { class: 'cartao estilo-cartao', 'data-id': item.id, 'data-aba': aba, 'data-escolhido': 'false' });
    const c = { li, item, figura };
    if (aba === 'efeitos') {
      acoes.push(el('button', {
        type: 'button', class: 'botao botao-primario estilo-adicionar', 'aria-label': `Adicionar ao vídeo: ${item.nome}`,
        onclick: () => abrirFormulario(item),
      }, icone('mais'), el('span', {}, 'Adicionar ao vídeo')));
    } else {
      c.texto = el('span', { class: 'usar-texto' }, 'Usar');
      c.usar = el('button', {
        type: 'button', class: 'botao botao-secundario estilo-usar', 'aria-pressed': 'false',
        onclick: () => escolher(aba, item),
      }, icone('ok'), c.texto);
      acoes.push(c.usar);
    }
    if ((item.variacoes || []).length) {
      acoes.push(el('button', {
        type: 'button', class: 'botao botao-secundario estilo-parecido',
        'aria-label': `Mais parecido com este: ${item.nome}`, onclick: () => parecidos(aba, item),
      }, 'Mais parecido com este'));
    }
    li.append(figura, ...cab, el('div', { class: 'estilo-acoes' }, ...acoes));
    cartoes[aba].push(c);
    return li;
  }

  function escolher(aba, item) {
    if (aba === 'paletas') sel.paleta = item.id;
    else {
      const d = item.dados || {};
      sel.legenda = { estilo: item.id, posicao: d.posicao_padrao || sel.legenda.posicao, tamanho: d.tamanho_padrao || sel.legenda.tamanho };
    }
    mudou();
  }

  // ----------------------------------------- "mais parecido com este"
  const painelParecidos = {};
  async function parecidos(aba, item) {
    const p = painelParecidos[aba];
    const c = cartoes[aba].find((x) => x.item.id === item.id);
    if (c) c.li.parentElement.prepend(c.li);
    p.titulo.textContent = `Parecidos com ${item.nome}`;
    p.lista.replaceChildren(el('li', { class: 'carregando' }, 'Procurando…'));
    p.caixa.hidden = false;
    p.caixa.dataset.item = item.id;
    try {
      const plural = aba;
      const r = await api('GET', `/api/banco/${plural}/${encodeURIComponent(item.id)}/variacoes?projeto=${encodeURIComponent(slug)}`);
      if (p.caixa.dataset.item !== item.id) return;
      p.lista.replaceChildren(...(r.variacoes || []).map((v) => variacao(aba, item, v)));
      if (!(r.variacoes || []).length) p.lista.replaceChildren(el('li', { class: 'suave' }, 'Este item não tem variações.'));
    } catch (e) {
      p.lista.replaceChildren(el('li', { class: 'mensagem-erro', role: 'alert' }, traduzir(e.mensagem)));
    }
  }

  function variacao(aba, item, v) {
    const d = v.dados || {};
    let amostra = null;
    let detalhe = '';
    let usar = null;
    if (aba === 'paletas') {
      amostra = el('span', { class: 'cores', role: 'img', 'aria-label': 'Cores desta variação' },
        ...['fundo', 'texto', 'destaque', 'apoio'].map((k) => {
          const s = el('span', { class: 'cor' });
          if (HEX.test(d[k] || '')) s.style.background = d[k];
          return s;
        }));
      detalhe = 'Só para ver: por enquanto dá para usar as paletas inteiras da lista.';
    } else if (aba === 'legendas') {
      detalhe = `${rotuloDe(POSICOES, d.posicao_padrao)} · ${rotuloDe(TAMANHOS, d.tamanho_padrao)}`;
      usar = el('button', {
        type: 'button', class: 'botao botao-secundario estilo-usar-variacao', 'aria-label': `Usar: ${v.nome}`,
        onclick: () => {
          sel.legenda = { estilo: item.id, posicao: d.posicao_padrao, tamanho: d.tamanho_padrao };
          mudou();
        },
      }, 'Usar');
    }
    return el('li', { class: 'variacao', 'data-nome': v.nome },
      amostra, el('div', { class: 'variacao-info' }, el('strong', {}, v.nome), el('span', { class: 'suave' }, detalhe)), usar);
  }

  function blocoParecidos(aba) {
    const titulo = el('h3', {});
    const lista = el('ul', { class: 'variacoes' });
    const fechar = el('button', { type: 'button', class: 'botao botao-secundario', onclick: () => { caixa.hidden = true; } }, 'Fechar');
    const caixa = el('section', { class: 'cartao estilo-parecidos', hidden: true, 'aria-live': 'polite', id: `parecidos-${aba}` },
      el('div', { class: 'secao-topo' }, titulo, fechar), lista);
    painelParecidos[aba] = { caixa, titulo, lista };
    return caixa;
  }

  // ------------------------------------------------------------- abas
  function blocoExemplos(aba) {
    const texto = el('p', { class: 'estilo-status suave', role: 'status', hidden: true });
    const deNovo = el('button', { type: 'button', class: 'botao botao-secundario', hidden: true,
      onclick: () => { ex[aba].estado = 'nada'; garantir(aba); } }, 'Preparar os exemplos de novo');
    status[aba] = { texto, de_novo: deNovo };
    return el('div', { class: 'estilo-status-linha' }, texto, deNovo);
  }

  function grade(aba) {
    const lista = itens[ABAS.find((a) => a.id === aba).tipo];
    if (!lista.length) return el('p', { class: 'suave' }, 'Nenhum item encontrado nesta aba.');
    return el('ul', { class: 'estilo-grade', id: `grade-${aba}` }, ...lista.map((it) => cartao(aba, it)));
  }

  const painelPaletas = () => el('div', { class: 'secao' },
    el('p', { class: 'ajuda' }, 'Cada cartão mostra um quadro do seu vídeo com aquelas cores.'),
    blocoExemplos('paletas'), blocoParecidos('paletas'), grade('paletas'));

  const posicao = el('select', { id: 'legenda-posicao' }, ...POSICOES.map(([v, t]) => el('option', { value: v }, t)));
  const tamanho = el('select', { id: 'legenda-tamanho' }, ...TAMANHOS.map(([v, t]) => el('option', { value: v }, t)));
  posicao.addEventListener('change', () => { sel.legenda.posicao = posicao.value; mudou(); });
  tamanho.addEventListener('change', () => { sel.legenda.tamanho = tamanho.value; mudou(); });
  const painelLegendas = () => el('div', { class: 'secao' },
    el('div', { class: 'cartao campo-dupla estilo-legenda-ajustes' },
      campoDe('Posição da legenda', 'legenda-posicao', posicao),
      campoDe('Tamanho das letras', 'legenda-tamanho', tamanho)),
    el('p', { class: 'ajuda' }, 'Os exemplos abaixo mostram a posição e o tamanho que já estão aplicados. A mudança aparece no preview depois de Aplicar estilo.'),
    blocoExemplos('legendas'), blocoParecidos('legendas'), grade('legendas'));

  const fontesLinhas = [];
  function painelFontes() {
    const lista = el('ul', { class: 'fontes', id: 'lista-fontes' });
    fontes.forEach((f, i) => {
      const aceita = FONTES_ACEITAS.includes(f.nome);
      let familia = 'Poppins, sans-serif';
      if (f.nome !== 'Poppins' && f.arquivo) {
        const alias = `previa-fonte-${i}`;
        try {
          const face = new FontFace(alias, `url(/static/fonts/${encodeURIComponent(f.arquivo)})`);
          face.load().then(() => document.fonts.add(face)).catch(() => {});
          familia = `${alias}, sans-serif`;
        } catch { familia = 'inherit'; }
      }
      const nome = el('strong', { class: 'fonte-nome' }, f.nome);
      nome.style.fontFamily = familia;
      const texto = el('span', { class: 'usar-texto' }, 'Usar');
      const usar = el('button', {
        type: 'button', class: 'botao botao-secundario estilo-usar', 'aria-pressed': 'false', disabled: !aceita,
        'aria-describedby': aceita ? null : `fonte-aviso-${i}`,
        onclick: () => { sel.fonte = f.nome; mudou(); },
      }, icone('ok'), texto);
      const li = el('li', { class: 'cartao fonte', 'data-nome': f.nome, 'data-escolhido': 'false' },
        el('div', { class: 'fonte-info' }, nome,
          aceita ? null : el('span', { class: 'selo' }, 'Em breve'),
          aceita ? null : el('span', { class: 'ajuda', id: `fonte-aviso-${i}` }, 'Por enquanto o editor só usa a fonte Poppins nas legendas e nos efeitos.')),
        usar);
      fontesLinhas.push({ li, fonte: f, usar, texto });
      lista.append(li);
    });
    return el('div', { class: 'secao' },
      fontes.length ? lista : el('p', { class: 'suave' }, 'Nenhuma fonte encontrada.'),
      el('p', { class: 'ajuda', id: 'fontes-ajuda' }, 'Para ter mais fontes, coloque o arquivo .ttf na pasta assets/fonts/'));
  }

  function painelNotas() {
    return el('div', { class: 'secao estilo-notas' },
      el('h3', {}, 'Como funciona'),
      el('p', {}, 'Escolha um item em cada aba e aperte Aplicar estilo. O editor monta o preview de novo com as suas escolhas e ele aparece no player ao lado.'),
      el('p', {}, 'Cada cartão mostra um quadro do seu vídeo. Os exemplos são preparados quando você abre a aba e ficam guardados para a próxima vez.'),
      el('p', {}, 'Os efeitos que você adiciona ao vídeo aparecem no preview na próxima vez que ele for montado.'),
      el('h3', {}, 'Como adicionar itens ao banco'),
      el('p', {}, 'Para criar uma paleta, uma legenda ou um efeito novo, copie a pasta de um item parecido dentro da pasta banco, troque o nome, a descrição e os valores no arquivo que está dentro dela e abra o editor de novo.'),
      el('p', {}, 'Se algo estiver errado, o item não aparece e o motivo é mostrado no aviso "itens do banco não carregaram".'),
      el('p', {}, 'Para ter mais fontes, coloque o arquivo .ttf na pasta assets/fonts/'));
  }

  // ------------------------------------------------------ efeitos no video
  const materiaisDoReel = { lista: null };
  const lugarForm = el('div', { id: 'efeito-lugar' });
  const listaNoVideo = el('ul', { id: 'efeitos-no-video', class: 'estilo-no-video' });
  const tituloNoVideo = el('h3', {}, 'Efeitos no vídeo');
  const erroNoVideo = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
  const caixaNoVideo = el('section', { class: 'secao', 'aria-labelledby': 'efeitos-no-video-titulo' }, tituloNoVideo, erroNoVideo, listaNoVideo);
  tituloNoVideo.id = 'efeitos-no-video-titulo';

  const nomeEfeito = (id) => (itens.efeito.find((x) => x.id === id) || {}).nome || 'Efeito';
  function resumoDe(c) {
    const campos = c.campos && typeof c.campos === 'object' ? c.campos : {};
    for (const v of Object.values(campos)) {
      if (typeof v === 'string' && !/^(materiais\/|quadro:)/.test(v)) return v;
      if (Array.isArray(v) && typeof v[0] === 'string' && !/^(materiais\/|quadro:)/.test(v[0])) return v.join(' · ');
    }
    return '';
  }
  function pintarNoVideo() {
    caixaNoVideo.hidden = noVideo.length === 0;
    const ordenados = noVideo.slice().sort((a, b) => (a.at || 0) - (b.at || 0));
    listaNoVideo.replaceChildren(...ordenados.map((c) => {
      const nome = nomeEfeito(c.efeito);
      const resumo = resumoDe(c);
      return el('li', { class: 'cartao estilo-no-video-item', 'data-id': c.id },
        el('div', { class: 'card-info' },
          el('strong', { class: 'card-titulo' }, nome),
          resumo ? el('span', { class: 'card-texto' }, resumo.length > 80 ? `${resumo.slice(0, 79)}…` : resumo) : null,
          el('span', { class: 'suave card-quando' }, `Aos ${relogio(c.at || 0)} · por ${segundos(c.dur || 0)}`)),
        el('button', {
          type: 'button', class: 'botao botao-secundario efeito-remover', 'aria-label': `Remover ${nome}`,
          onclick: (ev) => remover(c, ev.currentTarget),
        }, icone('lixo'), el('span', {}, 'Remover')));
    }));
  }
  async function gravarGraficos(mudar) {
    const atual = await api('GET', rota(slug, 'graficos')); // le de novo: nao perde os cards existentes
    const cards = mudar(Array.isArray(atual.cards) ? atual.cards : []);
    const r = await api('PUT', rota(slug, 'graficos'), { cards });
    noVideo = (r.cards || []).filter((c) => c && typeof c === 'object' && c.efeito);
    pintarNoVideo();
    ctx.atualizar();
    return r;
  }
  async function remover(c, botao) {
    erroNoVideo.hidden = true;
    botao.disabled = true;
    try {
      await gravarGraficos((cards) => cards.filter((x) => x.id !== c.id));
      toast('Efeito removido.', 'ok');
    } catch (e) {
      erroNoVideo.textContent = e.status === 409 ? 'Espere o trabalho em andamento terminar e tente de novo.' : traduzir(e.mensagem);
      erroNoVideo.hidden = false;
      botao.disabled = false;
    }
  }

  async function abrirFormulario(item) {
    if (materiaisDoReel.lista === null) {
      try { materiaisDoReel.lista = (await api('GET', rota(slug, 'materiais'))).materiais || []; } catch { materiaisDoReel.lista = []; }
    }
    const dur = item.duracao || { padrao: 3, min: 1, max: 6 };
    const momento = el('input', { id: 'efeito-momento', type: 'text', inputmode: 'decimal', autocomplete: 'off', 'aria-describedby': 'efeito-momento-ajuda' });
    const agora = () => Math.round((ctx.player && ctx.player.temVideo() ? ctx.player.agora() : 0) * 10) / 10;
    momento.value = String(agora()).replace('.', ',');
    const usarPonto = el('button', { type: 'button', id: 'efeito-usar-ponto', class: 'botao botao-secundario',
      onclick: () => { momento.value = String(agora()).replace('.', ','); } }, icone('relogio'), el('span', {}, 'Usar o ponto do vídeo'));
    const duracao = el('input', { id: 'efeito-duracao', type: 'text', inputmode: 'decimal', autocomplete: 'off', 'aria-describedby': 'efeito-duracao-ajuda' });
    duracao.value = String(dur.padrao).replace('.', ',');
    const ambiente = {
      imagens: (materiaisDoReel.lista || []).filter((m) => m.tipo === 'imagem'),
      momento: () => { const t = lerMomento(momento.value); return Number.isFinite(t) ? t : 0; },
    };
    const campos = item.campos.map((c) => campoEfeito(c, ambiente));
    const erroGeral = el('p', { id: 'efeito-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
    const salvar = el('button', { type: 'submit', id: 'efeito-salvar', class: 'botao botao-primario' }, icone('ok'), el('span', {}, 'Adicionar ao vídeo'));
    const cancelar = el('button', { type: 'button', id: 'efeito-cancelar', class: 'botao botao-secundario', onclick: fechar }, 'Cancelar');
    const form = el('form', { id: 'efeito-form', class: 'cartao formulario card-form', novalidate: true, 'data-efeito': item.id },
      el('h3', {}, item.nome),
      item.descricao ? el('p', { class: 'suave' }, item.descricao) : null,
      ...campos.map((c) => c.no),
      el('div', { class: 'campo-dupla' },
        campoDe('Aparece aos (segundos)', 'efeito-momento', momento,
          el('span', { id: 'efeito-momento-ajuda', class: 'ajuda' }, 'Conta no preview, já com os cortes.')),
        campoDe('Fica na tela por (segundos)', 'efeito-duracao', duracao,
          el('span', { id: 'efeito-duracao-ajuda', class: 'ajuda' }, `Entre ${numero(dur.min)} e ${numero(dur.max)} segundos.`))),
      usarPonto, erroGeral, el('div', { class: 'acoes' }, salvar, cancelar));
    function fechar() { lugarForm.replaceChildren(); }
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      erroGeral.hidden = true;
      const valores = {};
      let primeiro = null;
      item.campos.forEach((c, i) => {
        const r = campos[i].ler();
        if (r.erro) { if (!primeiro) primeiro = campos[i].foco; return; }
        if (!r.vazio) valores[c.id] = r.valor;
      });
      const erros = [];
      for (const grupo of (item.dados && item.dados.mesmo_tamanho) || []) {
        const tams = new Set(grupo.map((g) => (Array.isArray(valores[g]) ? valores[g].length : 0)));
        if (tams.size > 1) {
          const rots = grupo.map((g) => (item.campos.find((c) => c.id === g) || {}).rotulo || g);
          erros.push(`${rots.join(' e ')} precisam ter a mesma quantidade de itens.`);
        }
      }
      const at = lerMomento(momento.value);
      const d = lerNumero(duracao.value);
      if (!Number.isFinite(at)) { erros.push('O momento precisa ser um número de segundos, por exemplo 3 ou 3,5.'); primeiro = primeiro || momento; }
      if (!Number.isFinite(d) || d < dur.min || d > dur.max) {
        erros.push(`A duração precisa ficar entre ${numero(dur.min)} e ${numero(dur.max)} segundos.`);
        primeiro = primeiro || duracao;
      }
      if (primeiro || erros.length) {
        erroGeral.textContent = erros.length ? erros.join(' ') : 'Confira os campos marcados.';
        erroGeral.hidden = false;
        if (primeiro) primeiro.focus();
        return;
      }
      salvar.disabled = true;
      try {
        await gravarGraficos((cards) => {
          const usados = new Set(cards.map((c) => c.id));
          let n = cards.length + 1;
          while (usados.has(`efeito-${n}`)) n++;
          return [...cards, { id: `efeito-${n}`, efeito: item.id, campos: valores, at: Math.round(at * 100) / 100, dur: Math.round(d * 100) / 100 }];
        });
        toast('Efeito adicionado ao vídeo.', 'ok');
        fechar();
      } catch (e) {
        erroGeral.textContent = e.status === 409 ? 'Espere o trabalho em andamento terminar e tente de novo.' : traduzir(e.mensagem);
        erroGeral.hidden = false;
      } finally {
        salvar.disabled = false;
      }
    });
    lugarForm.replaceChildren(form);
    form.scrollIntoView({ block: 'nearest' });
    const alvo = campos[0] ? campos[0].foco : momento;
    alvo.focus({ preventScroll: true });
  }

  const painelEfeitos = () => {
    pintarNoVideo();
    return el('div', { class: 'secao' },
      el('p', { class: 'ajuda' }, 'Efeitos são animações curtas por cima do vídeo. Escolha um, preencha os campos e diga quando ele aparece.'),
      caixaNoVideo, lugarForm, blocoExemplos('efeitos'), blocoParecidos('efeitos'), grade('efeitos'));
  };

  // ------------------------------------------------------------- montagem
  const erros = banco.erros || [];
  const avisoBanco = erros.length ? el('div', { id: 'aviso-banco', class: 'mensagem-aviso estilo-aviso-banco' },
    el('details', {},
      el('summary', {}, erros.length === 1 ? '1 item do banco não carregou' : `${erros.length} itens do banco não carregaram`),
      el('ul', { class: 'estilo-erros-banco' }, ...erros.map((e) => el('li', {},
        el('strong', {}, String(e.pasta || 'Item')), ' ', String(e.motivo || ''))))))
    : null;
  const avisoEstilo = estiloIlegivel ? el('p', { class: 'mensagem-aviso', role: 'status' },
    'Não foi possível ler o estilo guardado deste Reel. Escolha de novo e aplique.') : null;

  const paineis = { paletas: painelPaletas(), fontes: painelFontes(), legendas: painelLegendas(), efeitos: painelEfeitos(), notas: painelNotas() };
  const botoes = ABAS.map((a) => el('button', {
    type: 'button', role: 'tab', id: `tab-estilo-${a.id}`, class: 'aba', 'aria-controls': `aba-estilo-${a.id}`,
    'data-aba': a.id, onclick: () => abrir(a.id),
  }, a.rotulo));
  const paineisNos = ABAS.map((a) => {
    const p = paineis[a.id];
    p.id = `aba-estilo-${a.id}`;
    p.setAttribute('role', 'tabpanel');
    p.setAttribute('aria-labelledby', `tab-estilo-${a.id}`);
    return p;
  });
  function abrir(id) {
    abaAtual = id;
    abaAberta.set(slug, id);
    ABAS.forEach((a, i) => {
      const s = a.id === id;
      botoes[i].setAttribute('aria-selected', String(s));
      botoes[i].tabIndex = s ? 0 : -1;
      paineisNos[i].hidden = !s;
    });
    if (ex[id]) garantir(id);
  }
  const listaAbas = el('div', { class: 'abas', role: 'tablist', 'aria-label': 'Opções de estilo' }, ...botoes);
  listaAbas.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
    const i = botoes.indexOf(document.activeElement);
    if (i < 0) return;
    const j = (i + (e.key === 'ArrowRight' ? 1 : botoes.length - 1)) % botoes.length;
    botoes[j].focus();
    abrir(ABAS[j].id);
  });

  const quadro = quadroTarefa(slug, ['quadros', 'aplicar-estilo'], {
    extra: { quadros: 'Você já pode escolher enquanto os exemplos aparecem.' },
  });
  container.append(...[avisoBanco, avisoEstilo, quadro, listaAbas, ...paineisNos, aplicarErro, barra].filter(Boolean));
  marcar();
  for (const a of ABAS.filter((x) => x.exemplo)) pintarQuadros(a.id);

  const parar = ouvir(slug, (job) => {
    if (!container.isConnected) { parar(); return; }
    if (job && job.estado !== 'rodando') {
      for (const a of ABAS.filter((x) => x.exemplo)) {
        const e = ex[a.id];
        if (e.estado !== 'preparando' || job.id !== e.job) continue;
        if (job.estado === 'ok') {
          e.mapa = mapear(job.saidas, a.tipo);
          cacheQuadros.set(chave(a.id), e.mapa);
          e.estado = 'pronto';
        } else {
          e.estado = 'erro';
          e.erro = '';
        }
        pintarQuadros(a.id);
      }
    }
    if (!rodando(slug) && ex[abaAtual] && ex[abaAtual].estado === 'aguardando') {
      ex[abaAtual].estado = 'nada';
      garantir(abaAtual);
    }
    atualizarBarra();
  });
  abrir(abaAtual);
}

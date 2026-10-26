// Passo Video, modo "Juntar vários trechos": enviar varios arquivos em sequencia, deixar na
// ordem certa e montar um video so. O envio continua se a pessoa trocar de passo; respostas
// de um Reel que ja nao esta aberto so atualizam a memoria daquele Reel, nunca a tela.
import { EDITOR_FECHADO, TOKEN, api, el, icone, relogio, tamanho, toast } from '../nucleo.js';
import { traduzir } from '../mensagens.js';
import { iniciarTarefa, quadroTarefa, rodando } from '../tarefa.js';

export const EXTENSOES = ['.mp4', '.mov', '.m4v', '.webm', '.mkv'];
export const FORMATOS = 'MP4, MOV, M4V, WEBM ou MKV';
const MAX_PADRAO = 40;

export function extensao(nome) {
  const i = nome.lastIndexOf('.');
  return i >= 0 ? nome.slice(i).toLowerCase() : '';
}

const listas = new Map(); // slug -> ultima lista conhecida do servidor
let fila = null; // envio em andamento (ou o resumo do ultimo): {slug, itens, xhr, ativo, parou}
let repintar = null; // repinta a tela aberta (ou null)

function avisarTela() { if (repintar) repintar(); }

const plural = (n, um, varios) => `${n} ${n === 1 ? um : varios}`;
const duracaoTexto = (s) => relogio(s);

function mensagemDoEnvio(xhr, limite) {
  let msg = '';
  try { msg = JSON.parse(xhr.responseText).erro || ''; } catch { /* sem JSON */ }
  if (xhr.status === 413) {
    return `O arquivo passa do limite do editor${limite ? ` (${tamanho(limite)})` : ''}. Exporte o vídeo em tamanho menor.`;
  }
  if (xhr.status === 401) return 'A chave de acesso não vale mais. Feche esta aba e abra o editor de novo pelo ícone.';
  if (xhr.status === 409) return 'Há um trabalho em andamento neste Reel. Espere terminar para mudar a lista.';
  return traduzir(msg) || `O editor respondeu com um erro (${xhr.status}). Tente de novo.`;
}

// ------------------------------------------------------------------ envio
function iniciarEnvio(arquivos, ctx) {
  const slug = ctx.slug;
  if (fila && fila.ativo) {
    toast('Já há trechos sendo enviados. Espere terminar ou cancele.', 'info');
    return;
  }
  const atual = listas.get(slug);
  const maximo = (atual && atual.max_clipes) || MAX_PADRAO;
  let vagas = maximo - (atual ? atual.clipes.length : 0);
  const limite = ctx.config && ctx.config.max_upload;
  const itens = [...arquivos].map((arquivo) => {
    const it = { nome: arquivo.name, arquivo, tamanho: arquivo.size, estado: 'espera', enviado: 0, erro: '' };
    if (!EXTENSOES.includes(extensao(arquivo.name))) {
      Object.assign(it, { estado: 'erro', erro: `Este tipo de arquivo não é aceito. Use um vídeo ${FORMATOS}.` });
    } else if (arquivo.size === 0) {
      Object.assign(it, { estado: 'erro', erro: 'O arquivo está vazio.' });
    } else if (limite && arquivo.size > limite) {
      Object.assign(it, { estado: 'erro',
        erro: `Tem ${tamanho(arquivo.size)} e o limite do editor é ${tamanho(limite)}. Exporte em tamanho menor.` });
    } else if (vagas <= 0) {
      Object.assign(it, { estado: 'erro', erro: `Um Reel aceita até ${maximo} trechos. Remova algum antes de enviar outro.` });
    } else {
      vagas -= 1;
      it.valido = true;
    }
    return it;
  });
  fila = { slug, itens, xhr: null, ativo: true, parou: false };
  seguirFila(ctx, fila);
}

function seguirFila(ctx, f) {
  if (f !== fila) return;
  const it = f.itens.find((x) => x.estado === 'espera');
  if (!it) {
    f.ativo = false;
    f.xhr = null;
    const ok = f.itens.filter((x) => x.estado === 'ok').length;
    if (ctx.slugAtual() !== f.slug && ok) toast(`${plural(ok, 'trecho chegou', 'trechos chegaram')} ao Reel que você deixou aberto antes.`, 'ok');
    avisarTela();
    return;
  }
  enviarUm(it, ctx, f);
}

function parar(f, motivo) {
  f.parou = true;
  for (const x of f.itens) if (x.estado === 'espera') Object.assign(x, { estado: 'parado', erro: motivo });
}

function enviarUm(it, ctx, f) {
  const slug = f.slug;
  const limite = ctx.config && ctx.config.max_upload;
  const xhr = new XMLHttpRequest();
  f.xhr = xhr;
  it.estado = 'enviando';
  xhr.open('PUT', `/api/projects/${encodeURIComponent(slug)}/clipes`);
  xhr.setRequestHeader('X-Token', TOKEN);
  xhr.setRequestHeader('X-Filename', encodeURIComponent(it.nome));
  xhr.upload.onprogress = (e) => {
    if (f !== fila || f.xhr !== xhr) return;
    it.enviado = e.loaded;
    if (e.lengthComputable) it.tamanho = e.total;
    it.conferindo = e.lengthComputable && e.loaded >= e.total;
    avisarTela();
  };
  xhr.upload.onload = () => { if (f === fila && f.xhr === xhr) { it.conferindo = true; avisarTela(); } };
  const fim = () => { it.arquivo = null; seguirFila(ctx, f); };
  xhr.onload = () => {
    if (f !== fila) return;
    it.conferindo = false;
    if (xhr.status === 200) {
      try { listas.set(slug, JSON.parse(xhr.responseText)); } catch { /* a proxima leitura corrige */ }
      Object.assign(it, { estado: 'ok', enviado: it.tamanho });
    } else {
      Object.assign(it, { estado: 'erro', erro: mensagemDoEnvio(xhr, limite) });
      if (xhr.status === 401 || xhr.status === 409) parar(f, 'Não foi enviado porque o anterior falhou.');
    }
    fim();
  };
  xhr.onerror = () => {
    if (f !== fila) return;
    Object.assign(it, { estado: 'erro', erro: `A conexão com o editor caiu durante o envio. ${EDITOR_FECHADO}` });
    parar(f, 'Não foi enviado porque a conexão caiu.');
    fim();
  };
  xhr.onabort = () => {
    if (f !== fila) return;
    Object.assign(it, { estado: 'cancelado', erro: 'Envio cancelado.' });
    parar(f, 'Envio cancelado.');
    for (const x of f.itens) if (x.estado === 'parado') x.estado = 'cancelado';
    fim();
  };
  xhr.send(it.arquivo);
  avisarTela();
}

// ------------------------------------------------------------------ tela
export function painelClipes(ctx) {
  const slug = ctx.slug;
  let ocupado = rodando(slug);
  let salvando = false;
  let confirmando = null; // lista `perde` do servidor, quando falta confirmar
  let aviso = '';
  let foco = null; // {arquivo, acao} para devolver o foco depois de repintar
  let carregou = false;

  const entrada = el('input', { id: 'arquivos-clipes', type: 'file', multiple: true, class: 'sr-only',
    accept: 'video/*,' + EXTENSOES.join(',') });
  entrada.addEventListener('change', () => {
    const arquivos = [...(entrada.files || [])];
    entrada.value = '';
    if (arquivos.length) iniciarEnvio(arquivos, ctx);
  });
  const limite = ctx.config && ctx.config.max_upload;
  const zona = el('label', { class: 'soltar soltar-baixo', for: 'arquivos-clipes' },
    icone('enviar', 'icone-grande'),
    el('strong', {}, 'Arraste os trechos para cá'),
    el('span', { class: 'suave' }, 'ou'),
    el('span', { class: 'botao botao-secundario falso-botao' }, 'Escolher arquivos'),
    el('span', { class: 'ajuda' }, `Pode escolher vários de uma vez · ${FORMATOS}${limite ? ` · até ${tamanho(limite)} cada` : ''}`),
    entrada);
  zona.addEventListener('dragover', (e) => { e.preventDefault(); zona.classList.add('ativa'); });
  zona.addEventListener('dragleave', () => zona.classList.remove('ativa'));
  zona.addEventListener('drop', (e) => {
    e.preventDefault();
    zona.classList.remove('ativa');
    const arquivos = e.dataTransfer ? [...e.dataTransfer.files] : [];
    if (arquivos.length) iniciarEnvio(arquivos, ctx);
  });

  // progresso do envio: um trecho e o conjunto
  const textoEnvio = el('p', { id: 'clipes-envio-texto' });
  const barraArquivo = el('progress', { id: 'clipes-barra-arquivo', max: '100', value: '0', 'aria-label': 'Progresso deste trecho' });
  const barraGeral = el('progress', { id: 'clipes-barra-geral', max: '100', value: '0', 'aria-label': 'Progresso de todos os trechos' });
  const cancelar = el('button', { type: 'button', id: 'clipes-cancelar', class: 'botao botao-secundario' }, 'Cancelar envio');
  cancelar.addEventListener('click', () => { if (fila && fila.xhr) fila.xhr.abort(); });
  const caixaEnvio = el('div', { id: 'clipes-envio', class: 'cartao envio', hidden: true, 'aria-live': 'polite' },
    el('div', { class: 'envio-linha' }, textoEnvio, cancelar), barraArquivo, barraGeral);

  const avisos = el('div', { id: 'clipes-avisos', class: 'clipes-avisos', hidden: true });
  const erroGeral = el('p', { id: 'clipes-erro', class: 'mensagem-erro', role: 'alert', hidden: true });

  const titulo = el('h2', { id: 'clipes-titulo', class: 'clipes-titulo' }, 'Trechos');
  const total = el('p', { id: 'clipes-total', class: 'suave' });
  const lista = el('ol', { id: 'clipes-lista', class: 'clipes-lista', 'aria-labelledby': 'clipes-titulo' });
  const vazio = el('p', { id: 'clipes-vazio', class: 'suave' }, 'Nenhum trecho ainda. Envie o primeiro acima.');
  const situacao = el('p', { id: 'clipes-situacao', class: 'mensagem-info', hidden: true });
  const montar = el('button', { type: 'button', id: 'clipes-montar', class: 'botao botao-primario' }, 'Montar vídeo');

  const confirmarTitulo = el('h3', { id: 'clipes-confirmar-titulo' }, 'Montar um vídeo novo apaga o que já foi feito');
  const confirmarTexto = el('p', {});
  const confirmarLista = el('ul', { id: 'clipes-perde' });
  const confirmarSim = el('button', { type: 'button', id: 'clipes-confirmar-sim', class: 'botao botao-primario' },
    'Entendi, montar e recomeçar os cortes');
  const confirmarNao = el('button', { type: 'button', id: 'clipes-confirmar-nao', class: 'botao botao-secundario' }, 'Voltar');
  const confirmar = el('div', { id: 'clipes-confirmar', class: 'mensagem-aviso confirmar-juntar', role: 'group',
    'aria-labelledby': 'clipes-confirmar-titulo', hidden: true },
  confirmarTitulo, confirmarTexto, confirmarLista,
  el('p', { class: 'ajuda' }, 'O estilo, a capa e os materiais continuam como estão.'),
  el('div', { class: 'acoes' }, confirmarSim, confirmarNao));

  const quadro = quadroTarefa(slug, ['juntar'], {
    aoMudar: (ativo) => { if (ativo !== ocupado) { ocupado = ativo; if (carregou) pintar(); } },
    extra: { juntar: 'Pode levar alguns minutos. Pode trocar de passo; o trabalho continua.' },
  });

  async function iniciarMontagem(confirmou) {
    aviso = '';
    try {
      await iniciarTarefa(slug, 'juntar', { confirmar: confirmou });
      confirmando = null;
    } catch (e) {
      if (e.codigo === 'precisa_confirmar') {
        confirmando = (e.dados && Array.isArray(e.dados.perde)) ? e.dados.perde : [];
        foco = { confirmar: true };
      } else {
        confirmando = null;
        aviso = traduzir(e.mensagem) || e.mensagem;
      }
    }
    pintar();
  }
  montar.addEventListener('click', () => iniciarMontagem(false));
  confirmarSim.addEventListener('click', () => iniciarMontagem(true));
  confirmarNao.addEventListener('click', () => { confirmando = null; foco = { montar: true }; pintar(); });

  async function mudarLista(metodo, caminho, corpo, depois) {
    if (salvando) return;
    salvando = true;
    aviso = '';
    pintar();
    try {
      const dados = await api(metodo, `/api/projects/${encodeURIComponent(slug)}/clipes${caminho}`, corpo);
      listas.set(slug, dados);
    } catch (e) {
      aviso = traduzir(e.mensagem) || e.mensagem;
      if (e.status === 404) carregar();
    }
    salvando = false;
    if (depois) depois();
    pintar();
  }

  function mover(arquivos, de, para, acao) {
    if (para < 0 || para >= arquivos.length || de === para) return;
    const nova = [...arquivos];
    const [x] = nova.splice(de, 1);
    nova.splice(para, 0, x);
    foco = { arquivo: x, acao };
    confirmando = null;
    mudarLista('POST', '/ordem', { ordem: nova });
  }

  function remover(c) {
    // o foco vai para o trecho que ocupava o lugar
    const arqs = listas.get(slug).clipes.map((x) => x.arquivo);
    const i = arqs.indexOf(c.arquivo);
    const vizinho = arqs[i + 1] || arqs[i - 1];
    foco = vizinho ? { arquivo: vizinho, acao: 'remover' } : { montar: true };
    confirmando = null;
    mudarLista('DELETE', `/${encodeURIComponent(c.arquivo)}`);
  }

  let arrastando = null;
  function linha(c, i, arqs) {
    const bloqueado = ocupado || salvando || !!(fila && fila.ativo);
    const rotulo = `o trecho ${i + 1}, ${c.nome}`;
    const botao = (acao, texto, desligado, aoClicar) => el('button', {
      type: 'button', class: 'botao botao-secundario botao-pequeno', 'data-acao': acao,
      'aria-label': `${texto} ${rotulo}`, disabled: desligado || bloqueado, onclick: aoClicar,
    }, texto);
    const li = el('li', { class: 'clipe', 'data-arquivo': c.arquivo, draggable: bloqueado ? 'false' : 'true' },
      el('span', { class: 'clipe-num', 'aria-hidden': 'true' }, String(i + 1)),
      el('div', { class: 'clipe-info' },
        el('strong', { class: 'clipe-nome' }, c.nome),
        el('span', { class: 'suave clipe-meta' }, `${duracaoTexto(c.duracao)} · ${tamanho(c.tamanho)}`)),
      el('div', { class: 'clipe-acoes' },
        botao('subir', 'Subir', i === 0, () => mover(arqs, i, i - 1, 'subir')),
        botao('descer', 'Descer', i === arqs.length - 1, () => mover(arqs, i, i + 1, 'descer')),
        botao('remover', 'Remover', false, () => remover(c))));
    li.addEventListener('dragstart', (e) => {
      if (bloqueado) { e.preventDefault(); return; }
      arrastando = c.arquivo;
      li.classList.add('arrastando');
      if (e.dataTransfer) { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', c.nome); }
    });
    li.addEventListener('dragend', () => {
      arrastando = null;
      li.classList.remove('arrastando');
      for (const x of lista.querySelectorAll('.alvo')) x.classList.remove('alvo');
    });
    li.addEventListener('dragover', (e) => {
      if (!arrastando || arrastando === c.arquivo) return;
      e.preventDefault();
      li.classList.add('alvo');
    });
    li.addEventListener('dragleave', () => li.classList.remove('alvo'));
    li.addEventListener('drop', (e) => {
      li.classList.remove('alvo');
      if (!arrastando || arrastando === c.arquivo) return;
      e.preventDefault();
      mover(arqs, arqs.indexOf(arrastando), i, 'subir');
      arrastando = null;
    });
    return li;
  }

  function pintarEnvio() {
    const meu = fila && fila.slug === slug ? fila : null;
    const enviando = !!(meu && meu.ativo);
    caixaEnvio.hidden = !enviando;
    zona.classList.toggle('desligada', enviando || ocupado);
    if (enviando) {
      const lote = meu.itens.filter((x) => x.valido);
      const totalBytes = lote.reduce((n, x) => n + (x.tamanho || 0), 0);
      const feitos = lote.reduce((n, x) => n + (x.estado === 'ok' ? x.tamanho : Math.min(x.enviado || 0, x.tamanho || 0)), 0);
      const atual = lote.find((x) => x.estado === 'enviando');
      const numero = atual ? lote.indexOf(atual) + 1 : 0;
      const de = lote.length;
      if (atual) {
        const pct = atual.tamanho ? Math.min(100, Math.floor((atual.enviado / atual.tamanho) * 100)) : 0;
        barraArquivo.value = pct;
        barraArquivo.setAttribute('aria-valuetext', `${pct}%`);
        textoEnvio.textContent = atual.conferindo
          ? `Conferindo o trecho ${numero} de ${de}: ${atual.nome}…`
          : `Enviando o trecho ${numero} de ${de}: ${atual.nome} (${pct}%)`;
        cancelar.hidden = !!atual.conferindo;
      }
      const geral = totalBytes ? Math.min(100, Math.floor((feitos / totalBytes) * 100)) : 0;
      barraGeral.value = geral;
      barraGeral.setAttribute('aria-valuetext', `${geral}% de todos os trechos`);
    }
    // resumo do que deu errado no ultimo envio
    const problemas = meu && !meu.ativo ? meu.itens.filter((x) => x.estado === 'erro' || x.estado === 'cancelado' || x.estado === 'parado') : [];
    avisos.hidden = !problemas.length;
    if (problemas.length) {
      const ok = meu.itens.filter((x) => x.estado === 'ok').length;
      const fechar = el('button', { type: 'button', id: 'clipes-avisos-fechar', class: 'botao botao-secundario botao-pequeno',
        onclick: () => { fila = null; pintar(); } }, 'Fechar aviso');
      avisos.replaceChildren(
        el('p', { class: 'mensagem-erro', role: 'alert' },
          ok ? `${plural(ok, 'trecho chegou', 'trechos chegaram')}, mas ${plural(problemas.length, 'não chegou', 'não chegaram')}:`
            : `${problemas.length === 1 ? 'O trecho não chegou' : 'Os trechos não chegaram'}:`),
        el('ul', { class: 'clipes-problemas' }, problemas.map((x) => el('li', {}, el('strong', {}, x.nome), ` — ${x.erro}`))),
        fechar);
    }
  }

  function pintar() {
    const dados = listas.get(slug);
    const itens = dados ? dados.clipes : [];
    const arqs = itens.map((c) => c.arquivo);
    const envioAtivo = !!(fila && fila.ativo && fila.slug === slug);
    const bloqueado = ocupado || salvando || envioAtivo;
    pintarEnvio();
    erroGeral.hidden = !aviso;
    erroGeral.textContent = aviso;
    titulo.hidden = !dados;
    vazio.hidden = !dados || itens.length > 0;
    lista.replaceChildren(...itens.map((c, i) => linha(c, i, arqs)));
    total.hidden = !itens.length;
    total.textContent = itens.length
      ? `${plural(itens.length, 'trecho', 'trechos')} · ${duracaoTexto(dados.total_duracao)} no total`
      : '';
    montar.disabled = bloqueado || !itens.length;
    montar.hidden = ocupado;
    const temVideo = !!(ctx.estado && ctx.estado.etapas && ctx.estado.etapas.video === 'pronto');
    let msg = '';
    if (dados && dados.montado && dados.desatualizada) {
      msg = 'A lista mudou depois da última montagem. Monte de novo para o vídeo acompanhar a lista.';
    } else if (dados && dados.montado) {
      msg = 'O vídeo deste Reel foi montado com estes trechos, na ordem mostrada.';
    } else if (temVideo && itens.length) {
      msg = 'Este Reel já tem um vídeo. Montar de novo troca esse vídeo pelo dos trechos.';
    }
    situacao.hidden = !msg || ocupado;
    situacao.textContent = msg;
    // confirmacao: lista exatamente o que o servidor disse que sera apagado
    confirmar.hidden = !confirmando || ocupado;
    if (confirmando) {
      confirmarTexto.textContent = 'O vídeo novo tem outra duração, então o que foi feito com o vídeo atual deixa de valer. Será apagado:';
      confirmarLista.replaceChildren(...confirmando.map((x) => el('li', {}, x)));
    }
    if (foco) {
      const f = foco;
      foco = null;
      let alvo = null;
      if (f.confirmar) alvo = confirmarSim;
      else if (f.montar) alvo = montar.disabled ? null : montar;
      else {
        const li = lista.querySelector(`[data-arquivo="${CSS.escape(f.arquivo)}"]`);
        alvo = li && (li.querySelector(`[data-acao="${f.acao}"]:not(:disabled)`)
          || li.querySelector('[data-acao]:not(:disabled)'));
      }
      if (alvo) alvo.focus();
    }
  }

  function carregar() {
    api('GET', `/api/projects/${encodeURIComponent(slug)}/clipes`).then((dados) => {
      listas.set(slug, dados);
    }).catch((e) => {
      if (ctx.slugAtual() === slug && !listas.has(slug)) aviso = e.mensagem;
    }).finally(() => {
      carregou = true;
      if (raiz.isConnected && ctx.slugAtual() === slug) pintar();
    });
  }

  const raiz = el('section', { id: 'painel-juntar', class: 'juntar' },
    el('p', { class: 'ajuda' },
      'Gravou em partes? Envie os trechos, deixe na ordem certa e o editor junta tudo num vídeo só. '
      + 'Trechos deitados ou quadrados ficam com faixas pretas, sem esticar a imagem.'),
    zona, caixaEnvio, avisos, erroGeral,
    el('div', { class: 'clipes-cabeca' }, titulo, total),
    lista, vazio, situacao, confirmar,
    el('div', { class: 'acoes' }, montar),
    quadro);

  repintar = () => {
    if (!raiz.isConnected) { repintar = null; return; }
    pintar();
  };
  pintar();
  carregar();
  return raiz;
}

// Passo 1, Video: criar/abrir um Reel e enviar o video bruto (XHR com progresso).
import { EDITOR_FECHADO, TOKEN, api, el, frase, icone, registrarPasso, relogio, tamanho, toast } from '../nucleo.js';

const EXTENSOES = ['.mp4', '.mov', '.m4v', '.webm', '.mkv'];
const FORMATOS = 'MP4, MOV, M4V, WEBM ou MKV';

// O envio continua se a pessoa trocar de passo; ao voltar, a tela mostra onde parou.
let envio = null; // {slug, xhr, enviado, total, conferindo}
let aviso = null; // {slug, tipo: 'erro'|'info', texto}
let telaAtual = null; // funcao que repinta a tela aberta (ou null)

function repintar() { if (telaAtual) telaAtual(); }

function extensao(nome) {
  const i = nome.lastIndexOf('.');
  return i >= 0 ? nome.slice(i).toLowerCase() : '';
}

function avisar(slug, tipo, texto) {
  aviso = { slug, tipo, texto };
  repintar();
}

function enviar(arquivo, ctx) {
  const slug = ctx.slug;
  if (envio) {
    toast('Já há um vídeo sendo enviado. Espere terminar ou cancele.', 'info');
    return;
  }
  aviso = null;
  const ext = extensao(arquivo.name);
  if (!EXTENSOES.includes(ext)) {
    return avisar(slug, 'erro', `Este tipo de arquivo não é aceito. Use um vídeo ${FORMATOS}.`);
  }
  if (arquivo.size === 0) return avisar(slug, 'erro', 'O arquivo está vazio. Escolha o vídeo de novo.');
  const limite = ctx.config && ctx.config.max_upload;
  if (limite && arquivo.size > limite) {
    return avisar(slug, 'erro', `O arquivo tem ${tamanho(arquivo.size)} e o limite do editor é ${tamanho(limite)}. `
      + 'Exporte o vídeo em tamanho menor e tente de novo.');
  }
  const xhr = new XMLHttpRequest();
  const nomeReel = (ctx.estado && ctx.estado.nome) || '';
  const tinhaVideo = !!(ctx.estado && ctx.estado.etapas.video === 'pronto');
  // o envio pode terminar com outro Reel aberto: entao so avisa, sem mexer na tela atual
  const outroAberto = () => ctx.slugAtual() !== slug;
  envio = { slug, xhr, enviado: 0, total: arquivo.size, conferindo: false };
  xhr.open('PUT', `/api/projects/${encodeURIComponent(slug)}/video`);
  xhr.setRequestHeader('X-Token', TOKEN);
  xhr.setRequestHeader('X-Filename', 'video' + ext);
  xhr.upload.onprogress = (e) => {
    if (!envio || envio.xhr !== xhr) return;
    envio.enviado = e.loaded;
    if (e.lengthComputable) envio.total = e.total;
    envio.conferindo = e.lengthComputable && e.loaded >= e.total;
    repintar();
  };
  xhr.upload.onload = () => {
    if (envio && envio.xhr === xhr) { envio.conferindo = true; repintar(); }
  };
  const terminar = () => { if (envio && envio.xhr === xhr) envio = null; };
  xhr.onload = () => {
    terminar();
    if (xhr.status === 200 && outroAberto()) {
      aviso = null;
      toast(`O vídeo do Reel "${nomeReel}" terminou de enviar.`, 'ok');
      return;
    }
    if (xhr.status !== 200 && outroAberto()) {
      toast(`O envio do vídeo do Reel "${nomeReel}" não deu certo. Abra esse Reel para ver o motivo.`, 'erro');
    }
    if (xhr.status === 200) {
      aviso = null;
      ctx.player.limpar();
      toast('Vídeo recebido.', 'ok');
      ctx.atualizar({ repintarPainel: true });
      return;
    }
    let msg = '';
    try { msg = JSON.parse(xhr.responseText).erro || ''; } catch { /* sem JSON */ }
    if (xhr.status === 413) {
      avisar(slug, 'erro', `O arquivo passa do limite do editor${limite ? ` (${tamanho(limite)})` : ''}. Exporte o vídeo em tamanho menor.`);
    } else if (xhr.status === 401) {
      avisar(slug, 'erro', 'A chave de acesso não vale mais. Feche esta aba e abra o editor de novo pelo ícone.');
    } else {
      avisar(slug, 'erro', `Não foi possível usar este arquivo: ${frase(msg || `erro ${xhr.status}`)}`);
    }
  };
  xhr.onerror = () => {
    terminar();
    avisar(slug, 'erro', `A conexão com o editor caiu durante o envio. ${EDITOR_FECHADO}`);
  };
  xhr.onabort = () => {
    terminar();
 avisar(slug, 'info', tinhaVideo
      ? 'Envio cancelado. O vídeo que já estava no Reel continua guardado.'
      : 'Envio cancelado. Nenhum vídeo foi guardado.');
  };
  xhr.send(arquivo);
  repintar();
}

// ------------------------------------------------------------- telas
function telaInicio(container, ctx) {
  const nome = el('input', { id: 'novo-nome', type: 'text', maxlength: '200', autocomplete: 'off',
    placeholder: 'Ex.: Prazo para recorrer', required: true });
  const erro = el('p', { id: 'novo-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
  const criar = el('button', { type: 'submit', id: 'novo-criar', class: 'botao botao-primario' }, 'Criar Reel');
  const form = el('form', { id: 'form-novo', class: 'formulario cartao', novalidate: true },
    el('label', { for: 'novo-nome' }, 'Nome do Reel'),
    el('div', { class: 'campo-linha' }, nome, criar),
    el('p', { class: 'ajuda' }, 'Só para você achar depois. Não aparece no vídeo.'),
    erro);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    erro.hidden = true;
    if (!nome.value.trim()) {
      erro.textContent = 'Dê um nome ao Reel para começar.';
      erro.hidden = false;
      nome.focus();
      return;
    }
    criar.disabled = true;
    try {
      const p = await api('POST', '/api/projects', { nome: nome.value });
      await ctx.abrirProjeto(p.slug, { passoInicial: 'video' });
    } catch (err) {
      erro.textContent = err.mensagem;
      erro.hidden = false;
      criar.disabled = false;
    }
  });

  const lista = el('div', { id: 'lista-projetos', class: 'projetos', 'aria-live': 'polite' },
    el('p', { class: 'suave' }, 'Carregando os Reels…'));
  container.append(
    el('p', { class: 'lead' }, 'Dê um nome ao Reel e, no próximo passo, envie o vídeo gravado na câmera.'),
    form,
    el('section', { class: 'secao', 'aria-labelledby': 'tit-anteriores' },
      el('h2', { id: 'tit-anteriores' }, 'Reels anteriores'), lista));
  api('GET', '/api/projects').then((projetos) => {
    if (!projetos.length) {
      lista.replaceChildren(el('div', { class: 'vazio' }, icone('pasta', 'icone-grande'),
        el('p', {}, 'Nenhum Reel ainda.'),
        el('p', { class: 'suave' }, 'Dê um nome acima para começar o primeiro.')));
      return;
    }
    lista.replaceChildren(...projetos.map((p) => el('button', {
      type: 'button', class: 'projeto', 'data-slug': p.slug,
      onclick: () => ctx.abrirProjeto(p.slug),
    },
    el('strong', { class: 'projeto-titulo' }, p.nome),
    el('span', { class: 'suave' }, dataCurta(p.criado)),
    el('span', { class: 'projeto-abrir' }, 'Abrir', icone('seta')))));
  }).catch((e) => {
    lista.replaceChildren(el('p', { class: 'mensagem-erro', role: 'alert' }, e.mensagem));
  });
}

function dataCurta(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return 'Criado em ' + d.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short', year: 'numeric' });
}

function descreverFormato(meta, nomeArquivo) {
  const ext = extensao(nomeArquivo || '').slice(1).toUpperCase();
  if (!meta || !meta.largura) return ext || '—';
  const { largura: w, altura: h } = meta;
  const orientacao = h > w ? 'Vertical' : h === w ? 'Quadrado' : 'Deitado';
  return `${orientacao} · ${w} × ${h}${ext ? ` · ${ext}` : ''}`;
}

function cartaoInfo(ctx) {
  const duracao = el('dd', { id: 'video-duracao' }, ctx.estado.duracao ? relogio(ctx.estado.duracao) : 'Lendo…');
  const formato = el('dd', { id: 'video-formato' }, 'Lendo…');
  const dica = el('p', { class: 'suave', hidden: true });
  ctx.player.metadados().then((m) => {
    if (m && Number.isFinite(m.duracao)) duracao.textContent = relogio(m.duracao);
    else if (!ctx.estado.duracao) duracao.textContent = 'Não deu para ler aqui';
    formato.textContent = descreverFormato(m, ctx.estado.arquivos.entrada);
    if (m && m.largura > m.altura) {
      dica.textContent = 'O Reel é vertical: um vídeo deitado vai aparecer com faixas em cima e embaixo.';
      dica.hidden = false;
    }
  });
  return el('div', { id: 'video-info', class: 'cartao info-video' },
    el('div', { class: 'info-topo' }, el('span', { class: 'bola-ok' }, icone('ok')),
      el('h2', {}, 'Vídeo recebido')),
    el('dl', {},
      el('div', {}, el('dt', {}, 'Duração'), duracao),
      el('div', {}, el('dt', {}, 'Formato'), formato)),
    dica,
    el('button', { type: 'button', class: 'botao botao-primario', onclick: () => ctx.ir('cortes') },
      'Ir para Cortes', icone('seta')));
}

function telaProjeto(container, ctx) {
  const temVideo = ctx.estado && ctx.estado.etapas.video === 'pronto';
  const entrada = el('input', { id: 'arquivo-video', type: 'file', class: 'sr-only',
    accept: 'video/*,' + EXTENSOES.join(',') });
  entrada.addEventListener('change', () => {
    const f = entrada.files && entrada.files[0];
    entrada.value = '';
    if (f) enviar(f, ctx);
  });
  const limite = ctx.config && ctx.config.max_upload;
  const zona = el('label', { class: 'soltar', for: 'arquivo-video' },
    icone('enviar', 'icone-grande'),
    el('strong', {}, temVideo ? 'Trocar o vídeo' : 'Arraste o vídeo para cá'),
    el('span', { class: 'suave' }, 'ou'),
    el('span', { class: 'botao botao-secundario falso-botao' }, 'Escolher arquivo'),
    el('span', { class: 'ajuda' }, `${FORMATOS}${limite ? ` · até ${tamanho(limite)}` : ''}`),
    entrada);
  zona.addEventListener('dragover', (e) => { e.preventDefault(); zona.classList.add('ativa'); });
  zona.addEventListener('dragleave', () => zona.classList.remove('ativa'));
  zona.addEventListener('drop', (e) => {
    e.preventDefault();
    zona.classList.remove('ativa');
    const f = e.dataTransfer && e.dataTransfer.files[0];
    if (f) enviar(f, ctx);
  });

  const barra = el('progress', { id: 'envio-barra', max: '100', value: '0' });
  const texto = el('p', { id: 'envio-texto' });
  const cancelar = el('button', { type: 'button', id: 'envio-cancelar', class: 'botao botao-secundario' }, 'Cancelar envio');
  cancelar.addEventListener('click', () => { if (envio) envio.xhr.abort(); });
  const caixaEnvio = el('div', { id: 'envio', class: 'cartao envio', hidden: true, 'aria-live': 'polite' },
    el('div', { class: 'envio-linha' }, texto, cancelar), barra);
  const erro = el('p', { id: 'video-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
  const info = el('p', { id: 'video-aviso', class: 'mensagem-info', hidden: true });

  container.append(
    el('p', { class: 'lead' }, 'Envie o vídeo do jeito que saiu da câmera. Pausas e erros de fala se resolvem no passo seguinte.'),
    temVideo ? cartaoInfo(ctx) : null,
    zona, caixaEnvio, erro, info);

  telaAtual = () => {
    if (!container.isConnected) { telaAtual = null; return; }
    const meu = envio && envio.slug === ctx.slug ? envio : null;
    caixaEnvio.hidden = !meu;
    zona.classList.toggle('desligada', !!meu);
    if (meu) {
      const pct = meu.total ? Math.min(100, Math.floor((meu.enviado / meu.total) * 100)) : 0;
      barra.value = pct;
      barra.setAttribute('aria-valuetext', `${pct}%`);
      texto.textContent = meu.conferindo ? 'Conferindo o vídeo… quase lá.'
        : `Enviando… ${pct}% (${tamanho(meu.enviado)} de ${tamanho(meu.total)})`;
      cancelar.hidden = meu.conferindo;
    }
    const meuAviso = aviso && aviso.slug === ctx.slug ? aviso : null;
    erro.hidden = !(meuAviso && meuAviso.tipo === 'erro');
    info.hidden = !(meuAviso && meuAviso.tipo === 'info');
    if (meuAviso) (meuAviso.tipo === 'erro' ? erro : info).textContent = meuAviso.texto;
  };
  telaAtual();
}

registrarPasso({
  id: 'video',
  render(container, ctx) {
    telaAtual = null;
    if (!ctx.slug || !ctx.estado) {
      container.closest('#painel').querySelector('h1').textContent = 'Comece um Reel';
      return telaInicio(container, ctx);
    }
    return telaProjeto(container, ctx);
  },
});

// Passo 5, Preview: monta uma versao leve (saida/preview.mp4) para assistir e anotar.
// As notas guardam o instante do video ORIGINAL (como na pagina de revisao); a tela
// mostra o instante no preview (cortado) com originalToCutTime.
import { api, el, icone, registrarPasso } from '../nucleo.js';
import { traduzir } from '../mensagens.js';
import { iniciarTarefa, quadroTarefa, versaoDe } from '../tarefa.js';
import { cutToOriginalTime, originalToCutTime, tempoFino } from '../tempo.js';

const arredondar = (t) => Math.round(t * 1000) / 1000;

function secaoNotas(ctx) {
  const lista = el('ul', { id: 'lista-notas', class: 'notas' });
  const vazio = el('p', { id: 'notas-vazio', class: 'suave' }, 'Nenhuma nota ainda.');
  const erro = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
  const adicionar = el('button', { type: 'button', id: 'nota-adicionar', class: 'botao botao-secundario', disabled: true },
    icone('mais'), el('span', {}, 'Anotar neste ponto'));
  const secao = el('section', { class: 'secao', 'aria-labelledby': 'tit-notas' },
    el('div', { class: 'secao-topo' }, el('h2', { id: 'tit-notas' }, 'Notas'), adicionar),
    el('p', { class: 'ajuda' }, 'Pause o vídeo onde quer mudar algo e anote. A nota guarda o ponto do vídeo.'),
    erro, vazio, lista);
  let notas = [];
  let ativos = [];
  let chave = 0;

  async function salvar() {
    erro.hidden = true;
    try {
      const rev = await api('PUT', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`,
        { notes: notas.filter((n) => n.text.trim()).map((n) => ({ t: n.t, text: n.text.trim() })) });
      ativos = rev.cuts.filter((c) => c.active);
    } catch (e) {
      erro.textContent = e.status === 409 ? 'Espere o trabalho em andamento terminar e tente de novo.' : traduzir(e.mensagem);
      erro.hidden = false;
    }
  }

  function pintar(focar) {
    const ordenadas = notas.slice().sort((a, b) => a.t - b.t);
    lista.replaceChildren(...ordenadas.map((n) => {
      const noPreview = originalToCutTime(n.t, ativos);
      const texto = el('textarea', { class: 'nota-texto', rows: '2', maxlength: '2000',
        'aria-label': `Nota em ${tempoFino(noPreview)}` });
      texto.value = n.text;
      texto.addEventListener('input', () => { n.text = texto.value; });
      texto.addEventListener('change', salvar);
      const apagar = el('button', { type: 'button', class: 'botao botao-secundario nota-apagar', 'aria-label': 'Apagar nota',
        onclick: () => { notas = notas.filter((x) => x !== n); pintar(); salvar(); } }, icone('lixo'));
      const tempo = el('button', { type: 'button', class: 'botao botao-secundario botao-pequeno nota-tempo',
        'aria-label': `Ir para ${tempoFino(noPreview)} no preview`, onclick: () => ctx.player.irPara(noPreview) },
      tempoFino(noPreview));
      if (focar === n) queueMicrotask(() => texto.focus());
      return el('li', { class: 'nota' }, tempo, texto, apagar);
    }));
    vazio.hidden = notas.length > 0;
  }

  adicionar.addEventListener('click', () => {
    const n = { t: arredondar(cutToOriginalTime(ctx.player.agora(), ativos)), text: '', chave: chave++ };
    ctx.player.video.pause();
    notas.push(n);
    pintar(n);
  });

  api('GET', `/api/projects/${encodeURIComponent(ctx.slug)}/revisao`).then((rev) => {
    if (!lista.isConnected) return;
    ativos = rev.cuts.filter((c) => c.active);
    notas = (rev.notes || []).map((n) => ({ t: n.t, text: n.text, chave: chave++ }));
    adicionar.disabled = false;
    pintar();
  }).catch((e) => {
    erro.textContent = traduzir(e.mensagem);
    erro.hidden = false;
  });
  return secao;
}

registrarPasso({
  id: 'preview',
  pronto: (estado) => estado.etapas.preview === 'pronto' && (!estado.preview_desatualizado || estado.preview_so_graficos === true),
  tarefas: ['preview'],
  video: (estado, slug) => (estado.arquivos.preview
    ? { rel: estado.arquivos.preview, rotulo: 'Preview', versao: versaoDe(slug, 'preview') } : null),
  render(container, ctx) {
    const tem = ctx.estado.etapas.preview === 'pronto';
    const velho = tem && ctx.estado.preview_desatualizado === true;
    const erro = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
    const gerar = el('button', { type: 'button', id: 'preview-gerar', class: `botao ${tem && !velho ? 'botao-secundario' : 'botao-primario'}` },
      icone('atualizar'), el('span', {}, tem ? 'Gerar de novo' : 'Gerar preview'));
    gerar.addEventListener('click', async () => {
      gerar.disabled = true;
      erro.hidden = true;
      try {
        await iniciarTarefa(ctx.slug, 'preview');
      } catch (e) {
        erro.textContent = traduzir(e.mensagem);
        erro.hidden = false;
      } finally {
        gerar.disabled = false;
      }
    });
    const acoes = tem
      ? el('div', { id: 'preview-pronto', class: 'cartao pronto-cartao' },
        el('div', { class: 'info-topo' }, el('span', { class: velho ? 'bola-ok bola-aviso' : 'bola-ok' }, icone(velho ? 'atualizar' : 'ok')), el('h2', {}, velho ? 'Preview antigo' : 'Preview pronto')),
        el('p', {}, 'Assista no player. Se algo não estiver bom, volte aos Cortes ou às Legendas e gere de novo.'),
        el('div', { class: 'acoes' }, gerar,
          velho ? null : el('button', { type: 'button', class: 'botao botao-primario', onclick: () => ctx.ir('final') },
            'Ir para Final', icone('seta'))))
      : el('div', { class: 'cartao comecar' },
        el('h2', {}, 'Monte uma prévia'),
        el('p', {}, 'Uma versão menor e mais leve do Reel, com os cortes e as legendas, para você assistir antes da versão final.'),
        gerar,
        el('p', { class: 'ajuda' }, 'Leva menos de um minuto na maioria dos vídeos.'));
    const quadro = quadroTarefa(ctx.slug, ['preview'], { aoMudar: (ocupado) => { acoes.hidden = ocupado; } });
    container.append(...[
      el('p', { class: 'lead' }, 'Veja como o Reel está ficando antes de gerar o arquivo final.'),
      velho ? el('p', { id: 'aviso-desatualizado', class: 'mensagem-aviso', role: 'status' },
        'Você mudou os cortes, as legendas ou os cards depois de gerar este vídeo. Ele não tem as mudanças: gere de novo.') : null,
      quadro, erro, acoes, tem ? secaoNotas(ctx) : null].filter(Boolean));
  },
});

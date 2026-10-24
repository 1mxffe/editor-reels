// Passo 8, Final: monta saida/final.mp4 (1080x1920), mostra no player, abre a pasta
// do Reel no computador e lista os arquivos prontos para baixar.
import { api, el, icone, registrarPasso, toast, urlArquivo } from '../nucleo.js';
import { traduzir } from '../mensagens.js';
import { iniciarTarefa, quadroTarefa, versaoDe } from '../tarefa.js';

const ARQUIVOS = [
  { chave: 'final', nome: 'Versão final', desc: 'Vídeo vertical 1080 × 1920, pronto para o Instagram', baixar: 'reel-final.mp4' },
  { chave: 'preview', nome: 'Preview', desc: 'Versão leve, só para conferir', baixar: 'reel-preview.mp4' },
  { chave: 'capa', nome: 'Capa', desc: 'Imagem 1080 × 1920', baixar: 'reel-capa.png' },
];

function listaArquivos(ctx) {
  const arq = ctx.estado.arquivos;
  const itens = ARQUIVOS.filter((a) => arq[a.chave]).map((a) => el('li', { class: 'arquivo' },
    el('div', { class: 'arquivo-info' }, el('strong', {}, a.nome), el('span', { class: 'suave' }, a.desc)),
    el('a', {
      class: 'botao botao-secundario', href: urlArquivo(ctx.slug, arq[a.chave], versaoDe(ctx.slug, a.chave)),
      download: a.baixar, 'aria-label': `Baixar: ${a.nome}`,
    }, icone('baixar'), el('span', {}, 'Baixar'))));
  return el('section', { class: 'secao', 'aria-labelledby': 'tit-arquivos' },
    el('h2', { id: 'tit-arquivos' }, 'Arquivos prontos'),
    el('ul', { id: 'final-arquivos', class: 'arquivos' }, itens));
}

registrarPasso({
  id: 'final',
  pronto: (estado) => estado.etapas.final === 'pronto' && !estado.final_desatualizado,
  tarefas: ['final'],
  video: (estado, slug) => {
    if (estado.arquivos.final) return { rel: estado.arquivos.final, rotulo: 'Versão final', versao: versaoDe(slug, 'final') };
    if (estado.arquivos.preview) return { rel: estado.arquivos.preview, rotulo: 'Preview', versao: versaoDe(slug, 'preview') };
    return null;
  },
  render(container, ctx) {
    const tem = ctx.estado.etapas.final === 'pronto';
    const velho = tem && ctx.estado.final_desatualizado === true;
    const erro = el('p', { class: 'mensagem-erro', role: 'alert', hidden: true });
    const gerar = el('button', { type: 'button', id: 'final-gerar', class: `botao ${tem && !velho ? 'botao-secundario' : 'botao-primario'}` },
      icone('atualizar'), el('span', {}, tem ? 'Gerar de novo' : 'Gerar versão final'));
    gerar.addEventListener('click', async () => {
      gerar.disabled = true;
      erro.hidden = true;
      try {
        await iniciarTarefa(ctx.slug, 'final');
      } catch (e) {
        erro.textContent = traduzir(e.mensagem);
        erro.hidden = false;
      } finally {
        gerar.disabled = false;
      }
    });
    const abrir = el('button', { type: 'button', id: 'final-abrir-pasta', class: 'botao botao-primario' },
      icone('pasta'), el('span', {}, 'Abrir pasta'));
    abrir.addEventListener('click', async () => {
      abrir.disabled = true;
      try {
        await api('POST', `/api/projects/${encodeURIComponent(ctx.slug)}/abrir-pasta`, {});
        toast('Pedi ao computador para abrir a pasta do Reel.', 'ok');
      } catch (e) {
        toast(traduzir(e.mensagem), 'erro');
      } finally {
        abrir.disabled = false;
      }
    });
    const acoes = tem
      ? el('div', { id: 'final-pronto', class: 'cartao pronto-cartao' },
        el('div', { class: 'info-topo' }, el('span', { class: velho ? 'bola-ok bola-aviso' : 'bola-ok' }, icone(velho ? 'atualizar' : 'ok')), el('h2', {}, velho ? 'Versão final antiga' : 'Reel pronto')),
        el('p', {}, 'O arquivo final está na pasta do Reel. Abra a pasta para enviar ao celular ou publicar.'),
        el('div', { class: 'acoes' }, ...(velho ? [gerar, abrir] : [abrir, gerar])))
      : el('div', { class: 'cartao comecar' },
        el('h2', {}, 'Gere o Reel pronto'),
        el('p', {}, 'Monta o vídeo no tamanho do Instagram (1080 × 1920), com os cortes e as legendas, em qualidade alta.'),
        gerar,
        el('p', { class: 'ajuda' }, 'Demora um pouco mais que o preview.'));
    const quadro = quadroTarefa(ctx.slug, ['final'], { aoMudar: (ocupado) => { acoes.hidden = ocupado; } });
    const temArquivos = ARQUIVOS.some((a) => ctx.estado.arquivos[a.chave]);
    container.append(...[
      el('p', { class: 'lead' }, 'Último passo: o Reel no tamanho certo, pronto para publicar.'),
      velho ? el('p', { id: 'aviso-desatualizado', class: 'mensagem-aviso', role: 'status' },
        'Você mudou os cortes, as legendas ou os cards depois de gerar este vídeo. Ele não tem as mudanças: gere de novo.') : null,
      quadro, erro, acoes, temArquivos ? listaArquivos(ctx) : null].filter(Boolean));
  },
});

// Tela de Instalacao: o que o computador tem (GET /api/doctor), o comando para
// colar no Terminal, o botao de instalar o navegador de graficos e o @ do escritorio.
import { api, el, frase, icone, registrarPasso, toast } from '../nucleo.js';

// Nomes em portugues simples por id (o servidor manda o nome tecnico).
const NOMES = {
  python: 'Programa base do editor',
  ffmpeg: 'Montagem do vídeo',
  ffprobe: 'Leitura do vídeo',
  node: 'Desenho dos cards e da capa',
  disco: 'Espaço livre no disco',
  whisper: 'Texto do vídeo automático',
  pillow: 'Imagens da capa',
  graficos: 'Navegador de gráficos',
};

const RESUMOS = {
  READY: ['tudo', 'Tudo pronto. O computador tem o que o editor precisa.'],
  'READY WITH LIMITS': ['limites', 'Pronto para usar. Alguns recursos extras ainda faltam.'],
};

async function copiar(texto, botao) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(texto);
    ok = true;
  } catch {
    const area = el('textarea', { class: 'sr-only', readonly: true });
    area.value = texto;
    document.body.append(area);
    area.select();
    try { ok = document.execCommand('copy'); } catch { ok = false; }
    area.remove();
  }
  if (ok) {
    botao.lastChild.textContent = 'Copiado';
    setTimeout(() => { botao.lastChild.textContent = 'Copiar'; }, 2000);
  } else {
    toast('Não deu para copiar sozinho. Selecione o comando e use Cmd+C.', 'erro');
  }
}

function linhaItem(it, ctx, recarregar) {
  const status = it.ok ? 'Instalado' : it.opcional ? 'Opcional, ainda não instalado' : 'Falta instalar';
  const conteudo = el('div', { class: 'item-conteudo' },
    el('div', { class: 'item-titulo' },
      el('strong', {}, NOMES[it.id] || it.nome),
      el('span', { class: 'item-status' }, status)),
    it.ok ? null : el('p', { class: 'item-mensagem' }, frase(it.mensagem)));
  if (!it.ok && it.comando) {
    const botao = el('button', { type: 'button', class: 'botao botao-secundario copiar',
      'aria-label': `Copiar o comando: ${it.comando}` }, icone('copiar'), el('span', {}, 'Copiar'));
    botao.addEventListener('click', () => copiar(it.comando, botao));
    conteudo.append(el('div', { class: 'item-comando' },
      el('p', { class: 'suave' }, 'Para instalar, abra o app Terminal, cole o comando abaixo e aperte Enter:'),
      el('div', { class: 'comando-linha' }, el('code', {}, it.comando), botao)));
  }
  if (!it.ok && it.id === 'graficos' && ctx.slug) {
    conteudo.append(botaoChromium(ctx, recarregar));
  }
  return el('li', { class: 'item', 'data-id': it.id, 'data-ok': String(it.ok) },
    el('span', { class: `item-marca ${it.ok ? 'sim' : it.opcional ? 'opcional' : 'nao'}`, 'aria-hidden': 'true' },
      it.ok ? '✓' : '✗'),
    conteudo);
}

function botaoChromium(ctx, recarregar) {
  const aviso = el('p', { class: 'suave', 'aria-live': 'polite' });
  const botao = el('button', { type: 'button', id: 'instalar-chromium', class: 'botao botao-primario' },
    'Instalar o navegador de gráficos');
  botao.addEventListener('click', async () => {
    botao.disabled = true;
    aviso.textContent = 'Instalando… isso pode levar alguns minutos. Pode deixar esta janela aberta.';
    try {
      const { job_id: id } = await api('POST', `/api/projects/${encodeURIComponent(ctx.slug)}/jobs/instalar-chromium`, {});
      for (;;) {
        await new Promise((r) => setTimeout(r, 1500));
        const job = await api('GET', `/api/jobs/${encodeURIComponent(id)}`);
        if (job.estado === 'rodando') continue;
        if (job.estado === 'ok') {
          toast('Navegador de gráficos instalado.', 'ok');
          recarregar();
        } else {
          aviso.textContent = job.mensagem ? `Não deu certo: ${frase(job.mensagem)}` : 'A instalação foi interrompida.';
          botao.disabled = false;
        }
        return;
      }
    } catch (e) {
      aviso.textContent = e.mensagem || 'Não foi possível começar a instalação.';
      botao.disabled = false;
    }
  });
  return el('div', { class: 'item-acao' }, botao, aviso);
}

function secaoProgramas(ctx) {
  const resumo = el('p', { id: 'instalacao-resumo', class: 'resumo' }, 'Conferindo o computador…');
  const lista = el('ul', { id: 'lista-itens', class: 'itens' });
  const conferir = el('button', { type: 'button', class: 'botao botao-secundario' }, icone('atualizar'), el('span', {}, 'Conferir de novo'));
  const secao = el('section', { class: 'secao', 'aria-labelledby': 'tit-programas' },
    el('div', { class: 'secao-topo' }, el('h2', { id: 'tit-programas' }, 'Programas no computador'), conferir),
    resumo, lista);

  async function carregar() {
    conferir.disabled = true;
    resumo.className = 'resumo';
    resumo.textContent = 'Conferindo o computador…';
    try {
      const d = await api('GET', '/api/doctor');
      const [tipo, texto] = RESUMOS[d.estado_codigo] || ['falta', 'Faltam itens obrigatórios. Instale os marcados com ✗ para usar o editor.'];
      resumo.className = `resumo resumo-${tipo}`;
      resumo.textContent = texto;
      lista.replaceChildren(...d.itens.map((it) => linhaItem(it, ctx, carregar)));
    } catch (e) {
      resumo.className = 'resumo resumo-falta';
      resumo.textContent = e.mensagem;
    } finally {
      conferir.disabled = false;
    }
  }
  conferir.addEventListener('click', carregar);
  carregar();
  return secao;
}

function secaoHandle(ctx) {
  const secao = el('section', { class: 'secao', 'aria-labelledby': 'tit-handle' });

  function pintar(editando, salvoAgora = false) {
    const brand = ctx.brand || { handles: [], completa: false };
    const topo = [el('h2', { id: 'tit-handle' }, '@ do escritório nas redes'),
      el('p', { class: 'suave' }, 'Aparece na capa de todos os Reels. Pode ter até 2, separados por vírgula.')];
    if (brand.completa && !editando) {
      const trocar = el('button', { type: 'button', class: 'botao botao-secundario', onclick: () => pintar(true) }, 'Trocar o @');
      secao.replaceChildren(...topo, el('div', { class: 'cartao handle-salvo' },
        el('p', { id: 'handle-salvo' }, salvoAgora ? `Salvo. A capa vai usar ${brand.handles.join(' e ')}.`
          : `A capa usa ${brand.handles.join(' e ')}.`),
        trocar));
      return;
    }
    const campo = el('input', { id: 'handle-campo', type: 'text', autocomplete: 'off', spellcheck: 'false',
      placeholder: '@gutmannesilva', 'aria-describedby': 'handle-ajuda handle-erro' });
    campo.value = (brand.handles || []).join(', ');
    const erro = el('p', { id: 'handle-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
    const salvar = el('button', { type: 'submit', id: 'handle-salvar', class: 'botao botao-primario' }, 'Salvar');
    const form = el('form', { id: 'form-handle', class: 'formulario', novalidate: true },
      el('label', { for: 'handle-campo' }, '@ do Instagram'),
      el('div', { class: 'campo-linha' }, campo, salvar),
      el('p', { id: 'handle-ajuda', class: 'ajuda' }, 'Só letras sem acento, números, ponto e sublinhado.'),
      erro);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const handles = campo.value.split(/[,;\s]+/).map((h) => h.trim()).filter(Boolean);
      erro.hidden = true;
      if (!handles.length) {
        erro.textContent = 'Escreva o @ do escritório, por exemplo @gutmannesilva.';
        erro.hidden = false;
        campo.focus();
        return;
      }
      salvar.disabled = true;
      try {
        ctx.brand = await api('PUT', '/api/brand', { handles });
        pintar(false, true);
        toast('@ salvo.', 'ok');
      } catch (err) {
        erro.textContent = err.mensagem;
        erro.hidden = false;
        salvar.disabled = false;
        campo.focus();
      }
    });
    secao.replaceChildren(...topo, form);
  }
  pintar(false);
  return secao;
}

registrarPasso({
  id: 'instalacao',
  titulo: 'Instalação',
  render(container, ctx) {
    container.append(
      el('p', { class: 'lead' }, 'Confira se o computador tem tudo o que o editor usa. Os itens opcionais só liberam recursos extras; dá para começar sem eles.'),
      secaoProgramas(ctx),
      secaoHandle(ctx),
      el('div', { class: 'acoes' },
        el('button', { type: 'button', class: 'botao botao-primario', onclick: () => ctx.ir('video') },
          ctx.slug ? 'Voltar ao Reel' : 'Começar um Reel', icone('seta'))));
  },
});

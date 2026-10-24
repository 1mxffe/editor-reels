// Passo 7, Capa (opcional): 3 quadros nítidos do vídeo (ou uma foto dos materiais),
// a pessoa escolhe o melhor (o editor NÃO reconhece sorriso nem rosto), escreve
// gancho/área/subtítulo e gera capa/capa.png (1080 x 1920) com a marca do escritório.
import { api, el, icone, registrarPasso, urlArquivo } from '../nucleo.js';
import { traduzir } from '../mensagens.js';
import { iniciarTarefa, quadroTarefa, rodando, versaoDe } from '../tarefa.js';

const GANCHO_MAX = 28;
const AREA_MAX = 28;
const SUB_MAX = 90;
const escolhas = new Map(); // slug -> {quadro, gancho, area, subtitulo}: sobrevive à troca de passo

function memoria(slug) {
  if (!escolhas.has(slug)) escolhas.set(slug, { quadro: null, gancho: '', area: '', subtitulo: '' });
  return escolhas.get(slug);
}

function nomeQuadro(rel) {
  const m = rel.match(/candidato-(\d+)\.png$/);
  return m ? `Quadro ${m[1]}` : 'Foto enviada';
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

registrarPasso({
  id: 'capa',
  tarefas: ['capa-candidatos', 'capa'],
  render(container, ctx) {
    const slug = ctx.slug;
    const estado = ctx.estado;
    const mem = memoria(slug);
    const candidatos = Array.isArray(estado.capa_candidatos) ? estado.capa_candidatos : [];
    if (mem.quadro && !candidatos.includes(mem.quadro)) mem.quadro = null;
    const semArroba = !(ctx.brand && ctx.brand.completa);
    const temVideo = estado.etapas.video === 'pronto';
    const versaoQuadros = versaoDe(slug, 'capa-candidatos');

    // --------------------------------------------------------- aviso do @
    const avisoArroba = semArroba ? el('div', { id: 'capa-sem-arroba', class: 'mensagem-aviso aviso-com-botao', role: 'status' },
      el('p', {}, 'Falta salvar o @ do escritório. A capa mostra o @ e só pode ser gerada depois que ele estiver salvo.'),
      el('button', { type: 'button', id: 'capa-ir-instalacao', class: 'botao botao-secundario', onclick: () => ctx.ir('instalacao') },
        'Abrir a Instalação', icone('seta'))) : null;

    // ------------------------------------------------------------ quadros
    const erroQuadros = el('p', { id: 'capa-erro-quadros', class: 'mensagem-erro', role: 'alert', hidden: true });
    const achar = el('button', { type: 'button', id: 'capa-achar', class: `botao ${candidatos.length ? 'botao-secundario' : 'botao-primario'}`, disabled: !temVideo },
      icone('video'), el('span', {}, candidatos.length ? 'Achar quadros de novo' : 'Achar quadros do vídeo'));
    achar.addEventListener('click', async () => {
      achar.disabled = true;
      erroQuadros.hidden = true;
      try {
        await iniciarTarefa(slug, 'capa-candidatos', { modo: 'video' });
      } catch (e) {
        erroQuadros.textContent = traduzir(e.mensagem);
        erroQuadros.hidden = false;
      } finally {
        achar.disabled = false;
      }
    });
    const fotos = el('select', { id: 'capa-foto', 'aria-label': 'Foto dos materiais' }, el('option', { value: '' }, 'Carregando fotos…'));
    const usarFoto = el('button', { type: 'button', id: 'capa-usar-foto', class: 'botao botao-secundario', disabled: true },
      icone('imagem'), el('span', {}, 'Usar esta foto'));
    const blocoFoto = el('div', { class: 'capa-foto' },
      el('p', { class: 'ajuda' }, 'Prefere uma foto? Envie na aba Materiais do passo Gráficos e escolha aqui.'),
      el('div', { class: 'campo-linha' }, fotos, usarFoto));
    api('GET', `/api/projects/${encodeURIComponent(slug)}/materiais`).then((r) => {
      const imagens = r.materiais.filter((m) => m.tipo === 'imagem' && !/\.svg$/i.test(m.nome));
      fotos.replaceChildren(...(imagens.length
        ? imagens.map((m) => el('option', { value: m.rel }, m.nome))
        : [el('option', { value: '' }, 'Nenhuma foto nos materiais')]));
      fotos.disabled = imagens.length === 0;
      usarFoto.disabled = imagens.length === 0;
    }).catch(() => { fotos.replaceChildren(el('option', { value: '' }, 'Não deu para listar as fotos')); });
    usarFoto.addEventListener('click', async () => {
      if (!fotos.value) return;
      usarFoto.disabled = true;
      erroQuadros.hidden = true;
      try {
        await iniciarTarefa(slug, 'capa-candidatos', { modo: 'foto', foto: fotos.value });
        mem.quadro = 'capa/foto.png';
      } catch (e) {
        erroQuadros.textContent = traduzir(e.mensagem);
        erroQuadros.hidden = false;
      } finally {
        usarFoto.disabled = false;
      }
    });

    const grade = el('ul', { id: 'capa-candidatos', class: 'candidatos' });
    function pintarGrade() {
      grade.replaceChildren(...candidatos.map((rel) => {
        const sel = mem.quadro === rel;
        const nome = nomeQuadro(rel);
        return el('li', { class: 'candidato', 'data-rel': rel, 'data-escolhido': String(sel) },
          el('img', { src: urlArquivo(slug, rel, versaoQuadros), alt: nome }),
          el('button', {
            type: 'button', class: `botao ${sel ? 'botao-primario' : 'botao-secundario'} candidato-escolher`,
            'aria-pressed': String(sel), 'aria-label': `Escolher este quadro: ${nome}`,
            onclick: () => { mem.quadro = rel; pintarGrade(); pintarGerar(); },
          }, sel ? icone('ok') : null, el('span', {}, sel ? 'Escolhido' : 'Escolher este quadro')));
      }));
    }
    pintarGrade();

    const secaoQuadros = el('section', { class: 'secao', 'aria-labelledby': 'tit-quadros' },
      el('h2', { id: 'tit-quadros' }, '1. Escolha o quadro'),
      el('p', { id: 'capa-sem-sorriso', class: 'mensagem-info' },
        'O editor não reconhece sorriso nem rosto. Ele separa 3 quadros nítidos, de partes diferentes do vídeo, e ',
        el('strong', {}, 'você escolhe'), ' o que ficou melhor.'),
      temVideo ? null : el('p', { class: 'ajuda' }, 'Envie o vídeo primeiro para achar os quadros.'),
      el('div', { class: 'acoes' }, achar), erroQuadros, grade, blocoFoto);

    // -------------------------------------------------------------- textos
    const gancho = el('input', { id: 'capa-gancho', type: 'text', maxlength: String(GANCHO_MAX), autocomplete: 'off', placeholder: 'Ex.: 3 MITOS' });
    gancho.value = mem.gancho;
    const area = el('input', { id: 'capa-area', type: 'text', maxlength: String(AREA_MAX), autocomplete: 'off', placeholder: 'Ex.: ISENÇÃO DE IR' });
    area.value = mem.area;
    const subtitulo = el('textarea', { id: 'capa-subtitulo', rows: '2', maxlength: String(SUB_MAX), placeholder: 'Ex.: sobre a aposentadoria' });
    subtitulo.value = mem.subtitulo;
    for (const [campo, chave] of [[gancho, 'gancho'], [area, 'area'], [subtitulo, 'subtitulo']]) {
      campo.addEventListener('input', () => { mem[chave] = campo.value; pintarGerar(); });
    }
    const campo = (rotulo, id, controle, ajuda) => el('div', { class: 'campo' },
      el('label', { for: id }, rotulo), controle, ajuda);

    const erroGerar = el('p', { id: 'capa-erro', class: 'mensagem-erro', role: 'alert', hidden: true });
    const gerar = el('button', { type: 'button', id: 'capa-gerar', class: 'botao botao-primario' },
      icone('atualizar'), el('span', {}, estado.arquivos.capa ? 'Gerar capa de novo' : 'Gerar capa'));
    const falta = el('p', { id: 'capa-falta', class: 'ajuda' });
    function pintarGerar() {
      const motivos = [];
      if (semArroba) motivos.push('salve o @ na Instalação');
      if (!mem.quadro) motivos.push('escolha um quadro');
      if (!mem.gancho.trim()) motivos.push('escreva o gancho');
      gerar.disabled = motivos.length > 0 || rodando(slug, ['capa', 'capa-candidatos']);
      falta.textContent = motivos.length ? `Para gerar: ${motivos.join(', ')}.` : '';
      falta.hidden = motivos.length === 0;
    }
    gerar.addEventListener('click', async () => {
      gerar.disabled = true;
      erroGerar.hidden = true;
      const corpo = { quadro: mem.quadro, gancho: mem.gancho.trim() };
      if (mem.area.trim()) corpo.area = mem.area.trim();
      if (mem.subtitulo.trim()) corpo.subtitulo = mem.subtitulo.trim();
      try {
        await iniciarTarefa(slug, 'capa', corpo);
      } catch (e) {
        erroGerar.textContent = e.codigo === 'marca_incompleta'
          ? 'Falta salvar o @ do escritório. Abra a Instalação e salve o @ antes de gerar a capa.'
          : traduzir(e.mensagem);
        erroGerar.hidden = false;
      } finally {
        pintarGerar();
      }
    });
    pintarGerar();

    const secaoTextos = el('section', { class: 'secao', 'aria-labelledby': 'tit-textos' },
      el('h2', { id: 'tit-textos' }, '2. Textos da capa'),
      el('div', { class: 'formulario' },
        campo('Gancho', 'capa-gancho', gancho, el('span', { class: 'ajuda' }, `Curto e forte, até ${GANCHO_MAX} letras. `, contador(gancho, GANCHO_MAX))),
        campo('Área (opcional)', 'capa-area', area, el('span', { class: 'ajuda' }, 'Aparece numa etiqueta acima do gancho.')),
        campo('Subtítulo (opcional)', 'capa-subtitulo', subtitulo, contador(subtitulo, SUB_MAX))),
      erroGerar, falta, el('div', { class: 'acoes' }, gerar));

    // --------------------------------------------------------------- pronta
    const versao = versaoDe(slug, 'capa');
    const pronta = estado.arquivos.capa
      ? el('figure', { id: 'capa-pronta', class: 'capa-pronta' },
        el('img', { src: urlArquivo(slug, estado.arquivos.capa, versao), alt: 'Capa pronta do Reel' }),
        el('figcaption', {},
          el('span', { class: 'suave' }, 'Capa pronta · 1080 × 1920'),
          el('a', { id: 'capa-baixar', class: 'botao botao-secundario', href: urlArquivo(slug, estado.arquivos.capa, versao),
            download: 'reel-capa.png' }, icone('baixar'), el('span', {}, 'Baixar capa'))))
      : el('div', { id: 'capa-pronta-vazia', class: 'capa-pronta capa-pronta-vazia', 'aria-hidden': 'true' },
        icone('imagem', 'icone-grande'), el('span', {}, 'A capa aparece aqui.'));

    const quadro = quadroTarefa(slug, ['capa-candidatos', 'capa'], {
      aoMudar: (ocupado) => { achar.disabled = ocupado || !temVideo; pintarGerar(); },
    });
    container.append(...[
      el('p', { class: 'lead' }, 'A imagem que aparece no perfil antes de alguém tocar no Reel. É opcional.'),
      avisoArroba, quadro,
      el('div', { class: 'capa-grade' },
        el('div', { class: 'capa-passos' }, secaoQuadros, secaoTextos),
        pronta),
    ].filter(Boolean));
  },
});

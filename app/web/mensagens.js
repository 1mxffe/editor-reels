// Traduz mensagens tecnicas do servidor/scripts para portugues simples (sem DOM,
// testavel no node). review_apply.py e os scripts mantem a redacao deles (tambem
// alimentam a review.html e a linha de comando); a traducao acontece so aqui.

export const GENERICA = 'Algo deu errado. Tente de novo; se continuar, veja os detalhes.';

// "graficos.json, card 2 ('g3'): ..." -> "No card 3, " (numerado a partir de 1)
function noCard(t) {
  const m = String(t).match(/card (\d+)\b/i);
  return m ? `No card ${Number(m[1]) + 1}, ` : '';
}
const minuscula = (s) => s[0].toLowerCase() + s.slice(1);
const doCard = (t, texto) => (noCard(t) ? noCard(t) + minuscula(texto) : texto);

const REGRAS = [
  // ---- gráficos (scripts/graphics.py validar e a rota de gráficos)
  [/t[ií]tulo obrigat[oó]rio/i, (m, t) => doCard(t, 'Escreva o título do card.')],
  [/t[ií]tulo com (\d+) caracteres \(m[aá]ximo (\d+)\)/i,
    (m, t) => doCard(t, `O título pode ter até ${m[2]} letras (está com ${m[1]}).`)],
  [/corpo com (\d+) caracteres \(m[aá]ximo (\d+)\)/i,
    (m, t) => doCard(t, `O texto pode ter até ${m[2]} letras (está com ${m[1]}).`)],
  [/\bat deve ser/i, (m, t) => doCard(t, 'O momento precisa ser um número de segundos (0 ou mais).')],
  [/\bdur deve ser/i, (m, t) => doCard(t, 'A duração precisa ficar entre 1 e 6 segundos.')],
  [/id repetido|id obrigat[oó]rio|chaves desconhecidas/i,
    () => 'Os cards ficaram fora de ordem. Recarregue a página e tente de novo.'],
  [/precisa ser um dos materiais|material (n[aã]o encontrado|fora|precisa|maior|ileg)|n[aã]o [eé] uma imagem .* v[aá]lida/i,
    (m, t) => doCard(t, 'A imagem escolhida não pode ser usada. Escolha outra dos materiais.')],
  [/confer[eê]ncia dos gr[aá]ficos demorou/i, () => 'Demorou demais para conferir os cards. Tente de novo.'],
  // ---- materiais
  [/tipo de arquivo n[aã]o aceito/i, () => 'Esse tipo de arquivo não serve. Envie PNG, JPG, WEBP, SVG ou MP4.'],
  [/conte[uú]do n[aã]o [eé] um arquivo/i, () => 'Esse arquivo não é o que o nome diz. Envie de novo em outro formato.'],
  [/grande demais \(m[aá]ximo (\d+) MB\)/i, (m) => `Arquivo grande demais: o limite é ${m[1]} MB.`],
  [/material n[aã]o existe/i, () => 'Esse material já tinha sido apagado.'],
  // ---- capa (scripts/cover_frames.py, cover_compose.py e as opções da capa)
  [/salve o @|handles vazio|informe o @/i,
    () => 'Falta salvar o @ do escritório. Abra a Instalação e salve o @ antes de gerar a capa.'],
  [/gancho n[aã]o cabe em 2 linhas/i, () => 'O gancho não cabe em 2 linhas na capa. Encurte o texto.'],
  [/gancho com mais de 2 linhas/i, () => 'O gancho pode ter no máximo 2 linhas.'],
  [/gancho com (\d+) caracteres \(m[aá]ximo (\d+)\)/i,
    (m) => `O gancho pode ter até ${m[2]} letras (está com ${m[1]}). Encurte o texto.`],
  [/gancho (obrigat|vazio)|informe o gancho/i, () => 'Escreva o gancho da capa.'],
  [/[aá]rea com (\d+) caracteres \(m[aá]ximo (\d+)\)/i, (m) => `A área pode ter até ${m[2]} letras.`],
  [/subt[ií]tulo com (\d+) caracteres \(m[aá]ximo (\d+)\)/i, (m) => `O subtítulo pode ter até ${m[2]} letras.`],
  [/texto longo demais para a capa/i, () => 'O texto ficou grande demais para a capa. Encurte o subtítulo.'],
  [/foto pequena demais/i, () => 'Essa foto é pequena demais para a capa. Use uma com pelo menos 600 pixels no lado menor.'],
  [/n[aã]o [eé] uma imagem que d[eê] para abrir/i, () => 'Não consegui abrir essa foto. Envie em PNG ou JPG.'],
  [/nenhum quadro utiliz[aá]vel/i,
    () => 'Não achei quadros bons no vídeo (escuros ou claros demais). Envie uma foto nos materiais.'],
  [/quadro escolhido n[aã]o existe|escolha o quadro|'quadro' deve/i,
    () => 'Escolha um dos quadros antes de gerar a capa.'],
  [/foto escolhida n[aã]o est[aá]|escolha a foto|'foto' deve/i, () => 'Escolha uma foto dos materiais.'],
  [/renderizador indispon[ií]vel|chromium|playwright|node ausente/i,
    () => 'Falta instalar uma peça do editor que desenha a capa e os cards. Abra a Instalação.'],
  [/frase (\d+)\D.*(barra invertida|chaves)/i,
    (m) => `Na frase ${Number(m[1]) + 1}, não use barra invertida (\\) nem chaves ({ }): a legenda não mostra esses sinais.`],
  [/barra invertida|chaves/i, () => 'Não use barra invertida (\\) nem chaves ({ }) na legenda: ela não mostra esses sinais.'],
  [/frase (\d+)\D.*m[aá]ximo (\d+) linhas/i,
    (m) => `Na frase ${Number(m[1]) + 1}, use no máximo ${m[2]} linhas.`],
  [/m[aá]ximo (\d+) linhas/i, (m) => `Use no máximo ${m[1]} linhas por legenda.`],
  [/texto autom[aá]tico mudou/i,
    () => 'Os cortes mudaram depois que você abriu esta tela. Recarregue a página e edite de novo.'],
  [/fora do intervalo/i, () => 'Esse trecho passa do fim do vídeo.'],
  [/ffprobe|ffmpeg|moov atom|invalid data|n[aã]o parece ser um v[ií]deo/i,
    () => 'Não consegui ler este vídeo. Envie de novo ou em outro formato (MP4).'],
  [/transcreva o v[ií]deo|arquivo ausente|envie o v[ií]deo/i, () => 'Falta um passo anterior. Volte e conclua.'],
  [/tarefa|revis[aã]o .*andamento|edi[cç][aã]o est[aá] em andamento/i,
    () => 'Espere o trabalho em andamento terminar e tente de novo.'],
  [/tempo limite|demorou demais/i, () => 'Demorou demais. Tente de novo.'],
  [/arquivos prontos/i, () => 'Ainda não há arquivos prontos neste Reel.'],
  [/sem conex[aã]o/i, (m, t) => t],
];

// sinais de texto tecnico ou sem acento que nao deve chegar a tela
const TECNICO = /ffmpeg|ffprobe|json|\.py\b|traceback|c[oó]digo \d|errno|0x[0-9a-f]|\bjob\b|\bnao\b|\bvoce\b|\binvalid\b|\berror\b|not found|[/\\][\w.-]+[/\\]|<projeto>/i;

function frase(t) {
  const s = String(t || '').trim();
  if (!s) return '';
  const f = s[0].toUpperCase() + s.slice(1);
  return /[.!?…]$/.test(f) ? f : f + '.';
}

/** Mensagem pronta para a tela; texto vazio vira ''. */
export function traduzir(msg) {
  const t = String(msg || '').trim();
  if (!t) return '';
  for (const [re, fn] of REGRAS) {
    const m = t.match(re);
    if (m) return fn(m, t);
  }
  return TECNICO.test(t) ? GENERICA : frase(t);
}

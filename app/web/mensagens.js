// Traduz mensagens tecnicas do servidor/scripts para portugues simples (sem DOM,
// testavel no node). review_apply.py e os scripts mantem a redacao deles (tambem
// alimentam a review.html e a linha de comando); a traducao acontece so aqui.

export const GENERICA = 'Algo deu errado. Tente de novo; se continuar, veja os detalhes.';

const REGRAS = [
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

// Contas de tempo entre o video original e o video cortado (sem DOM, testavel no node).
// Mesma matematica de review/review.html (mergeCuts, originalToCutTime,
// cutToOriginalTime); tests/test_app_ui_flow_a.py compara as duas em varios pontos.

/** Cortes [{start, end}] -> intervalos [[s, e]] ordenados e fundidos (vazios saem). */
export function mergeCuts(cuts) {
  const iv = cuts.map((c) => [Number(c.start), Number(c.end)]).filter((p) => p[1] > p[0])
    .sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const out = [];
  for (const [s, e] of iv) {
    if (out.length && s <= out[out.length - 1][1]) out[out.length - 1][1] = Math.max(out[out.length - 1][1], e);
    else out.push([s, e]);
  }
  return out;
}

/** Tempo do original -> tempo no video cortado (subtrai os cortes antes de t). */
export function originalToCutTime(t, cuts) {
  let removed = 0;
  for (const [s, e] of mergeCuts(cuts || [])) {
    if (s >= t) break;
    removed += Math.min(e, t) - s;
  }
  return Math.max(0, t - removed);
}

/** Tempo no video cortado -> tempo do original (pula os cortes). */
export function cutToOriginalTime(x, cuts) {
  let t = Math.max(0, x);
  for (const [s, e] of mergeCuts(cuts || [])) {
    if (s <= t) t += e - s; else break;
  }
  return t;
}

const DECIMAL = { minimumFractionDigits: 1, maximumFractionDigits: 1 };

/** 2.34 -> "2,3 s" */
export function segundos(s) {
  const n = Number.isFinite(s) ? Math.max(0, s) : 0;
  return `${n.toLocaleString('pt-BR', DECIMAL)} s`;
}

/** 63.27 -> "1:03,3" (minutos:segundos com um decimal) */
export function tempoFino(t) {
  const n = Number.isFinite(t) ? Math.max(0, t) : 0;
  const d = Math.round(n * 10) / 10;
  const m = Math.floor(d / 60);
  const s = d - m * 60;
  const [int, dec] = s.toFixed(1).split('.');
  return `${m}:${int.padStart(2, '0')},${dec}`;
}

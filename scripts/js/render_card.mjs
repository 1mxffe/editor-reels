// Driver Playwright dos efeitos do banco (chamado por scripts/graphics.py).
//
// Uso: node scripts/js/render_card.mjs <job.json>
// job = {html, banco, width, height, fps, data, frames?, outdir?, inspect?: {ts, shotdir?}}
//     | {verificar: [{id, html, banco, data, ts}], width, height}
// - html precisa ser <banco>/efeitos/<id>/efeito.html (arquivo comum, sem links).
// - frames: grava outdir/f00000.png ... (fundo transparente), um por quadro, chamando
//   window.setTime(i / fps); quadros com a mesma chave (texto devolvido) sao copiados.
// - inspect: para cada t mede a pagina (caixas em px de 1080x1920, opacidade de #efeito,
//   textos [data-texto], imagens) e junta window.inspect() se existir; com shotdir, salva
//   o PNG de cada t.
// - verificar: abre cada efeito, chama setup e setTime nos ts; devolve {id: motivo|null}.
// Sem rede: toda requisicao que nao seja file:/data:/blob: e abortada; Math.random, Date e
// performance.now ficam fixos (determinismo); cada etapa tem 5 s no maximo.
// Saida: JSON em stdout; erro = mensagem em stderr e codigo 1.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (e) {
  process.stderr.write('playwright (node) ausente: instale com "npm i -g playwright"\n');
  process.exit(1);
}

const LIMITE = 5000;
const SLUG = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

function limit(promise, what) {
  let timer;
  const t = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${what}: tempo esgotado (${LIMITE / 1000} s)`)), LIMITE);
  });
  return Promise.race([promise, t]).finally(() => clearTimeout(timer));
}

// O efeito precisa ser <banco>/efeitos/<id>/efeito.html, arquivo comum, sem links.
function efeitoSeguro(html, banco) {
  const raiz = fs.realpathSync(path.join(banco, 'efeitos'));
  const abs = path.resolve(html);
  const pasta = path.dirname(abs);
  if (path.basename(abs) !== 'efeito.html' || !SLUG.test(path.basename(pasta))) {
    throw new Error('efeito fora do banco: ' + html);
  }
  for (const p of [pasta, abs]) {
    if (fs.lstatSync(p).isSymbolicLink()) throw new Error('efeito com link (symlink): ' + html);
  }
  const real = fs.realpathSync(abs);
  if (path.dirname(path.dirname(real)) !== raiz || !fs.statSync(real).isFile()) {
    throw new Error('efeito fora do banco: ' + html);
  }
  return real;
}

// Antes de qualquer script da pagina: relogio e sorteio fixos (mesmo quadro sempre).
const DETERMINISMO = `(() => {
  let s = 0x2545f491;
  Math.random = () => { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; return (s >>> 0) / 4294967296; };
  const T0 = 1767225600000, D = Date;
  class FixedDate extends D { constructor(...a) { super(...(a.length ? a : [T0])); } static now() { return T0; } }
  window.Date = FixedDate;
  performance.now = () => 0;
})();`;

function medir(scale) {
  const root = document.getElementById('efeito') || document.body;
  const k = 1 / scale;
  const box = (r) => ({ top: r.top * k, bottom: r.bottom * k, left: r.left * k, right: r.right * k });
  const caixas = [];
  // moldura (data-moldura) = recipiente do tamanho da tela: nao conta como caixa
  for (const el of [root, ...root.querySelectorAll('*')]) {
    if (el.hasAttribute('data-moldura')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    caixas.push({ ...box(r), id: el.id || null });
  }
  const imgs = [...document.querySelectorAll('img')];
  return {
    caixas,
    opacidade: Number(getComputedStyle(root).opacity),
    textos: [...document.querySelectorAll('[data-texto]')].map((e) => e.textContent),
    imgCount: imgs.length,
    imgLoaded: imgs.length ? imgs.every((i) => i.complete && i.naturalWidth > 0) : null,
    xss: window.__xss === undefined ? null : window.__xss,
    extra: typeof window.inspect === 'function' ? window.inspect() : {},
  };
}

async function abrir(ctx, html, banco, data, pageErrors) {
  const real = efeitoSeguro(html, banco);
  const page = await ctx.newPage();
  page.setDefaultTimeout(LIMITE);
  await page.addInitScript(DETERMINISMO);
  await page.route('**/*', (route) => {
    const u = route.request().url();
    return u.startsWith('file:') || u.startsWith('data:') || u.startsWith('blob:') ? route.continue() : route.abort();
  });
  page.on('pageerror', (e) => pageErrors.push(String(e && e.message || e).split('\n')[0]));
  await limit(page.goto(pathToFileURL(real).href), 'abrir o efeito');
  const tem = await page.evaluate(() => typeof window.setup === 'function' && typeof window.setTime === 'function');
  if (!tem) throw new Error('efeito.html precisa definir window.setup(dados) e window.setTime(t)');
  try {
    await limit(page.evaluate((d) => window.setup(d), data), 'setup');
  } catch (e) {
    throw new Error('setup do efeito falhou: ' + String(e.message || e).split('\n')[0]);
  }
  return page;
}

async function setTime(page, t) {
  try {
    return await limit(page.evaluate((x) => window.setTime(x), t), `setTime(${t})`);
  } catch (e) {
    throw new Error(`setTime(${Number(t).toFixed(3)}) do efeito falhou: ` + String(e.message || e).split('\n')[0]);
  }
}

const browser = await chromium.launch();
let code = 0;
try {
  const ctx = await browser.newContext({ viewport: { width: job.width, height: job.height }, deviceScaleFactor: 1 });
  if (job.verificar) {
    const out = {};
    for (const j of job.verificar) {
      const pageErrors = [];
      let page = null;
      try {
        page = await abrir(ctx, j.html, j.banco, j.data, pageErrors);
        for (const t of j.ts) await setTime(page, t);
        out[j.id] = pageErrors.length ? 'erro na página: ' + pageErrors[0] : null;
      } catch (e) {
        out[j.id] = String(e && e.message || e).split('\n')[0];
      } finally {
        if (page) await page.close();
      }
    }
    process.stdout.write(JSON.stringify(out));
  } else {
    const pageErrors = [];
    const page = await abrir(ctx, job.html, job.banco, job.data, pageErrors);
    if (job.inspect) {
      const quadros = [];
      for (const [i, t] of job.inspect.ts.entries()) {
        await setTime(page, t);
        const q = { t, ...(await page.evaluate(medir, job.data.scale)) };
        if (job.inspect.shotdir) {
          q.shot = path.join(job.inspect.shotdir, `q${i}.png`);
          await page.screenshot({ path: q.shot, omitBackground: true });
        }
        quadros.push(q);
      }
      process.stdout.write(JSON.stringify({ quadros, pageErrors }));
    } else {
      let prevKey = null, prevFile = null, unique = 0;
      for (let i = 0; i < job.frames; i++) {
        const key = await setTime(page, i / job.fps);
        const file = path.join(job.outdir, 'f' + String(i).padStart(5, '0') + '.png');
        if (typeof key === 'string' && key === prevKey) fs.copyFileSync(prevFile, file);
        else { await page.screenshot({ path: file, omitBackground: true }); unique++; }
        prevKey = typeof key === 'string' ? key : null; prevFile = file;
      }
      process.stdout.write(JSON.stringify({ frames: job.frames, unique, pageErrors }));
    }
  }
} catch (e) {
  process.stderr.write(String(e && e.message || e) + '\n');
  code = 1;
} finally {
  await browser.close();
}
process.exit(code);

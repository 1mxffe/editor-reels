// Driver Playwright dos cards de grafico (chamado por scripts/graphics.py).
//
// Uso: node scripts/js/render_card.mjs <job.json>
// job = {html, width, height, frames, fps, outdir, data, inspect?: {t, shot?}}
// - sem "inspect": grava outdir/f00000.png ... (fundo transparente), um por quadro,
//   chamando window.setTime(i / fps); quadros com o mesmo estado sao copiados.
// - com "inspect": posiciona em t, opcionalmente salva um PNG e imprime o
//   resultado de window.inspect() (testes).
// Sem rede: toda requisicao que nao seja file:/data: e abortada.
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

const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const browser = await chromium.launch();
let code = 0;
try {
  const ctx = await browser.newContext({ viewport: { width: job.width, height: job.height }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  await page.route('**/*', (route) => {
    const u = route.request().url();
    return u.startsWith('file:') || u.startsWith('data:') ? route.continue() : route.abort();
  });
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  await page.goto(pathToFileURL(job.html).href);
  try {
    await page.evaluate((d) => window.setup(d), job.data);
  } catch (e) {
    throw new Error('card nao montou (imagem de apoio ilegivel?): ' + String(e.message || e).split('\n')[0]);
  }
  if (job.inspect) {
    await page.evaluate((t) => window.setTime(t), job.inspect.t);
    if (job.inspect.shot) await page.screenshot({ path: job.inspect.shot, omitBackground: true });
    const info = await page.evaluate(() => window.inspect());
    process.stdout.write(JSON.stringify({ ...info, pageErrors }));
  } else {
    let prevKey = null, prevFile = null, unique = 0;
    for (let i = 0; i < job.frames; i++) {
      const key = await page.evaluate((t) => window.setTime(t), i / job.fps);
      const file = path.join(job.outdir, 'f' + String(i).padStart(5, '0') + '.png');
      if (key === prevKey) fs.copyFileSync(prevFile, file);
      else { await page.screenshot({ path: file, omitBackground: true }); unique++; }
      prevKey = key; prevFile = file;
    }
    process.stdout.write(JSON.stringify({ frames: job.frames, unique, pageErrors }));
  }
} catch (e) {
  process.stderr.write(String(e && e.message || e) + '\n');
  code = 1;
} finally {
  await browser.close();
}
process.exit(code);

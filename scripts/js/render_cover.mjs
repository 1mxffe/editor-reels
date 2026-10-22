// Driver Playwright da capa do Reel (chamado por scripts/cover_compose.py).
//
// Uso: node scripts/js/render_cover.mjs <job.json>
// job = {html, width, height, data, shot?}
// Monta a pagina com window.setup(data) e imprime as medidas devolvidas (JSON);
// com "shot", grava o quadro inteiro, opaco, nesse PNG.
// Sem rede: toda requisicao que nao seja file:/data: e abortada; cada etapa da
// pagina tem 5 s no maximo.
// Saida: JSON em stdout; erro = mensagem em stderr e codigo 1.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (e) {
  process.stderr.write('playwright (node) ausente: instale com "npm i -g playwright"\n');
  process.exit(1);
}

const PAGE_TIMEOUT = 5000;
const job = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

function limit(promise, what) {
  let timer;
  const t = new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error(`${what}: tempo esgotado (${PAGE_TIMEOUT / 1000} s)`)), PAGE_TIMEOUT);
  });
  return Promise.race([promise, t]).finally(() => clearTimeout(timer));
}

const browser = await chromium.launch();
let code = 0;
try {
  const ctx = await browser.newContext({ viewport: { width: job.width, height: job.height }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  page.setDefaultTimeout(PAGE_TIMEOUT);
  page.setDefaultNavigationTimeout(PAGE_TIMEOUT);
  await page.route('**/*', (route) => {
    const u = route.request().url();
    return u.startsWith('file:') || u.startsWith('data:') ? route.continue() : route.abort();
  });
  const pageErrors = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  await page.goto(pathToFileURL(job.html).href);
  let info;
  try {
    info = await limit(page.evaluate((d) => window.setup(d), job.data), 'montagem da capa');
  } catch (e) {
    throw new Error('capa nao montou (foto ou logotipo ilegivel?): ' + String(e.message || e).split('\n')[0]);
  }
  if (job.shot) {
    await page.screenshot({ path: job.shot, type: 'png', omitBackground: false,
                            clip: { x: 0, y: 0, width: job.width, height: job.height } });
  }
  process.stdout.write(JSON.stringify({ ...info, pageErrors }));
} catch (e) {
  process.stderr.write(String(e && e.message || e) + '\n');
  code = 1;
} finally {
  await browser.close();
}
process.exit(code);

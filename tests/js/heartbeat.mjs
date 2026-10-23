// Batida (heartbeat) da pagina: POST /api/heartbeat ao abrir e a cada 10 s; falha calada.
//
// Uso: node tests/js/heartbeat.mjs <config.json>   config: {tmp, brand}
// Relogio da pagina controlado pelo Playwright (page.clock): nada de esperar 10 s de verdade.
// Imprime um JSON com as observacoes; quem afirma e o pytest (tests/test_app_launch.py).
import fs from 'node:fs';
import path from 'node:path';
import { iniciarServidor, esperar, require_ } from './helpers.mjs';

const { chromium } = require_('playwright');
const cfg = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
const DOCTOR_OK = { estado: 'READY', itens: [{ name: 'python >= 3.11', ok: true, required: true }] };

const srv = await iniciarServidor({ root: path.join(cfg.tmp, 'projects'), brand: cfg.brand,
  doctor: DOCTOR_OK }, cfg.tmp);
const browser = await chromium.launch();
const out = {};
try {
  const page = await browser.newPage();
  const batidas = [];
  page.on('request', (r) => {
    if (new URL(r.url()).pathname === '/api/heartbeat') {
      batidas.push({ metodo: r.method(), token: r.headers()['x-token'] === srv.token });
    }
  });
  await page.clock.install();
  await page.goto(srv.url);
  await esperar(() => batidas.length >= 1);
  await page.waitForTimeout(300); // nenhuma batida extra sem o relogio andar
  out.inicial = batidas.length;
  await page.clock.runFor(10_000);
  await esperar(() => batidas.length >= out.inicial + 1);
  out.depois10s = batidas.length;
  await page.clock.runFor(10_000);
  await esperar(() => batidas.length >= out.inicial + 2);
  out.depois20s = batidas.length;
  // editor fora do ar: a batida falha sem aviso nenhum na tela
  await page.route('**/api/heartbeat', (r) => r.abort());
  await page.clock.runFor(10_000);
  await esperar(() => batidas.length >= out.inicial + 3);
  await page.waitForTimeout(200);
  out.fatal = await page.evaluate(() => !document.getElementById('fatal').hidden);
  out.batidas = batidas;
} catch (e) {
  out.error = String(e && e.stack || e);
} finally {
  await browser.close();
  srv.parar();
}
process.stdout.write(JSON.stringify(out));

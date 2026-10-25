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
  let terminadas = 0;
  const ehBatida = (r) => new URL(r.url()).pathname === '/api/heartbeat';
  page.on('request', (r) => {
    if (ehBatida(r)) batidas.push({ metodo: r.method(), token: r.headers()['x-token'] === srv.token });
  });
  // a resposta precisa ser lida ate o fim: pedido "pendurado" prende conexao e networkidle
  page.on('requestfinished', (r) => { if (ehBatida(r)) terminadas += 1; });
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
  await esperar(() => terminadas >= out.depois20s);
  out.terminadas = terminadas;
  await page.waitForLoadState('networkidle', { timeout: 5000 });
  out.ociosa = true;
  // aba escondida volta a ficar visivel / janela ganha o foco: bate na hora, sem esperar o timer
  const antes = batidas.length;
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await esperar(() => batidas.length >= antes + 1);
  out.aoVoltarVisivel = batidas.length - antes;
  await esperar(() => terminadas >= batidas.length);
  const antesFoco = batidas.length;
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await esperar(() => batidas.length >= antesFoco + 1);
  out.aoVoltarFoco = batidas.length - antesFoco;
  await esperar(() => terminadas >= batidas.length);
  // editor fora do ar: a batida falha sem aviso nenhum na tela
  const base = batidas.length;
  await page.route('**/api/heartbeat', (r) => r.abort());
  await page.clock.runFor(10_000);
  await esperar(() => batidas.length >= base + 1);
  await page.waitForTimeout(200);
  out.fatal = await page.evaluate(() => !document.getElementById('fatal').hidden);
  // varias falhas seguidas: mensagem clara em portugues, no lugar do erro generico
  await page.clock.runFor(10_000);
  await page.clock.runFor(10_000);
  await esperar(async () => page.evaluate(() => !document.getElementById('fatal').hidden));
  out.aviso = await page.evaluate(() => ({
    titulo: document.getElementById('fatal-titulo').textContent,
    texto: document.getElementById('fatal-texto').textContent }));
  // chamadas da API sem resposta usam a mesma mensagem
  await page.route('**/api/config', (r) => r.abort());
  out.msgApi = await page.evaluate(async () => {
    const m = await import('/static/nucleo.js');
    try { await m.api('GET', '/api/config'); return ''; } catch (e) { return e.mensagem; }
  });
  // o editor volta (ex.: notebook acordou): o aviso some sozinho
  await page.unroute('**/api/heartbeat');
  await page.clock.runFor(10_000);
  await esperar(async () => page.evaluate(() => document.getElementById('fatal').hidden));
  out.avisoSumiu = true;
  out.batidas = batidas;
} catch (e) {
  out.error = String(e && e.stack || e);
} finally {
  await browser.close();
  srv.parar();
}
process.stdout.write(JSON.stringify(out));

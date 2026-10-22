// Driver Playwright da pagina de revisao (review/review.html).
//
// Uso: node tests/js/review_driver.cjs <review.html> <dir_fixtures>
// <dir_fixtures>/<nome>/ sao pastas de projeto (review.json, saida/preview.mp4...).
// Imprime em stdout um JSON {cenario: observacoes | {error}}; quem afirma e o pytest.
//
// showDirectoryPicker nao tem resposta em headless: cada cenario injeta, via
// addInitScript, um diretorio EM MEMORIA (getFileHandle/getDirectoryHandle/
// createWritable/getFile/removeEntry) semeado com os arquivos da fixture.
'use strict';
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const [htmlPath, fixDir] = process.argv.slice(2);
const URL_ = 'file://' + path.resolve(htmlPath);

function seed(name, extra = {}) {
  const root = path.join(fixDir, name);
  const files = {};
  const walk = (dir) => {
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, ent.name);
      if (ent.isDirectory()) walk(p);
      else {
        const rel = path.relative(root, p).split(path.sep).join('/');
        files[rel] = { b64: fs.readFileSync(p).toString('base64'),
          type: rel.endsWith('.json') ? 'application/json' : rel.endsWith('.mp4') ? 'video/mp4' : '' };
      }
    }
  };
  walk(root);
  for (const [k, v] of Object.entries(extra)) {
    if (v === null) delete files[k];
    else files[k] = { b64: Buffer.from(v).toString('base64'), type: 'application/json' };
  }
  return files;
}

// Roda dentro da pagina (antes de qualquer script dela).
function mockInit(files) {
  const store = new Map();
  for (const [p, f] of Object.entries(files)) {
    const bin = atob(f.b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    store.set(p, new Blob([u8], { type: f.type }));
  }
  const dirs = new Set(['']);
  for (const p of store.keys()) {
    const parts = p.split('/');
    for (let i = 1; i < parts.length; i++) dirs.add(parts.slice(0, i).join('/'));
  }
  const writes = {};
  const nf = (n) => new DOMException('nao existe: ' + n, 'NotFoundError');
  const join = (a, b) => (a ? a + '/' + b : b);
  function fileHandle(p) {
    return {
      kind: 'file', name: p.split('/').pop(),
      async getFile() {
        if (!store.has(p)) throw nf(p);
        const b = store.get(p);
        return new File([b], p.split('/').pop(), { type: b.type });
      },
      async createWritable() {
        const chunks = [];
        return {
          async write(d) {
            if (d && typeof d === 'object' && d.type === 'write') d = d.data;
            chunks.push(d);
          },
          async close() {
            store.set(p, new Blob(chunks));
            writes[p] = (writes[p] || 0) + 1;
          },
          async abort() {},
        };
      },
    };
  }
  function dirHandle(dp) {
    return {
      kind: 'directory', name: dp.split('/').pop() || 'reel-teste',
      async getFileHandle(n, opt = {}) {
        if (n.includes('/') || n.includes('\\')) throw new TypeError('nome invalido: ' + n);
        const p = join(dp, n);
        if (!store.has(p)) {
          if (!opt.create) throw nf(p);
          store.set(p, new Blob([]));
        }
        return fileHandle(p);
      },
      async getDirectoryHandle(n, opt = {}) {
        const p = join(dp, n);
        if (!dirs.has(p)) {
          if (!opt.create) throw nf(p);
          dirs.add(p);
        }
        return dirHandle(p);
      },
      async removeEntry(n) {
        const p = join(dp, n);
        if (!store.delete(p)) throw nf(p);
      },
      async queryPermission() { return 'granted'; },
      async requestPermission() { return 'granted'; },
    };
  }
  window.showDirectoryPicker = async () => dirHandle('');
  window.__mockFS = {
    writes,
    async text(p) { return store.has(p) ? await store.get(p).text() : null; },
    list() { return [...store.keys()].sort(); },
    put(p, text) { store.set(p, new Blob([text], { type: 'application/json' })); },
  };
}

async function openPage(browser, files, opts = {}) {
  const ctx = await browser.newContext({ viewport: opts.viewport || { width: 1280, height: 900 },
    acceptDownloads: true, colorScheme: opts.colorScheme || 'dark' });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  // sem rede: qualquer pedido que nao seja do disco/blob/data vira erro do cenario
  page.on('request', (r) => { if (!/^(file|blob|data):/.test(r.url())) errors.push('rede: ' + r.url()); });
  if (files) await page.addInitScript(mockInit, files);
  else await page.addInitScript(() => { delete window.showDirectoryPicker; });
  await page.goto(URL_);
  if (files) {
    await page.click('#open-folder');
    await page.waitForSelector('body[data-state="ready"]', { timeout: 5000 });
  }
  return { ctx, page, errors };
}

async function decisionsAfter(page, n) {
  await page.waitForFunction((k) => (window.__mockFS.writes['decisions.json'] || 0) >= k, n,
    { timeout: 4000 });
  return JSON.parse(await page.evaluate(() => window.__mockFS.text('decisions.json')));
}
async function decisionsWhen(page, pred) {
  for (let i = 0; i < 40; i++) {
    const t = await page.evaluate(() => window.__mockFS.text('decisions.json'));
    if (t) { const d = JSON.parse(t); if (pred(d)) return d; }
    await page.waitForTimeout(100);
  }
  throw new Error('decisions.json nao chegou ao estado esperado: '
    + await page.evaluate(() => window.__mockFS.text('decisions.json')));
}
const writesOf =(page, p) => page.evaluate((q) => window.__mockFS.writes[q] || 0, p);

async function wordByText(page, w) {
  return page.locator('.word', { hasText: w }).first();
}

const scenarios = {
  async tabs(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('main'));
    const info = await page.evaluate(() => {
      const tabs = [...document.querySelectorAll('[role="tablist"] [role="tab"]')];
      return {
        title: document.title, lang: document.documentElement.lang,
        tablists: document.querySelectorAll('[role="tablist"]').length,
        tabs: tabs.map((t) => ({ id: t.id, selected: t.getAttribute('aria-selected'),
          controls: t.getAttribute('aria-controls'), text: t.textContent.trim(),
          panelRole: document.getElementById(t.getAttribute('aria-controls'))?.getAttribute('role'),
          panelHidden: document.getElementById(t.getAttribute('aria-controls'))?.hidden })),
        landmarks: { main: !!document.querySelector('main'), header: !!document.querySelector('header') },
      };
    });
    await page.focus('#tab-revisao');
    await page.keyboard.press('ArrowRight');
    const after = await page.evaluate(() => ({
      focused: document.activeElement.id,
      selected: document.getElementById('tab-materiais').getAttribute('aria-selected'),
      revisaoHidden: document.getElementById('panel-revisao').hidden,
      materiaisHidden: document.getElementById('panel-materiais').hidden,
      emptyVisible: !!document.querySelector('#materials-empty:not([hidden])'),
      emptyText: document.querySelector('#materials-empty')?.textContent || '',
    }));
    await page.keyboard.press('ArrowLeft');
    const back = await page.evaluate(() => document.activeElement.id);
    await ctx.close();
    return { ...info, after, back, errors };
  },

  async empty_materials(browser) {
    const out = {};
    for (const [k, extra] of [['absent', {}], ['empty', { 'materiais.json': '{"items":[]}' }]]) {
      const { ctx, page, errors } = await openPage(browser, seed('main', extra));
      await page.click('#tab-materiais');
      out[k] = await page.evaluate(() => ({
        emptyVisible: !!document.querySelector('#materials-empty:not([hidden])'),
        items: document.querySelectorAll('#mat-list .mat-item').length,
        errorText: [...document.querySelectorAll('[role="alert"]')]
          .filter((e) => !e.hidden && e.textContent.trim()).map((e) => e.textContent.trim()),
      }));
      out[k].errors = errors;
      out[k].materiaisWrites = await writesOf(page, 'materiais.json');
      await ctx.close();
    }
    return out;
  },

  async word_click(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('main'));
    const nWords = await page.locator('.word').count();
    const calma = await wordByText(page, 'calma.');
    await calma.click();
    const d1 = await decisionsAfter(page, 1);
    const calmaState = await calma.getAttribute('data-state');
    await calma.click();
    const d2 = await decisionsAfter(page, 2);
    const com = page.locator('.word[data-i="10"]');
    const comBefore = await com.getAttribute('data-state');
    await com.click();
    const d3 = await decisionsAfter(page, 3);
    const comAfter = await com.getAttribute('data-state');
    await com.click();
    const d4 = await decisionsAfter(page, 4);
    // seek: "Leia" (3.80 original) no video cortado = 3.80 - 0.45 - 0.8
    await (await wordByText(page, 'Leia')).click();
    const seek = await page.evaluate(() => document.getElementById('video').currentTime);
    const status = await page.textContent('#save-status');
    const hint = await page.evaluate(() => document.body.innerText.includes('aplicar revisão'));
    await ctx.close();
    return { nWords, d1, calmaState, d2, comBefore, d3, comAfter, d4, seek, status, hint, errors };
  },

  async no_hscroll(browser) {
    const out = [];
    for (const theme of ['dark', 'light']) {
      const { ctx, page } = await openPage(browser, seed('main'),
        { viewport: { width: 375, height: 812 }, colorScheme: theme });
      for (const tab of ['revisao', 'materiais']) {
        await page.click('#tab-' + tab);
        await page.waitForTimeout(350);
        out.push({ theme, tab, ...(await page.evaluate(() => {
          const lum = (c) => {
            const m = c.match(/[\d.]+/g).map(Number).slice(0, 3).map((v) => {
              v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
            return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2];
          };
          const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
            return (x + 0.05) / (y + 0.05); };
          const cs = getComputedStyle(document.body);
          const muted = document.querySelector('.muted');
          return {
            scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth,
            bodyContrast: ratio(cs.color, cs.backgroundColor),
            mutedContrast: muted ? ratio(getComputedStyle(muted).color, cs.backgroundColor) : null,
            dataTheme: document.documentElement.getAttribute('data-theme'),
          };
        })) });
      }
      // toggle manual inverte o tema
      const before = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      await page.click('#theme-toggle');
      await page.waitForTimeout(400);
      const after = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
      out.push({ theme, toggleChanged: before !== after,
        scrollWidth: await page.evaluate(() => document.documentElement.scrollWidth),
        innerWidth: 375 });
      await ctx.close();
    }
    return out;
  },

  async caption_edit(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('main'));
    const field = page.locator('.phrase-text[data-idx="0"]');
    const original = await field.inputValue();
    await field.fill('Novo texto da legenda');
    const d1 = await decisionsAfter(page, 1);
    const edited = await page.locator('.phrase[data-idx="0"]').getAttribute('data-edited');
    await field.fill('');
    const d2 = await decisionsAfter(page, 2);
    await field.blur();
    const shownAfterBlank = await field.inputValue();
    // grafico: manter -> descartar
    await page.click('.graphic-toggle[data-id="g1"]');
    const d3 = await decisionsAfter(page, 3);
    const times = await page.textContent('.phrase[data-idx="0"] .phrase-time');
    await ctx.close();
    return { original, d1, edited, d2, shownAfterBlank, d3, times, errors };
  },

  async caption_restore(browser) {
    // decisions.json com edicoes presas ao texto automatico: so volta a que ainda bate
    const review = JSON.parse(fs.readFileSync(path.join(fixDir, 'main', 'review.json'), 'utf8'));
    const base0 = review.phrases[0].base_text;
    const base1 = review.phrases[1].base_text;
    const pending = JSON.stringify({ cuts_removed: [], cuts_added: [], graphics: {}, notes: [],
      caption_edits: { 0: { text: 'Restaurada', base_text: base0 }, 1: { text: 'Velha', base_text: 'outro texto' } } });
    const { ctx, page, errors } = await openPage(browser, seed('main', { 'decisions.json': pending }));
    const field0 = await page.locator('.phrase-text[data-idx="0"]').inputValue();
    const field1 = await page.locator('.phrase-text[data-idx="1"]').inputValue();
    const edited0 = await page.locator('.phrase[data-idx="0"]').getAttribute('data-edited');
    await page.locator('.phrase-text[data-idx="0"]').fill('Restaurada ');
    await page.locator('.phrase-text[data-idx="0"]').fill('Restaurada');
    const d = await decisionsWhen(page, (x) => Object.keys(x.caption_edits).length === 1);
    await ctx.close();
    return { field0, field1, edited0, base0, base1, d, errors };
  },

  async csp(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('main'));
    const requests = [];
    const failed = new Map();
    page.on('request', (r) => requests.push(r.url()));
    page.on('requestfailed', (r) => failed.set(r.url(), (r.failure() || {}).errorText || ''));
    const fetched = await page.evaluate(() => fetch('https://example.com/x').then(() => 'ok', () => 'blocked'));
    const img = await page.evaluate(() => new Promise((res) => {
      const i = new Image(); i.onload = () => res('ok'); i.onerror = () => res('blocked');
      i.src = 'https://example.com/p.png';
    }));
    const meta = await page.evaluate(() => {
      const m = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
      return m ? m.content : null;
    });
    await page.waitForTimeout(150);
    await ctx.close();
    const cspErrors = errors.filter((e) => /Content Security Policy/i.test(e)).length;
    // o Chromium anuncia o pedido e o falha com ERR_BLOCKED_BY_CSP: nada sai para a rede
    const network = requests.filter((u) => !/^(file|blob|data):/.test(u)
      && !/BLOCKED_BY_CSP|^csp$/i.test(failed.get(u) || ''));
    return { fetched, img, meta, requests: network, cspErrors, failures: [...failed.values()] };
  },

  async notes(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('main'));
    await page.evaluate(() => { document.getElementById('video').currentTime = 2.0; });
    await page.waitForTimeout(150);
    await page.click('#add-note');
    const ta = page.locator('.note-text').first();
    const label = await page.textContent('.note-time');
    await ta.fill('Ajustar a luz aqui');
    const d1 = await decisionsWhen(page, (d) => (d.notes || []).length === 1);
    await ta.fill('Ajustar a luz aqui, mais quente');
    const d2 = await decisionsWhen(page, (d) => (d.notes || [])[0]?.text.endsWith('quente'));
    await page.click('.note-delete');
    const d3 = await decisionsWhen(page, (d) => (d.notes || []).length === 0);
    await ctx.close();
    return { label, d1, d2, d3, errors };
  },

  async mapping(browser) {
    const { ctx, page } = await openPage(browser, null);
    const r = await page.evaluate(() => {
      const f = window.ReviewApp.originalToCutTime;
      const g = window.ReviewApp.cutToOriginalTime;
      const cuts = [{ start: 0, end: 0.45 }, { start: 2.6, end: 3.4 }, { start: 3.0, end: 3.6 }];
      return {
        a: f(0.2, cuts), b: f(1.0, cuts), c: f(3.0, cuts), d: f(4.0, cuts), e: f(1.0, []),
        inv: g(f(4.0, cuts), cuts), inv2: g(0, cuts),
      };
    });
    await ctx.close();
    return r;
  },

  async stale(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('stale'));
    const r = await page.evaluate(() => {
      const w = document.getElementById('warnings');
      return { hidden: w.hidden, text: w.textContent, items: w.querySelectorAll('li').length };
    });
    await ctx.close();
    return { ...r, errors };
  },

  async materials_write(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('main'));
    await page.click('#tab-materiais');
    const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
    await page.setInputFiles('#mat-file-input', [{ name: '../../etc/fo\u0007to 1.png', mimeType: 'image/png', buffer: png }]);
    await page.waitForFunction(() => (window.__mockFS.writes['materiais.json'] || 0) >= 1, null, { timeout: 4000 });
    await page.setInputFiles('#mat-file-input', [{ name: '..\\fo to 1.png', mimeType: 'image/png', buffer: png }]);
    await page.waitForFunction(() => (window.__mockFS.writes['materiais.json'] || 0) >= 2, null, { timeout: 4000 });
    // arrastar e soltar um svg (icone)
    await page.evaluate(() => {
      const dt = new DataTransfer();
      dt.items.add(new File(['<svg xmlns="http://www.w3.org/2000/svg"/>'], 'seta.svg', { type: 'image/svg+xml' }));
      const z = document.getElementById('mat-dropzone');
      z.dispatchEvent(new DragEvent('dragover', { dataTransfer: dt, bubbles: true, cancelable: true }));
      z.dispatchEvent(new DragEvent('drop', { dataTransfer: dt, bubbles: true, cancelable: true }));
    });
    await page.waitForFunction(() => (window.__mockFS.writes['materiais.json'] || 0) >= 3, null, { timeout: 4000 });
    // link: javascript: recusado; https aceito
    await page.fill('#mat-url', 'javascript:alert(1)');
    await page.click('#mat-url-add');
    const urlError = await page.textContent('#mat-url-error');
    const itemsAfterBad = await page.locator('#mat-list .mat-item').count();
    await page.fill('#mat-url', 'https://example.com/referencia');
    await page.click('#mat-url-add');
    await page.waitForFunction(() => (window.__mockFS.writes['materiais.json'] || 0) >= 4, null, { timeout: 4000 });
    // nota no primeiro item
    await page.locator('.mat-note').first().fill('usar no gancho');
    await page.waitForFunction(() => (window.__mockFS.writes['materiais.json'] || 0) >= 5, null, { timeout: 4000 });
    const link = await page.evaluate(() => {
      const a = document.querySelector('#mat-list a.mat-link');
      return a && { href: a.href, rel: a.rel, target: a.target };
    });
    const iframes = await page.locator('iframe').count();
    const mj1 = JSON.parse(await page.evaluate(() => window.__mockFS.text('materiais.json')));
    const files1 = await page.evaluate(() => window.__mockFS.list());
    // remover o segundo item
    await page.locator('#mat-list .mat-item').nth(1).locator('.mat-remove').click();
    await page.waitForFunction(() => (window.__mockFS.writes['materiais.json'] || 0) >= 6, null, { timeout: 4000 });
    const mj2 = JSON.parse(await page.evaluate(() => window.__mockFS.text('materiais.json')));
    const files2 = await page.evaluate(() => window.__mockFS.list());
    const san = await page.evaluate(() => [
      window.ReviewApp.sanitizeName('a/b\\c\u0000d.JPG'), window.ReviewApp.sanitizeName('...'),
      window.ReviewApp.uniqueName('x.png', ['x.png', 'x-2.png']),
      window.ReviewApp.isSafeUrl('http://a.b'), window.ReviewApp.isSafeUrl('data:text/html,1'),
      window.ReviewApp.isSafeUrl('JavaScript:alert(1)'),
    ]);
    await ctx.close();
    return { urlError, itemsAfterBad, link, iframes, mj1, files1, mj2, files2, san, errors };
  },

  async xss(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('xss'));
    await page.click('#tab-materiais');
    await page.waitForTimeout(200);
    const r = await page.evaluate(() => ({
      fired: window.__xss === 1,
      evilImgs: document.querySelectorAll('img[src="x"], img[src$="/x"]').length,
      wordText: [...document.querySelectorAll('.word')].map((w) => w.textContent).find((t) => t.includes('<img')) || null,
      phraseText: [...document.querySelectorAll('.phrase-text')].map((p) => p.value).find((t) => t.includes('<img')) || null,
      matText: document.getElementById('mat-list').textContent
        + [...document.querySelectorAll('#mat-list .mat-note')].map((n) => n.value).join('|'),
      graphicsEmpty: document.getElementById('graphics').textContent,
    }));
    await ctx.close();
    return { ...r, errors };
  },

  async cards(browser) {
    const { ctx, page, errors } = await openPage(browser, seed('cards'));
    const info = await page.evaluate(() => ({
      labels: [...document.querySelectorAll('#graphics .graphic strong')].map((e) => e.textContent),
      fired: window.__xss === 1,
      checked: Object.fromEntries([...document.querySelectorAll('#graphics .graphic-toggle')]
        .map((b) => [b.dataset.id, b.getAttribute('aria-checked')])),
    }));
    await page.click('.graphic-toggle[data-id="k1"]');
    const d = await decisionsAfter(page, 1);
    await ctx.close();
    return { ...info, d, errors };
  },

  async reload(browser) {
    // 1) decisions.json existente e restaurado ao abrir
    const pending = JSON.stringify({ cuts_removed: [], cuts_added: [{ start: 4.9, end: 5.3 }],
      caption_edits: {}, graphics: {}, notes: [{ t: 1, text: 'nota salva' }] });
    const { ctx, page, errors } = await openPage(browser, seed('main', { 'decisions.json': pending }));
    const calma = page.locator('.word[data-i="11"]');
    const restored = { state: await calma.getAttribute('data-state'), pending: await calma.getAttribute('data-pending'),
      notes: await page.locator('.note-text').count(), writes: await writesOf(page, 'decisions.json') };
    // 2) o Claude aplica + build; "Recarregar" filtra o que ja entrou
    const applied = fs.readFileSync(path.join(fixDir, 'main_applied', 'review.json'), 'utf8');
    await page.evaluate((t) => window.__mockFS.put('review.json', t), applied);
    await page.click('#reload');
    const d = await decisionsWhen(page, (x) => x.cuts_added.length === 0);
    const after = { state: await calma.getAttribute('data-state'), pending: await calma.getAttribute('data-pending'),
      status: await page.textContent('#save-status') };
    await ctx.close();
    return { restored, d, after, errors };
  },

  async fallback(browser) {
    const { ctx, page, errors } = await openPage(browser, null);
    const fsaHidden = await page.evaluate(() => document.getElementById('open-folder').hidden
      || document.getElementById('open-folder').disabled);
    await page.setInputFiles('#file-review', path.join(fixDir, 'main', 'review.json'));
    await page.waitForSelector('body[data-state="ready"]', { timeout: 5000 });
    await page.setInputFiles('#file-video', path.join(fixDir, 'main', 'saida', 'preview.mp4'));
    await (await wordByText(page, 'calma.')).click();
    await page.waitForTimeout(600);
    const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#download-decisions')]);
    const decisions = JSON.parse(fs.readFileSync(await dl.path(), 'utf8'));
    const dlName = dl.suggestedFilename();
    await page.click('#tab-materiais');
    const notice = await page.evaluate(() => {
      const n = document.getElementById('mat-fallback-notice');
      return { hidden: n.hidden, text: n.textContent };
    });
    await page.fill('#mat-url', 'https://example.com/a');
    await page.click('#mat-url-add');
    const [dl2] = await Promise.all([page.waitForEvent('download'), page.click('#download-materiais')]);
    const materiais = JSON.parse(fs.readFileSync(await dl2.path(), 'utf8'));
    const status = await page.textContent('#save-status');
    await ctx.close();
    return { fsaHidden, decisions, dlName, notice, materiais, status, errors };
  },
};

(async () => {
  const only = process.env.REVIEW_SCENARIOS ? process.env.REVIEW_SCENARIOS.split(',') : null;
  const browser = await chromium.launch();
  const out = {};
  try {
    const names = Object.keys(scenarios).filter((n) => !only || only.includes(n));
    await Promise.all(names.map(async (n) => {
      try { out[n] = await scenarios[n](browser); } catch (e) { out[n] = { error: String(e && e.stack || e) }; }
    }));
  } finally {
    await browser.close();
  }
  process.stdout.write(JSON.stringify(out));
})();

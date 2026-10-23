// Ajuda dos testes de tela do app: sobe o servidor REAL (app/server.py) em porta
// efemera via tests/js/serve_for_test.py e conversa com a API pelo fetch do node.
import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const AQUI = path.dirname(fileURLToPath(import.meta.url));
export const REPO = path.resolve(AQUI, '..', '..');

// ESM ignora NODE_PATH; createRequire usa os caminhos globais (NODE_PATH) do node.
export const require_ = createRequire(import.meta.url);

/**
 * Sobe um servidor. cfg: {root, brand, max_upload, doctor, test_mode}; env: variaveis
 * extras do processo do servidor (ex.: REEL_APP_FAKE_TRANSCRIBE). Devolve {base, url, token, root, parar}.
 */
export async function iniciarServidor(cfg, dirTmp, env = {}) {
  fs.mkdirSync(cfg.root, { recursive: true });
  const cfgPath = path.join(dirTmp, `srv-${process.hrtime.bigint()}.json`);
  fs.writeFileSync(cfgPath, JSON.stringify(cfg));
  const proc = spawn('python3', ['-I', path.join(AQUI, 'serve_for_test.py'), cfgPath],
    { stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, ...env } });
  let stderr = '';
  proc.stderr.on('data', (d) => { stderr += d; });
  const linha = await new Promise((resolve, reject) => {
    let buf = '';
    const t = setTimeout(() => reject(new Error('servidor nao subiu: ' + stderr)), 20000);
    proc.stdout.on('data', (d) => {
      buf += d;
      const i = buf.indexOf('\n');
      if (i >= 0) { clearTimeout(t); resolve(buf.slice(0, i)); }
    });
    proc.on('exit', (c) => { clearTimeout(t); reject(new Error(`servidor saiu (${c}): ${stderr}`)); });
  });
  const info = JSON.parse(linha);
  return {
    ...info, root: cfg.root,
    stderr: () => stderr,
    parar() { try { proc.stdin.end(); proc.kill('SIGTERM'); } catch { /* ja saiu */ } },
  };
}

/** Chamada a API com o token; devolve {status, json}. */
export async function api(srv, method, rota, body) {
  const headers = { 'X-Token': srv.token };
  let data;
  if (body !== undefined) {
    data = JSON.stringify(body);
    headers['Content-Type'] = 'application/json';
  }
  const r = await fetch(srv.base + rota, { method, headers, body: data });
  let json = null;
  try { json = await r.json(); } catch { /* sem corpo */ }
  return { status: r.status, json };
}

/** Espera ate cond() (async) ser verdadeira ou estoura o prazo. */
export async function esperar(cond, ms = 10000, passo = 50) {
  const fim = Date.now() + ms;
  for (;;) {
    const v = await cond();
    if (v) return v;
    if (Date.now() > fim) throw new Error('tempo esgotado esperando condicao');
    await new Promise((r) => setTimeout(r, passo));
  }
}

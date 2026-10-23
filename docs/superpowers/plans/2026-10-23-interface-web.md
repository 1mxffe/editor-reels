# Interface web do Editor de Reel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um app no navegador, aberto com dois cliques no Mac, que leva um vídeo bruto ao Reel final e à capa (8 passos), com um banco extensível de estilos e efeitos, sem terminal e sem Claude Code.

**Architecture:** Servidor HTTP local em Python (biblioteca padrão) que expõe uma API JSON e serve uma página estática (HTML/CSS/JS puros, duas colunas: player à esquerda, painel do passo à direita). Tarefas longas rodam os scripts existentes de `scripts/` como subprocessos. O "banco" em `banco/` guarda paletas, legendas e efeitos como pastas com manifesto.

**Tech Stack:** Python ≥ 3.11 (stdlib: `http.server`, `subprocess`, `threading`, `json`), HTML/CSS/JS sem framework, ffmpeg, Chromium via node Playwright (já usado por `graphics.py`/`cover_compose.py`), pytest, node Playwright para testes de tela.

**Spec:** `docs/superpowers/specs/2026-10-23-interface-web-design.md`

## Decisão de plano (desvio do spec)

O spec previa um adaptador "HTTP" em `review/review.html`. Aqui a tela **Cortes** implementa o
clique nas palavras de forma nativa em `app/web/passos/cortes.js` (com a matemática de
`originalToCutTime` portada, e teste de paridade), porque o layout de duas colunas com player
fixo não cabe na página de revisão. `review/review.html` **não é alterada** e continua
valendo para o fluxo do Claude Code. O spec ganha essa nota na T15.

## Global Constraints

- Sem dependências novas em Python nem em JS (nada de Flask, npm install de pacotes de UI).
- Python ≥ 3.11; scripts rodam com `python3 -I`; o servidor também (`python3 -I app/server.py`); arquivos em `app/` que importam irmãos começam com `sys.path.insert(0, str(Path(__file__).resolve().parent))`; `app/` importa os scripts como subprocessos, nunca por import (exceto `projects.py` que lê JSON).
- Servidor só em `127.0.0.1`, porta livre; toda chamada `/api/*` exige o cabeçalho `X-Token` igual ao token da subida; recusa `Host` diferente de `127.0.0.1:<porta>`/`localhost:<porta>` e `Origin` externa; sem CORS.
- Caminhos só a partir de slug `[a-z0-9-]{1,40}` dentro de `projects/`; recusar `..`, links simbólicos que saiam da pasta e arquivos fora da lista `entrada.*`, `saida/*`, `capa/*`, `materiais/*`, `quadros/*`.
- Nada de `shell=True`; argumentos sempre em lista; erros viram `{"erro": "<mensagem em português>"}` e nunca traceback.
- Texto do usuário na página só por `textContent`; CSP sem rede (`default-src 'self'`; `connect-src 'self'`).
- Uma tarefa por projeto por vez; 4 GB de limite de upload (configurável); upload em streaming.
- Interface em português do Brasil; tokens da marca (`#001931`, `#ddebf5`, `#a8c8f0`), Poppins de `assets/fonts/`; layout funciona a 375 px sem rolagem horizontal; foco visível; sem emoji como ícone; `lang="pt-BR"`.
- Legendas: sempre **estáticas por frase**, sem pop-up e sem animação por palavra (fade ≤ 150 ms).
- Sem `estilo.json`, `render`/`graphics`/`cover_compose` produzem **exatamente** o resultado atual (a suíte existente, ≈ 469 testes, continua passando).
- Commits: mensagem curta em português, terminando com a linha `Claude-Session: https://claude.ai/code/session_01XGnNogbp62aoej3Hsos544`; sem nome de modelo nem `Co-Authored-By`.

## Review Focus

- Upload de arquivo que não é vídeo (texto renomeado `.mp4`, vazio, enorme): recusar com mensagem clara e sem deixar arquivo parcial. → T3
- Duas tarefas no mesmo projeto (duplo clique em "Gerar preview"): a segunda recebe "já há uma tarefa em andamento". → T4
- Slug/nome de arquivo malicioso na URL (`..%2f`, links simbólicos, barra invertida, nomes longos): 404/400, nunca fora de `projects/`. → T2, T3
- Fechar a aba com tarefa rodando e reabrir: a tarefa e o log continuam disponíveis; o servidor só se encerra após o tempo sem página e sem tarefas. → T4, T8
- Item de banco com manifesto inválido ou efeito que não renderiza: não aparece e a instalação diz qual pasta e por quê; o app continua abrindo. → T10, T12
- `estilo.json` corrompido ou com valores fora do catálogo: recusado com mensagem; render usa defaults. → T11
- Porta ocupada / segunda instância do app: a segunda abre a mesma página em vez de falhar. → T8

## File Structure

```
Abrir Editor.command            duplo clique (macOS): acha python3 ≥ 3.11, sobe o servidor, abre o Chrome
app/server.py                   HTTP: roteamento, token, Host/Origin, estáticos, JSON, Range, upload
app/projects.py                 slugs, caminhos permitidos, estado das etapas de cada projeto
app/jobs.py                     tarefas em segundo plano (subprocesso, log, cancelar, uma por projeto)
app/tarefas.py                  monta o argv de cada tipo de tarefa a partir do projeto e do estilo
app/web/index.html, app.css     casca: duas colunas, barra de passos, player
app/web/app.js                  cliente da API, roteamento de passos, utilitários (el(), toast, erro)
app/web/passos/*.js             uma tela por passo (video, cortes, legendas, estilo, preview, graficos, capa, final, instalacao)
scripts/banco.py                carrega/valida banco/, lista itens, quadro de exemplo
scripts/estilo.py               valida estilo.json, defaults, resolve paleta/fonte/legenda
banco/paletas|legendas|efeitos|materiais/   itens do banco (manifesto.json [+ efeito.html])
tests/test_app_*.py             API
tests/js/app_*.mjs              fluxo na tela (Chromium)
COMO-USAR.md                    passo a passo em português simples
```

---

## ENTREGA A — App base: Vídeo → Cortes → Legendas → Preview → Final

### Task 1: Projetos (`app/projects.py`)

**Files:** Create `app/projects.py`, `tests/test_app_projects.py`

**Interfaces:**
- Produces: `slugify(name: str) -> str` (minúsculas, sem acento, `-`, ≤ 40, vazio ⇒ `ProjectsError`); `class ProjectsError(Exception)`; `class Projects` com `__init__(self, root: Path)` (root = pasta `projects/`), `list() -> list[dict]` (`{"slug","nome","criado"}` mais recentes primeiro), `create(name: str) -> dict` (cria a pasta; slug repetido ganha `-2`, `-3`), `path(slug: str) -> Path` (valida o padrão e que a pasta existe), `state(slug: str) -> dict` com `{"slug","nome","duracao": float|None,"etapas": {"video","transcricao","cortes","legendas","estilo","preview","graficos","capa","final": "pendente"|"pronto"},"arquivos": {...}}` calculado por arquivos presentes (`entrada.*`, `transcricao.json`, `cortes.json`, `legendas.json`, `estilo.json`, `saida/preview.mp4`, `graficos.json`, `capa/capa.png`, `saida/final.mp4`), `resolve_file(slug: str, rel: str) -> Path` (só `entrada.*`, `saida/*`, `capa/*`, `materiais/*`, `quadros/*`; sem `..`, sem link simbólico para fora; `ProjectsError` caso contrário).

- [ ] **Step 1:** Testes: `test_slugify_accents_and_symbols` ("Isenção de IR — 3 mitos!" → `isencao-de-ir-3-mitos`), `test_slugify_empty_raises`, `test_create_duplicate_gets_suffix`, `test_path_rejects_bad_slug` (`../x`, `A_b`, 41 chars, barra invertida), `test_resolve_file_allowlist`, `test_resolve_file_rejects_traversal_and_symlink_out`, `test_state_steps_follow_files`.
- [ ] **Step 2:** Rodar → FAIL (`python3 -m pytest tests/test_app_projects.py -q`).
- [ ] **Step 3:** Implementar `app/projects.py`; o nome original fica em `projects/<slug>/projeto.json` (`{"nome","criado"}`, escrita atômica via a lógica de `scripts/common.py`: copiar a função `atomic_write` por import de `sys.path` do repositório não é permitido — reutilizar chamando `scripts/common.py` como módulo importado de `scripts/` adicionado ao `sys.path` em `app/projects.py`).
- [ ] **Step 4:** PASS. **Step 5:** Commit `Projetos do app: slug, caminhos permitidos e estado das etapas`.

### Task 2: Servidor HTTP base (`app/server.py`)

**Files:** Create `app/server.py`, `app/web/index.html` (placeholder mínimo), `tests/test_app_server.py`

**Interfaces:**
- Consumes: `Projects` (T1).
- Produces: `make_server(root: Path, token: str, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer` (atributo `server.app` com `projects`, `jobs`, `token`, `root`); `Handler` com `json_reply(status, obj)`, `error(status, msg)`; rotas estáticas `GET /` e `GET /static/<arquivo de app/web>`; `GET /api/ping` → `{"ok": true}`; helper de teste `client(server)` em `tests/conftest_app.py` (http.client com token). Cabeçalhos de segurança em toda resposta: `Content-Security-Policy: default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; style-src 'self' 'unsafe-inline'`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store`.

- [ ] **Step 1:** Testes: `test_api_requires_token` (sem/errado ⇒ 401 `{"erro"}`), `test_host_header_must_match` (`Host: evil.com` ⇒ 403), `test_origin_external_rejected`, `test_static_only_from_web_dir` (`/static/../server.py` ⇒ 404), `test_security_headers_present`, `test_unknown_route_404_json`, `test_binds_loopback_only` (`server.server_address[0] == "127.0.0.1"`), `test_errors_never_traceback` (exceção forçada ⇒ 500 com `{"erro"}` sem "Traceback").
- [ ] **Step 2:** FAIL. **Step 3:** Implementar `make_server`/`Handler`; token comparado com `hmac.compare_digest`; `main()` fica para T8. **Step 4:** PASS. **Step 5:** Commit `Servidor local com token, Host/Origin e CSP`.

### Task 3: API de projetos, upload, arquivos e doctor

**Files:** Modify `app/server.py`, `scripts/doctor.py` (adiciona `--json`); Create `app/instalacao.py`, `tests/test_app_projects_api.py`; Modify `tests/test_doctor.py`

**Interfaces:**
- Consumes: T1, T2; `scripts/doctor.py::check() -> tuple[str, list[dict]]` (itens `{"name","ok","required","detail"?}`).
- Produces: `GET /api/projects`, `POST /api/projects {"nome"}` → 201 projeto; `GET /api/projects/<slug>` (= `state`); `PUT /api/projects/<slug>/video` (corpo = bytes do vídeo, cabeçalho `X-Filename`; streaming para `projects/<slug>/entrada.<ext>.tmp` e depois `os.replace`; extensões `.mp4 .mov .m4v .webm .mkv`; checa com `ffprobe` que há stream de vídeo e duração > 0, senão apaga o `.tmp` e responde 400 "o arquivo não parece ser um vídeo"; limite `MAX_UPLOAD` (4 GB, `make_server(max_upload=…)`) ⇒ 413); `GET /api/projects/<slug>/arquivos/<rel>` (via `resolve_file`; `Range: bytes=a-b` ⇒ 206 com `Content-Range`, `Accept-Ranges: bytes`; tipos MIME por extensão); `GET /api/doctor` → `{"estado","itens":[{"id","nome","ok","opcional","mensagem","comando"}]}` com texto em português (mapa em `app/instalacao.py`); `doctor.py --json` imprime a mesma lista em JSON sem mudar a saída padrão nem o código de saída; `GET/PUT /api/brand` (`{"handles": [..]}` valida e grava com `brand.set_handles`; GET devolve `handles` e se a marca está completa).

- [ ] **Step 1:** Testes: `test_create_and_list_projects`, `test_upload_valid_video_atomic` (vídeo do `make_sample`; existe `entrada.mp4`, sem `.tmp`), `test_upload_text_renamed_mp4_rejected_no_leftover`, `test_upload_empty_rejected`, `test_upload_over_limit_413_no_leftover`, `test_upload_bad_extension`, `test_file_range_206_and_416` (intervalos válidos, inválido, aberto `bytes=100-`), `test_file_allowlist_via_api` (`../` e `projeto.json` ⇒ 404), `test_doctor_translated_items`, `test_doctor_json_flag_matches_default_exit_code` (em `tests/test_doctor.py`), `test_brand_handles_roundtrip_and_validation`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar (upload: ler em blocos de 1 MiB e contar bytes; `ffprobe -v error -select_streams v:0 -show_entries stream=codec_type:format=duration -of json`). **Step 4:** PASS (também `tests/test_doctor.py` completo). **Step 5:** Commit `API de projetos, upload, arquivos com Range, doctor em português e @`.

### Task 4: Tarefas em segundo plano (`app/jobs.py`, `app/tarefas.py`)

**Files:** Create `app/jobs.py`, `app/tarefas.py`, `tests/test_app_jobs.py`; Modify `app/server.py`

**Interfaces:**
- Produces: `class JobBusy(Exception)`; `class Jobs` com `__init__(self, root: Path)`, `start(slug: str, tipo: str, argv: list[str], cwd: Path, saidas: list[str] = ()) -> str` (levanta `JobBusy` se o projeto já tem tarefa `rodando`), `get(job_id: str) -> dict` (`{"id","slug","tipo","estado": "rodando"|"ok"|"erro"|"cancelado","mensagem","log": list[str] (últimas 200 linhas),"inicio","fim","saidas": list[str]}`), `cancel(job_id: str) -> bool` (SIGTERM, depois SIGKILL em 5 s), `ativo_em(slug) -> str | None`, `recentes(slug) -> list[dict]`; estado em `projects/<slug>/.tarefa-<id>.json` para sobreviver ao reload da página (não ao reinício do servidor: jobs `rodando` órfãos viram `erro` "interrompida" ao subir). `tarefas.argv(tipo: str, project: Path, **opcoes) -> list[str]`: `transcrever` → `[sys.executable, "-I", scripts/transcribe.py, entrada, transcricao.json]`, `cortes` → `cut.py detect`, `preview`/`final` → `render.py <project> preview|final`, `capa-candidatos` → `cover_frames.py video|photo …`, `capa` → `cover_compose.py …`, `instalar-chromium` → `npm i -g playwright` e `npx playwright install chromium` encadeados num único subprocesso `sh -c` **sem entrada do usuário** (argv fixo). Rotas: `POST /api/projects/<slug>/jobs/<tipo>` (corpo com opções validadas por tipo) → 202 `{"job_id"}`; 409 se `JobBusy`; `GET /api/jobs/<id>`; `POST /api/jobs/<id>/cancelar`.
- Mensagem de erro do job = a linha `erro: …` do stderr do script (os scripts já usam essa convenção), sem traceback.

- [ ] **Step 1:** Testes (com um "script" Python de teste no lugar dos reais, injetado via `tarefas.argv` monkeypatch): `test_job_ok_collects_log_and_outputs`, `test_job_error_message_from_stderr_line`, `test_second_job_same_project_busy_409`, `test_jobs_in_different_projects_run_in_parallel`, `test_cancel_kills_process_tree`, `test_job_state_survives_new_Jobs_instance_for_finished`, `test_orphan_running_job_marked_error_on_start`, `test_argv_is_list_no_shell` (nenhum `shell=True`: inspeção do `subprocess.Popen` mockado), `test_option_validation_rejects_unknown_keys`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar com `subprocess.Popen(..., stdout=PIPE, stderr=STDOUT, text=True, start_new_session=True)` e thread leitora do log. **Step 4:** PASS. **Step 5:** Commit `Tarefas em segundo plano: uma por projeto, log, cancelar`.

### Task 5: API de cortes, legendas e render

**Files:** Modify `app/server.py`; Create `app/revisao_api.py`, `tests/test_app_revisao.py`

**Interfaces:**
- Consumes: `scripts/review_apply.py` (`build_review(project) -> dict`, `apply(project, decisions: dict)`, `ReviewError`), `scripts/cut.py detect`.
- Produces: `GET /api/projects/<slug>/revisao` → `review_apply.build_review` (words, cuts, phrases, notes, graphics, kept_duration); `PUT /api/projects/<slug>/revisao` com as `decisions` de `review_apply` (`cuts_removed`, `cuts_added`, `caption_edits {idx: {text, base_text}}`, `graphics`, `notes`) → aplica e devolve o `build_review` novo; `ReviewError` ⇒ 400 `{"erro"}`. `app/revisao_api.py` chama `scripts/review_apply.py` por **subprocesso** (`apply` e `build`, mesmos argv do SKILL) para não importar o motor; resposta traz o `review.json` regerado. Etapa "cortes" fica `pronto` quando existe `cortes.json`; "legendas" quando `legendas.json` ou o usuário confirma (`PUT …/etapas/legendas {"confirmado": true}` grava `projects/<slug>/etapas.json`).

- [ ] **Step 1:** Testes (projeto sintético + transcrição fixa de `tests/fixtures_app.py`): `test_revisao_build_matches_script_output`, `test_put_cut_removed_then_build_reflects`, `test_put_caption_edit_pinned_to_base_text_mismatch_400`, `test_put_idempotent_twice_same_decisions`, `test_put_invalid_decisions_400_no_traceback`, `test_legendas_confirm_marks_step`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Commit `API de cortes e legendas por review_apply`.

### Task 6: Casca da página e telas de Instalação e Vídeo

**Files:** Create `app/web/index.html`, `app/web/app.css`, `app/web/app.js`, `app/web/passos/instalacao.js`, `app/web/passos/video.js`, `tests/js/app_shell.mjs`, `tests/test_app_ui_shell.py`

**Interfaces:**
- Produces (JS): `api(method, path, body?) -> Promise<json>` (manda `X-Token` lido de `window.__TOKEN__`, injetado pelo servidor em `index.html`; lança `Erro` com `.mensagem`); `el(tag, props, ...filhos)` (sempre `textContent`); `toast(msg, tipo)`; `registrarPasso({id, titulo, render(container, ctx)})`; `ctx = {slug, estado, player, api, ir(passoId), atualizar()}`; layout `#coluna-player` (vídeo vertical com Play/Pause, −5 s, +5 s e tempo) e `#painel`; barra `#passos` com estado (pendente/andamento/pronto), passos bloqueados até o anterior estar pronto, sem perder o que já foi feito ao voltar; `localStorage` só para o último projeto.
- Tela **Instalação**: lista de `GET /api/doctor` (✔/✘ em texto, não emoji), o comando copiável (botão "Copiar"), botão **Instalar Chromium** (tarefa `instalar-chromium`) quando faltar; primeira execução pede o `@` (campo, validação do servidor, mensagem de erro dele).
- Tela **Vídeo**: criar/abrir projeto, arrastar/soltar, barra de envio (XHR com `upload.onprogress`), duração e formato detectados; erro do servidor exibido por extenso.

- [ ] **Step 1:** Teste de tela (node Playwright, servidor real em porta efêmera via `tests/js/helpers.mjs`): `test_shell_two_columns_and_stepper`, `test_steps_locked_until_previous_ready`, `test_install_screen_lists_items_and_handle_form`, `test_video_upload_progress_and_error_message`, `test_no_horizontal_scroll_375`, `test_all_text_via_textcontent` (um nome de projeto `<img onerror>` fica inerte), `test_csp_blocks_external_request`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar a página (carregar a skill `artifact-design` para o visual; Poppins via `@font-face` apontando para `/static/fonts/` servido de `assets/fonts/`; tema claro/escuro por `prefers-color-scheme`). **Step 4:** PASS. **Step 5:** Commit `Casca da página: passos, player, instalação e envio do vídeo`.

### Task 7: Telas Cortes, Legendas, Preview e Final

**Files:** Create `app/web/passos/cortes.js`, `legendas.js`, `preview.js`, `final.js`, `tests/js/app_flow_a.mjs`, `tests/test_app_ui_flow_a.py`

**Interfaces:**
- Consumes: T4 (tarefas), T5 (`/revisao`), `originalToCutTime(t, cortesAtivos)` portada de `review/review.html` (mesma matemática; teste de paridade em T7).
- Produces: **Cortes:** botão Transcrever → tarefa `transcrever` (na 1ª vez avisa "baixa o modelo de voz"), depois `cortes`; lista de cortes com ligar/desligar (envia `cuts_removed`/`cuts_added`), tempo economizado, palavras clicáveis (clicar fora de corte corta a palavra; dentro restaura); progresso e log "Detalhes" recolhível; botão Cancelar. **Legendas:** frases editáveis (≤ 2 linhas, mostra o aviso de `\ { }` vindo do servidor), envia `caption_edits` com `base_text`; "Confirmar legendas". **Preview:** "Gerar preview" (tarefa `preview`), player com `saida/preview.mp4`; notas com marca de tempo (`notes`). **Final:** "Gerar versão final" (tarefa `final`), player, botão "Abrir pasta" (`POST …/abrir-pasta` → `open` no macOS, `xdg-open` no Linux; teste usa duplo) e lista de arquivos prontos.

- [ ] **Step 1:** Testes de tela com transcrição fixa no lugar do Whisper (`tests/fixtures_app.py::fake_transcribe_script` injetado por variável `REEL_APP_FAKE_TRANSCRIBE=1` aceita **apenas** quando o servidor sobe com `make_server(..., test_mode=True)`): `test_cuts_flow_toggle_and_time_saved`, `test_word_click_cut_and_restore`, `test_original_to_cut_time_parity_with_review_html`, `test_caption_edit_pinned_and_error_shown`, `test_preview_generates_and_plays` (arquivo 540x960 via ffprobe), `test_final_1080x1920`, `test_cancel_running_job_ui`, `test_reload_keeps_running_job`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS (`node tests/js/app_flow_a.mjs` via pytest). **Step 5:** Commit `Telas de cortes, legendas, preview e final`.

### Task 8: Lançador, encerramento automático e COMO-USAR

**Files:** Create `Abrir Editor.command`, `COMO-USAR.md`, `tests/test_app_launch.py`; Modify `app/server.py` (`main`), `README.md`

**Interfaces:**
- Produces: `python3 -I app/server.py [--porta N] [--sem-navegador]`: sobe o servidor, grava `projects/.app.json` (`{"porta","token","pid"}`), imprime a URL `http://127.0.0.1:<porta>/?t=<token>`, abre o Chrome (`open -a "Google Chrome" <url>`; se não houver Chrome, o navegador padrão); `POST /api/heartbeat` chamado a cada 10 s pela página; o servidor encerra após 120 s sem heartbeat **e** sem tarefa rodando; segunda instância detecta `projects/.app.json` válido (pid vivo e porta respondendo `/api/ping`) e só reabre a mesma URL. `Abrir Editor.command` (executável): `cd` para a pasta do script, usa `python3` do `PATH` se ≥ 3.11, senão `/opt/homebrew/opt/python@3.13/libexec/bin/python3`, senão mostra mensagem em português com o que instalar e espera Enter; roda o servidor. `COMO-USAR.md` (português simples): instalação com os passos reais do Mac da equipe (Homebrew, `brew install python@3.13 ffmpeg node git`, `PATH`, `pip install --break-system-packages -r requirements.txt`), como abrir, os 8 passos, onde ficam os arquivos, o que fazer se algo falhar.

- [ ] **Step 1:** Testes: `test_server_main_prints_url_with_token_and_writes_app_json`, `test_second_instance_reuses_first`, `test_auto_shutdown_after_idle_no_jobs`, `test_no_shutdown_while_job_running`, `test_stale_app_json_ignored`, `test_command_file_is_executable_and_mentions_python_fallback`, `test_open_browser_prefers_chrome` (comando montado, sem executar).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Commit `Lançador de dois cliques, encerramento por inatividade e COMO-USAR`.

---

## ENTREGA B — Gráficos e Capa na tela

### Task 9: API e telas de Materiais, Gráficos e Capa

**Files:** Modify `app/server.py`, `app/tarefas.py`; Create `app/web/passos/graficos.js`, `capa.js`, `tests/test_app_graficos_capa.py`, `tests/js/app_flow_b.mjs`

**Interfaces:**
- Consumes: `scripts/graphics.py` (`validate`, `load_cards`, `render_card`), `scripts/cover_frames.py` CLI, `scripts/cover_compose.py` CLI, `scripts/brand.py`.
- Produces: `GET/PUT /api/projects/<slug>/materiais` (lista; `PUT` arquivo por streaming para `materiais/<nome sanitizado>`: png/jpg/webp/svg/mp4; recusa outros tipos; mesma sanitização de nomes que `review/review.html`); `GET/PUT /api/projects/<slug>/graficos` (lê/grava `graficos.json`; a validação de cada card roda por subprocesso no subcomando novo `scripts/graphics.py validar <graficos.json> <projeto>`, que imprime `ok` ou `erro: …` com exit 0/1); tarefas `capa-candidatos` (corpo `{"modo": "video"|"foto", "foto"?: "materiais/…"}`) e `capa` (corpo `{"quadro": "capa/candidato-2.png", "gancho", "area"?, "subtitulo"?}` → `cover_compose.py`; erros do script, como "gancho não cabe em 2 linhas", chegam por extenso); `GET …/arquivos/capa/*`. Telas: **Gráficos** (lista de cards, formulário título ≤ 60/texto ≤ 140/momento/duração, imagem dos materiais, manter/remover; aba Materiais com envio e remoção) e **Capa** (3 candidatos com "Escolher este quadro" — o usuário escolhe o sorriso, a tela diz que **não há detecção de sorriso**; campos gancho/área/subtítulo; botão "Gerar capa"; imagem pronta ao lado; aviso se o `@` não estiver salvo, levando à Instalação).

- [ ] **Step 1:** Testes: `test_materials_upload_whitelist_and_sanitized_name`, `test_materials_rejects_traversal_and_big_svg_script_kept_inert`, `test_graficos_put_validates_each_card`, `test_graficos_validar_subcommand_exit_codes` (em `tests/test_graphics.py`), `test_capa_candidatos_job_produces_three_png`, `test_capa_job_error_message_hook_too_long`, `test_capa_needs_handle_message`; telas: `test_graphics_form_and_remove`, `test_cover_flow_select_frame_and_generate` (Chromium real, foto sintética), `test_cover_no_smile_detection_notice`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Commit `Materiais, gráficos e capa na tela`.

---

## ENTREGA C — Banco de estilos e efeitos + passo Estilo

### Task 10: Carregador do banco (`scripts/banco.py`) e itens de paletas e legendas

**Files:** Create `scripts/banco.py`, `banco/paletas/{marca,marinho-profundo,gelo-claro,grafite}/manifesto.json`, `banco/legendas/{faixa-azul,pilula-escura,duas-linhas-grandes,pequena-baixa-esquerda}/manifesto.json`, `banco/README.md`, `tests/test_banco.py`

**Interfaces:**
- Produces: `class BancoError(ValueError)`; `carregar(raiz: Path = REPO/"banco") -> Banco` com `Banco.itens(tipo: str) -> list[Item]`, `Banco.item(tipo: str, id: str) -> Item`, `Banco.erros -> list[dict]` (`{"pasta","motivo"}` de itens inválidos, que **não** entram na lista); `Item = {"id","tipo","nome","descricao","campos": list[Campo],"dados": dict,"pasta": Path}`; `Campo = {"id","rotulo","tipo": "texto"|"numero"|"imagem"|"cor"|"escolha","max"?,"min"?,"opcoes"?,"obrigatorio": bool}`. Manifesto: `{"nome","descricao","tipo","duracao"?:{"padrao","min","max"},"campos":[…],"dados":{…}}`. Paleta `dados` = `{"fundo","texto","destaque","apoio"}` (hex `#rrggbb`); legenda `dados` = `{"estilo": "faixa"|"pilula"|"duas-linhas"|"pequena","posicao_padrao": "baixo"|"meio","tamanho_padrao": "P"|"M"|"G"}`. CLI `python3 -I scripts/banco.py listar [--json]` e `validar` (exit 1 se houver erro).
- Valores: paleta **Marca** = `fundo #001931`, `texto #ddebf5`, `destaque #a8c8f0`, `apoio #566a7a`; **Faixa azul** = comportamento atual exato.

- [ ] **Step 1:** Testes: `test_loads_four_palettes_and_four_caption_styles`, `test_invalid_manifest_excluded_and_reported` (JSON quebrado, cor inválida, tipo desconhecido, `max` negativo, id ≠ nome da pasta, caminho com `..`), `test_field_types_validation`, `test_brand_palette_matches_brand_json_seed`, `test_cli_validar_exit_codes`, `test_id_is_folder_name_slug`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar (valida tudo no carregamento; nada de `eval`; `efeito.html` só é verificado quanto à existência aqui). **Step 4:** PASS. **Step 5:** Commit `Banco de estilos: carregador, paletas e legendas`.

### Task 11: `estilo.json`, legendas em quatro estilos e leitura no render

**Files:** Create `scripts/estilo.py`, `tests/test_estilo.py`; Modify `scripts/captions.py`, `scripts/render.py`, `scripts/graphics.py`, `scripts/cover_compose.py`, `tests/test_captions.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `banco.carregar`, `captions.to_ass(phrases, brand, size=(1080,1920))`, `render.render`.
- Produces: `estilo.DEFAULT = {"paleta": "marca", "fonte": "Poppins", "legenda": {"estilo": "faixa-azul", "posicao": "baixo", "tamanho": "M"}, "cards": {"estilo": "vidro"}}`; `estilo.carregar(project: Path) -> dict` (sem arquivo ⇒ DEFAULT; arquivo inválido ⇒ `EstiloError` com mensagem em português); `estilo.salvar(project: Path, dados: dict) -> None` (valida contra o banco, escrita atômica); `estilo.aplicar_marca(brand: dict, est: dict) -> dict` (devolve um `brand` efetivo com cores da paleta e `font_*` da fonte, **sem** mudar o arquivo `brand.json`); `captions.to_ass(phrases, brand, size=..., estilo: dict | None = None)`: `estilo=None` ⇒ saída idêntica byte a byte à atual; estilos: `faixa-azul` (atual), `pilula-escura` (caixa arredondada centralizada, fundo `fundo` a 85 %), `duas-linhas-grandes` (fonte maior, 2 linhas, sem caixa, contorno), `pequena-baixa-esquerda` (menor, alinhada à esquerda); `posicao` `baixo` (MarginV ≥ 340) | `meio`; `tamanho` P/M/G = ×0,85/×1/×1,2 — **todos sem tags de animação** além de `\fad(≤150,≤150)`; `render.render` lê `estilo.json` quando existe e passa o `estilo` a `captions.to_ass`, `brand` efetivo a graphics/cover.

- [ ] **Step 1:** Testes: `test_default_ass_byte_identical_to_golden` (arquivo dourado gerado do `HEAD` antes da mudança e commitado em `tests/golden/legenda_atual.ass`), `test_each_style_has_no_animation_tags` (sem `\t(`, `\k`, `\move`, `\fscx`, `\org`, `\clip`), `test_fade_at_most_150ms`, `test_bottom_position_respects_safe_area_340`, `test_size_scaling`, `test_estilo_missing_file_returns_default`, `test_estilo_invalid_json_message`, `test_estilo_unknown_item_rejected`, `test_aplicar_marca_does_not_write_brand_json`, `test_render_without_estilo_unchanged` (hash do `.ass` gerado), `test_render_with_estilo_uses_palette_font`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar; gerar o arquivo dourado **antes** de tocar em `captions.py` (passo 0: `python3 -I scripts/captions.py` com entrada fixa → `tests/golden/`). **Step 4:** PASS; suíte completa verde (`python3 -m pytest -q`). **Step 5:** Commit `Estilo da legenda e da marca por estilo.json, sem mudar o padrão atual`.

### Task 12: Efeitos do banco (10) e renderizador genérico

**Files:** Modify `scripts/graphics.py`, `scripts/js/render_card.mjs`; Create `banco/efeitos/<id>/{manifesto.json,efeito.html}` para: `card-destaque`, `numero-grande`, `pilula-destaque`, `selos`, `polaroides`, `circulo-a-mao`, `seta-a-mao`, `calendario`, `linha-do-tempo`, `palavra-destaque`; `tests/test_efeitos.py`

**Interfaces:**
- Consumes: `banco` (T10), pipeline de frames de `graphics.render_clip` (Chromium frame a frame → webm `yuva420p`).
- Produces: `graficos.json` aceita `{"id","efeito": "<id do banco>","campos": {…},"at","dur"}`; o formato atual `{"title","body","material",…}` continua válido e vale como `efeito="card-destaque"`; `graphics.validate` valida `campos` contra o manifesto (tipos, `max`, obrigatórios, imagens dentro do projeto/materiais); cada `efeito.html` expõe `window.setup(dados)` e `window.setTime(t)` (determinístico, sem rede, texto só por `textContent`, CSP sem rede); `graphics.inspect_effect(efeito_id, campos, brand, *, project, t) -> dict` (caixas medidas e o quadro PNG em `t`) para os testes e para os cartões do passo Estilo. Efeitos: entradas suaves (350 ms ease-out), saída 300 ms; `polaroides` aceita quadros do próprio vídeo (`campos.imagens` com `quadro:<segundo>` extraídos por `ffmpeg`); `circulo-a-mao`/`seta-a-mao` desenham o traço (SVG `stroke-dashoffset`); `palavra-destaque` é corte seco e exige `dur ≤ 2`; nenhum efeito cobre a faixa da legenda (y entre 1580 e 1920 livre) nem a área superior de 250 px.

- [ ] **Step 1:** Testes por efeito (parametrizados): `test_effect_renders_clip_with_alpha_and_duration`, `test_effect_text_inert_with_markup` (`<img onerror>` vira texto), `test_effect_respects_safe_areas` (caixas dentro de y ∈ [250, 1580]), `test_effect_entrance_and_exit_frames` (opacidade 0 → 1 → 0), `test_effect_field_limits_enforced`, `test_legacy_card_format_still_valid`, `test_polaroid_uses_video_frames`, `test_palavra_destaque_max_duration`, `test_broken_effect_html_excluded_with_reason` (efeito cujo `setTime` lança ⇒ fora do banco, com motivo em `Banco.erros`).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar o renderizador genérico (`render_card.mjs` carrega `efeito.html` do banco passado no job) e os 10 efeitos; olhar um quadro de cada efeito (Read) e ajustar até seguir o visual da marca. **Step 4:** PASS (cada teste com Chromium ≤ 5 s; total do arquivo ≤ 90 s). **Step 5:** Commit `Dez efeitos no banco e renderizador de efeitos`.

### Task 13: Quadros de exemplo e API do banco/estilo

**Files:** Modify `scripts/banco.py`, `app/server.py`; Create `app/estilo_api.py`, `tests/test_app_estilo.py`

**Interfaces:**
- Produces: `banco.quadro(project: Path, tipo: str, item_id: str, estilo: dict, t: float, out: Path) -> Path` (540x960 PNG: um quadro do vídeo do usuário no segundo `t` com o item aplicado — legenda via `captions` + `ffmpeg`, paleta via cores aplicadas num quadro com a legenda de exemplo e um card, efeito via `graphics.inspect_effect` composto sobre o quadro); cache em `projects/<slug>/quadros/<tipo>-<id>-<hash>.png`; API: `GET /api/banco` (`{"paletas":[…],"legendas":[…],"efeitos":[…],"erros":[…],"fontes":[{"nome","arquivo"}]}`; fontes = `assets/fonts/*.ttf` lidas pelo nome da família), `GET/PUT /api/projects/<slug>/estilo` (`PUT` valida com `estilo.salvar`; erro ⇒ 400), tarefa `quadros` (gera os cartões da aba pedida; devolve a lista de PNGs por `saidas`), tarefa `aplicar-estilo` (grava e roda `preview`). "mais parecido com este": `GET /api/banco/<tipo>/<id>/variacoes` devolve variações predefinidas do manifesto (`variacoes: [{nome, dados}]`), ordenadas pelo item escolhido primeiro.

- [ ] **Step 1:** Testes: `test_banco_endpoint_lists_items_and_errors`, `test_fontes_from_assets_dir`, `test_quadro_png_size_and_cache`, `test_quadro_each_tipo_renders`, `test_estilo_put_validates_against_banco`, `test_aplicar_estilo_runs_preview_with_estilo`, `test_variacoes_order_selected_first`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Commit `API do banco e do estilo com quadros de exemplo`.

### Task 14: Tela Estilo

**Files:** Create `app/web/passos/estilo.js`, `tests/js/app_flow_c.mjs`, `tests/test_app_ui_flow_c.py`; Modify `app/web/app.css`

**Interfaces:**
- Produces: abas **Paletas · Fontes · Legendas · Efeitos · Notas**; cada cartão = `<img>` do quadro de exemplo + nome + descrição; "Usar" marca um cartão por aba; "Mais parecido com este" reordena a aba; aba **Fontes** lista só as fontes do servidor e mostra o texto "para ter mais fontes, coloque o arquivo .ttf em assets/fonts/"; aba **Legendas** tem seletores de posição (baixo/meio) e tamanho (P/M/G); aba **Efeitos** adiciona efeitos ao vídeo (formulário gerado dos `campos` do manifesto, momento e duração) e grava em `graficos.json`; **Aplicar** → tarefa `aplicar-estilo` com barra de progresso, e o player à esquerda troca para o preview novo; itens inválidos do banco aparecem num aviso "N itens do banco não carregaram" com os motivos.

- [ ] **Step 1:** Testes de tela (Chromium; vídeo sintético; efeitos reais): `test_style_tabs_and_cards_render_with_example_frames`, `test_use_card_then_apply_changes_preview` (o `estilo.json` gravado e o preview tem a legenda do estilo), `test_more_like_this_reorders`, `test_effect_form_from_manifest_fields_and_limits`, `test_fonts_tab_lists_only_available_fonts`, `test_invalid_bank_items_notice`, `test_no_horizontal_scroll_375_style_step`, `test_card_text_inert`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar (olhar capturas 375x812 e 1280x800 nos dois temas). **Step 4:** PASS. **Step 5:** Commit `Tela Estilo com banco de opções`.

---

## ENTREGA D — Fechamento

### Task 15: Fluxo completo, documentação e suíte final

**Files:** Create `tests/js/app_full_flow.mjs`, `tests/test_app_full_flow.py`; Modify `README.md`, `.claude/skills/editor-reel/SKILL.md`, `COMO-USAR.md`, `docs/superpowers/specs/2026-10-23-interface-web-design.md` (nota "implementado")

**Interfaces:** nenhuma nova; consome tudo.

- [ ] **Step 1:** Teste de ponta a ponta na tela: criar projeto → enviar vídeo → transcrever (modo de teste) → cortes → legendas → Estilo (paleta, legenda, 1 efeito) → preview → capa (escolher quadro, gancho) → final; confere os arquivos (`saida/final.mp4` 1080x1920, `capa/capa.png` 1080x1920, `estilo.json`, `graficos.json`), sem erros no console e sem requisições de rede externas; `test_second_browser_tab_same_project_consistent`.
- [ ] **Step 2:** Rodar → FAIL onde faltar integração; corrigir apenas o que o teste apontar. **Step 3:** README (nova seção "Usar pela tela"), SKILL.md (uma linha dizendo que a tela existe e o SKILL continua válido), COMO-USAR final, nota no spec. **Step 4:** `python3 -m pytest -q` completo verde (conte e anote a duração). **Step 5:** Commit `Fluxo completo da interface, documentação e suíte final`.

# Editor de Reel Implementation Plan

> **2026-10-22 — decisão do escritório:** o checklist OAB foi removido do editor (revisão humana dupla antes da gravação); as seções sobre OAB abaixo estão superadas.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Skill local do Claude Code que transforma o vídeo bruto de um advogado em Reel 1080x1920 com cortes, legendas fixas na marca, checklist OAB bloqueante, página de revisão e capa.

**Architecture:** Scripts Python pequenos, cada um lê e grava arquivos JSON/vídeo dentro de `projects/<reel>/`; `ffmpeg` corta e queima legendas ASS; HyperFrames só renderiza gráficos animados (entrega 2). A skill `editor-reel` orquestra os scripts.

**Tech Stack:** Python 3.11+ (`-I`), pytest, ffmpeg, faster-whisper, Pillow, Node 22, HTML single-file (artefato), Figma MCP (opcional).

**Spec:** `docs/superpowers/specs/2026-10-21-editor-reel-design.md` · Marca: `brand/guia-visual.md`

## Global Constraints

- Saída de vídeo: 1080x1920, vertical; rascunho em 540x960.
- Legendas: por frase, estáticas, **sem animação de pop-up nem efeito por palavra**; fade ≤150 ms no máximo.
- `render` nunca roda sem `oab_check` aprovado; reprovação aponta o item.
- Cortes nunca apagam o original; `cortes.json` é reversível.
- Texto de tela, legenda e capa nunca citam número de lei ou artigo (`docs/formatos.md` do auto-copys); nada de promessa de resultado, urgência, captação, autoelogio; sem símbolo da OAB.
- Python sempre com `python3 -I`; scripts recebem caminhos por argumento.
- Cada script falha com código ≠ 0, mensagem clara e sem arquivo parcial (escrever em `.tmp` e renomear).
- Cores/fontes: `brand/brand.json` (semente em `brand/guia-visual.md` v1, medida no Figma POSTS-OUTUBRO): azul-marinho `#001931` dominante, degradê `#235587→#092744`, gelo `#f3f8fb`, texto `#ddebf5`; **Poppins em tudo** (serifada só no logotipo).
- Formatos: Reel rápido 12–15 s, Reel aprofundado 30–45 s.

## Review Focus

- Vídeo sem nenhuma fala/silêncio total → `cut` devolve cortes vazios e erro claro, não crash.
- Vídeo sem trilha de áudio → `transcribe` falha com mensagem, não trava.
- Transcrição com acento/emoji/aspas nas legendas → ASS escapa corretamente (`{`, `}`, `\`, `,`).
- `brand.json` ausente ou incompleto → `render` pede a entrevista de marca, não usa valores inventados.
- Vídeo de celular com rotação (metadado) ou VFR → saída continua 1080x1920 e áudio em sincronia.

## File Structure

```
.claude/skills/editor-reel/SKILL.md
references/{normas-oab.md,formatos-reel.md,legendas.md,capa.md}
brand/{guia-visual.md,brand.json}
scripts/{common.py,doctor.py,brand.py,oab_check.py,transcribe.py,cut.py,captions.py,render.py}
scripts/{review_apply.py,cover_frames.py,cover_compose.py}
review/review.html                      (entrega 2, artefato)
tests/{conftest.py,fixtures/,test_*.py}
projects/<reel>/                        (gitignored)
```

---

## ENTREGA 1 — Pipeline

### Task 1: Scaffold e `doctor`

**Files:** Create `scripts/common.py`, `scripts/doctor.py`, `tests/conftest.py`, `tests/test_doctor.py`, `.gitignore`, `requirements.txt`, `tests/fixtures/sample.mp4` (gerado por `tests/conftest.py::make_sample`)

**Interfaces:**
- Produces: `common.write_json_atomic(path: Path, data: dict) -> None`; `common.fail(msg: str, code: int = 1) -> NoReturn`; `common.run(cmd: list[str]) -> str`; `doctor.check() -> tuple[str, list[dict]]` com status em `{"READY","READY WITH LIMITS","MISSING"}` e itens `{"name","ok","required"}`.

- [ ] **Step 1:** Teste `test_doctor_ready_when_all_present`, `test_doctor_missing_ffmpeg_is_missing` (monkeypatch `shutil.which`), `test_doctor_whisper_missing_is_limits` (Whisper é opcional até a v1 estável).
- [ ] **Step 2:** `pytest tests/test_doctor.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3:** Implementar `doctor.check` verificando `ffmpeg`, `node`, import `faster_whisper`, espaço livre ≥ 10 GB; `main()` imprime lista com ✔/✘ e a última linha com o status.
- [ ] **Step 4:** `pytest tests/test_doctor.py -v` → PASS.
- [ ] **Step 5:** Fixture `make_sample`: 6 s de vídeo vertical com tom de áudio + 1 s de silêncio no meio, gerado por `ffmpeg lavfi`. Commit `feat: scaffold, common e doctor`.

### Task 2: Marca (`brand.py`)

**Files:** Create `scripts/brand.py`, `brand/brand.json`, `tests/test_brand.py`

**Interfaces:**
- Consumes: `common.write_json_atomic`.
- Produces: `brand.load(path: Path) -> dict` (lança `BrandMissing` se ausente/incompleto); `brand.REQUIRED = ["accent","bg","fg","muted","font_title","font_body","handles","caption_style"]`; `brand.seed_from_guide() -> dict` com `accent="#a8c8f0"`, `bg="#001931"`, `fg="#ddebf5"`, `muted="#566a7a"`, `font_title="Poppins"`, `font_body="Poppins"`, `handles=[]`, `caption_style="static-phrase"`.

- [ ] **Step 1:** Testes `test_load_missing_raises`, `test_load_incomplete_names_missing_keys`, `test_seed_has_all_required`, `test_handles_empty_blocks_cover_only` (handles vazio é válido para vídeo, inválido para capa).
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Implementar. **Step 4:** Rodar → PASS.
- [ ] **Step 5:** Commit `feat: brand.json e semente da marca`.

### Task 3: Checklist OAB (`oab_check.py`)

**Files:** Create `references/normas-oab.md` (cópia do auto-copys com aviso de origem), `scripts/oab_check.py`, `tests/test_oab_check.py`

**Interfaces:**
- Produces: `oab_check.check(texts: list[str]) -> list[Violation]` onde `Violation = {"rule": str, "text": str, "excerpt": str}`; `oab_check.RULES: dict[str, list[re.Pattern]]` com chaves `promessa_resultado`, `urgencia_sensacionalismo`, `captacao`, `autoelogio`, `numero_lei_artigo`, `simbolo_oab`.
- CLI: `python3 -I scripts/oab_check.py <textos.json>` sai 0 se limpo, 2 se houver violação (imprime regra e trecho).

- [ ] **Step 1:** Testes `test_clean_text_passes`; `test_promessa_resultado_blocked` ("garantimos que você ganha"); `test_urgencia_blocked` ("última chance", "corra"); `test_numero_lei_blocked` ("art. 7º", "Lei 8.213/91", "Lei nº 13.467"); `test_captacao_blocked` ("ligue agora e contrate"); `test_autoelogio_blocked` ("o melhor escritório"); `test_cli_exit_code_2`.
- [ ] **Step 2:** Rodar → FAIL.
- [ ] **Step 3:** Implementar com regex em português, insensível a caixa e acento; padrões derivados das 15 perguntas de `references/normas-oab.md`. Texto limpo não pode gerar falso positivo com "artigo" no sentido comum ("este artigo do blog" não é número de lei).
- [ ] **Step 4:** Rodar → PASS. **Step 5:** Commit `feat: checklist OAB bloqueante`.

### Task 4: Transcrição (`transcribe.py`)

**Files:** Create `scripts/transcribe.py`, `tests/test_transcribe.py`

**Interfaces:**
- Produces: `transcribe.transcribe(video: Path, out_json: Path, model: str = "small", lang: str = "pt") -> dict` com `{"duration": float, "words": [{"w": str, "start": float, "end": float}]}`; `transcribe.has_audio(video: Path) -> bool`.

- [ ] **Step 1:** Testes `test_has_audio_false_for_silent_video`, `test_no_audio_fails_clearly` (exit ≠ 0, mensagem cita "áudio"), `test_output_schema` com Whisper mockado (`monkeypatch` do `WhisperModel`).
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Implementar com `faster_whisper.WhisperModel(model).transcribe(..., word_timestamps=True)`; `has_audio` via `ffprobe`. **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: transcrição com tempo por palavra`.

### Task 5: Cortes (`cut.py`)

**Files:** Create `scripts/cut.py`, `tests/test_cut.py`

**Interfaces:**
- Consumes: transcrição de Task 4.
- Produces: `cut.detect(transcript: dict, min_gap: float = 0.5, fillers: set[str] = FILLERS) -> list[dict]` com itens `{"start","end","kind"}` (`kind ∈ {"silence","filler","repeat"}`); `cut.keep_segments(duration: float, cuts: list[dict]) -> list[tuple[float,float]]`; `cut.apply(video: Path, cuts: list[dict], out: Path) -> None` (ffmpeg `trim/atrim` + `concat`); `FILLERS = {"ãh","é","hum","tipo","né"}` (ver `references/formatos-reel.md`).

- [ ] **Step 1:** Testes `test_gap_over_threshold_is_silence`, `test_filler_word_is_cut`, `test_immediate_repeat_is_cut` ("a a empresa"), `test_keep_segments_complement`, `test_empty_cuts_keep_whole`, `test_apply_shortens_duration` (fixture: saída ≤ original − 0.8 s), `test_no_speech_returns_error`.
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Implementar; `cortes.json` guarda a lista (reversível — nunca altera `entrada`). **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat: detecção e aplicação de cortes`.

### Task 6: Legendas (`captions.py`)

**Files:** Create `references/legendas.md`, `scripts/captions.py`, `tests/test_captions.py`

**Interfaces:**
- Consumes: `brand.load`, transcrição já ajustada pelos cortes (tempos remapeados por `cut.keep_segments`).
- Produces: `captions.phrases(words: list[dict], max_chars: int = 38, max_lines: int = 2) -> list[dict]` (`{"text","start","end"}`); `captions.to_ass(phrases: list[dict], brand: dict, size=(1080,1920)) -> str`; `captions.remap(words, keep) -> list[dict]`.

- [ ] **Step 1:** Testes `test_phrase_max_two_lines`, `test_ass_has_no_animation_tags` (sem `\t(`, `\k`, `\move`, `\fscx` e escala); `test_ass_escapes_braces_and_backslash`; `test_fade_at_most_150ms` (`\fad(≤150,≤150)`); `test_font_and_color_from_brand`; `test_safe_area_margins` (`MarginV` ≥ 340).
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Implementar; cor ASS é BGR (`&H00BBGGRR`). **Step 4:** PASS. **Step 5:** Commit `feat: legendas estáticas por frase`.

### Task 7: Render (`render.py`)

**Files:** Create `scripts/render.py`, `tests/test_render.py`

**Interfaces:**
- Consumes: `oab_check.check`, `brand.load`, `captions.to_ass`, `cut.apply`.
- Produces: `render.render(project: Path, quality: Literal["preview","final"]) -> Path` (`saida/preview.mp4` 540x960 ou `saida/final.mp4` 1080x1920); lança `OabBlocked(violations)` antes de qualquer arquivo de saída.

- [ ] **Step 1:** Testes `test_blocked_text_creates_no_output`; `test_preview_resolution_540x960`; `test_final_resolution_1080x1920` (via `ffprobe`); `test_missing_brand_asks_interview`; `test_rotated_input_still_vertical` (fixture com `rotate=90`); `test_audio_in_sync` (duração do áudio ≈ do vídeo ±0.1 s).
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Implementar: ordem fixa `oab_check → brand.load → cut.apply → scale/pad 1080x1920 → subtitles=ass`; saída `.tmp` renomeada ao fim. **Step 4:** PASS. **Step 5:** Commit `feat: render com gate OAB`.

### Task 8: Skill `editor-reel` e fluxo ponta a ponta

**Files:** Create `.claude/skills/editor-reel/SKILL.md`, `references/formatos-reel.md`, `tests/test_e2e.py`, `README.md`

**Interfaces:** gatilhos "edit this into a reel" / "build preview" / "final"; a SKILL roda `doctor`, entrevista de marca (uma pergunta por vez, grava `brand.json`), `transcribe → cut → oab_check → captions → render`.

- [ ] **Step 1:** Teste `test_e2e_fixture_to_preview` (fixture → preview, duração menor, legenda sem animação) e `test_e2e_blocked_never_renders`.
- [ ] **Step 2:** Rodar → FAIL. **Step 3:** Escrever SKILL.md e `formatos-reel.md` (Reel rápido 12–15 s / aprofundado 30–45 s; avisar se o corte ficar fora da faixa). **Step 4:** `pytest -q` inteiro → PASS.
- [ ] **Step 5:** Commit `feat: skill editor-reel e e2e`.

---

## ENTREGA 2 — Revisão e materiais de apoio

### Task 9: Aplicar decisões da revisão (`review_apply.py`)

**Files:** Create `scripts/review_apply.py`, `tests/test_review_apply.py`

**Interfaces:**
- Produces: `review_apply.apply(project: Path, decisions: dict) -> None` com `decisions = {"cuts_removed": [id], "cuts_added": [{"start","end"}], "caption_edits": {idx: str}, "graphics": {id: "keep"|"drop"}, "notes": [{"t": float, "text": str}]}`; reescreve `cortes.json`/legendas, nunca o original.

- [ ] **Step 1:** Testes `test_restore_cut_removes_from_list`, `test_add_cut_from_word_click`, `test_caption_edit_passes_oab_again` (edição proibida bloqueia), `test_original_untouched`. **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Commit.

### Task 10: Página de revisão (`review/review.html`) com aba Materiais

**Files:** Create `review/review.html`, `references/revisao.md`, `tests/test_review_html.py`

**Interfaces:** artefato HTML único (tema claro/escuro, 16 px de gutter, mobile) lendo `projects/<reel>/review.json`; abas **Revisão** e **Materiais (opcional)**; Materiais aceita fotos, vídeos, ícones e inspirações (imagem ou link), gravando em `projects/<reel>/materiais/` + `materiais.json`. Vazio ⇒ o editor ignora a aba.

- [ ] **Step 1:** Teste (Playwright/Chromium já instalado) `test_tabs_render`, `test_empty_materials_is_valid`, `test_word_click_toggles_cut`, `test_no_horizontal_scroll_375px`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar (carregar `artifact-design` e `artifact-capabilities` antes). **Step 4:** PASS. **Step 5:** Commit.

### Task 11: Gráficos animados (HyperFrames)

**Files:** Create `scripts/graphics.py`, `references/graficos.md`, `tests/test_graphics.py`

**Interfaces:** `graphics.render_card(spec: dict, brand: dict, out: Path) -> Path` com `spec = {"title": str, "body": str|None, "at": float, "dur": float, "material": str|None}`; passa por `oab_check` e usa `material` quando existir; a fonte é HTML/CSS em Poppins; movimento ease-out 300–450 ms.

- [ ] **Step 1:** Testes `test_card_text_blocked_by_oab`, `test_card_uses_poppins`, `test_card_duration_matches_spec`. **Step 2:** FAIL. **Step 3:** Implementar com `npx hyperframes` (verificar versão no doctor). **Step 4:** PASS. **Step 5:** Commit.

---

## ENTREGA 3 — Capa

### Task 12: Candidatos de capa (`cover_frames.py`)

**Files:** Create `scripts/cover_frames.py`, `tests/test_cover_frames.py`

**Interfaces:** `cover_frames.candidates(video: Path, n: int = 3, out_dir: Path) -> list[Path]` — extrai frames nítidos (maior variância do Laplaciano via Pillow) com o rosto de frente; o usuário escolhe o sorriso; aceita também foto enviada.

- [ ] **Step 1:** Testes `test_returns_n_distinct_frames`, `test_skips_blurry_frames`, `test_accepts_uploaded_photo`. **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS. **Step 5:** Commit.

### Task 13: Composição da capa (`cover_compose.py`) + Figma

**Files:** Create `scripts/cover_compose.py`, `references/capa.md`, `tests/test_cover_compose.py`

**Interfaces:** `cover_compose.compose(photo: Path, title: str, brand: dict, out_png: Path) -> Path` (1080x1920, safe area, padrão do guia v1: logo no topo, retrato, degradê marinho, pill da área, gancho Poppins ExtraBold, subtítulo com última linha em azul-claro); roda `oab_check` no `title` e exige `brand["handles"]` não vazio; caminho Figma: a skill monta o frame no Figma via conector e, se o export falhar, usa esta versão HTML→PNG.

- [ ] **Step 1:** Testes `test_requires_handles`, `test_title_blocked_by_oab`, `test_output_size_1080x1920`, `test_no_oab_symbol`. **Step 2:** FAIL. **Step 3:** Implementar (HTML → PNG com Chromium). **Step 4:** PASS. **Step 5:** Commit.

### Task 14: Fechamento

- [ ] **Step 1:** `pytest -q` e `python3 -I scripts/doctor.py` → READY ou READY WITH LIMITS.
- [ ] **Step 2:** Revisão da branch inteira contra a spec; criar o repositório remoto `gutmannesilva-reel-editor` (depende de autorização — fora do escopo atual da sessão) e push.

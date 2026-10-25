# Editor de Reel — Gutmann & Silva

Ferramenta local que transforma um vídeo bruto de câmera falada em Reel
vertical (1080x1920): transcreve, sugere cortes de silêncio, muletas e
repetições, queima legendas estáticas por frase e renderiza preview ou versão
final. O escritório revisa o texto antes de gravar; a ferramenta não confere o
conteúdo do texto. Nada é publicado automaticamente.

## Interface (para quem não usa o Terminal)

Dois cliques em **`Abrir Editor.command`** abrem o editor no Google Chrome: uma
página com os passos Vídeo, Cortes, Legendas, Estilo, Preview, Gráficos, Capa e
Final, sem precisar do Claude Code. Instalação, uso e o que fazer se algo falhar,
em português simples: **[COMO-USAR.md](COMO-USAR.md)**.

Por baixo, o lançador roda `python3 -I app/server.py` (servidor só em
`127.0.0.1`, porta livre, chave de acesso no endereço `?t=`; `--porta N` fixa a
porta e `--sem-navegador` só imprime o endereço). Um segundo lançamento reabre a
mesma página (`projects/.app.json`); o servidor fecha sozinho 30 minutos depois de
a página parar de dar sinal, se nenhuma tarefa ou envio estiver em andamento.

## Requisitos

- Mac ou Linux
- Python 3.11 ou mais novo (`python3 --version`; o python3 que vem no macOS é 3.9:
  `brew install python@3.13`). O `doctor.py` roda em python antigo só para avisar isso.
- `ffmpeg` (com `ffprobe`); `node` só para cards de gráfico e capa automática
- Para cards de gráfico e capa automática (opcional): `npm i -g playwright`,
  `npx playwright install chromium`; os cards pedem também ffmpeg com `libvpx-vp9`
  (ver `references/graficos.md` e `references/capa.md`)
- `pip install -r requirements.txt` (faster-whisper para transcrição, Pillow, pytest;
  no Python do Homebrew: `pip install --break-system-packages -r requirements.txt`)

## Verificar o ambiente

```
python3 -I scripts/doctor.py
```

A última linha é `READY`, `READY WITH LIMITS` (falta item opcional, como o
faster-whisper, o Pillow e o node da capa ou o Chromium dos gráficos) ou `MISSING`
(python antigo, ou falta ffmpeg, ffprobe ou disco).

## Como usar com o Claude Code

Abra o Claude Code na raiz deste repositório, coloque o vídeo bruto na pasta e
peça "edit this into a reel". O skill `editor-reel`
(`.claude/skills/editor-reel/SKILL.md`) também responde a "build preview" e
"final" (pedir "final" é a aprovação do preview). Ele conduz doctor,
entrevista de marca (se `brand/brand.json` faltar), transcrição, cortes e render.
`python3 -I scripts/brand.py seed brand/brand.json` só cria o arquivo quando
ele está ausente, nunca sobre um arquivo existente (recusa sem `--force`).

## Estrutura

```
Abrir Editor.command                  lançador de dois cliques (Mac); ver COMO-USAR.md
app/                                  servidor local (server.py, jobs.py, projects.py) e página (web/)
.claude/skills/editor-reel/SKILL.md   procedimento do skill
brand/                                guia-visual.md e brand.json
references/                           formatos-reel.md, legendas.md, graficos.md, revisao.md, capa.md
review/review.html                    página de revisão (abrir do disco; lê e grava a pasta do projeto)
scripts/                              doctor, brand, transcribe, cut, captions, graphics, render, review_apply, cover_frames, cover_compose
assets/logo.webp                      logotipo do escritório (origem em references/capa.md)
scripts/js/                           card.html + render_card.mjs (cards) e cover.html + render_cover.mjs (capa), desenhados no Chromium
tests/                                pytest (tests/js: driver Playwright da página de revisão)
projects/<reel>/                      entrada.<ext>, transcricao.json, cortes.json, graficos.json, review.json, decisions.json, materiais/, capa/, saida/ (ignorado pelo git)
```

Fontes: `assets/fonts/` traz só `Poppins-Bold.ttf` (fornecida pelo escritório; licença
SIL OFL). As legendas usam Bold e já saem em Poppins; cards e capa usam o mesmo arquivo
para todos os pesos (títulos e texto corrido ficam em Bold). Para o desenho exato da
marca, acrescente `Poppins-Regular.ttf`, `Poppins-SemiBold.ttf` e `Poppins-ExtraBold.ttf`
(também SIL OFL: podem ser versionados); o código já os procura nessa pasta.
`cut.py apply` e a CLI de `captions.py` são uso interno/depuração (vídeo sem
legenda nem cards, ou só o ASS); o Reel sai só pelo `render.py`.

Códigos de saída de todas as CLIs: 0 ok; 1 erro (mensagem `erro: ...`, nada
gravado pela metade).

Testes: `python3 -m pytest -q` (a suíte inteira leva alguns minutos).

## Roteiro

1. **Entrega 1 (pronta):** transcrição, cortes, legendas, render preview e final, skill.
2. **Entrega 2 (pronta):** revisão em página (`review/review.html`, ver `references/revisao.md`), aba de materiais de apoio e cards de gráfico animados (`references/graficos.md`), mantidos ou descartados na revisão.
3. **Entrega 3 (pronta):** capa do Reel. Candidatos (`scripts/cover_frames.py`: quadros nítidos do vídeo ou foto enviada; o usuário escolhe o sorriso) e composição 1080x1920 com logotipo, gancho, subtítulo e @ (`brand.py set-handles` grava o @). Caminho preferido: duplicar o frame `272:2` do Figma `POSTS-OUTUBRO` pelo conector (exige o conector autorizado e acesso de edição); sem Figma, `scripts/cover_compose.py` gera o PNG no mesmo padrão. Ver `references/capa.md`.

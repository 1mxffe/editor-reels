---
name: editor-reel
description: Edita em Reel vertical (1080x1920) um vídeo bruto de câmera falada do escritório Gutmann & Silva — transcreve, detecta cortes de silêncio, muletas e repetições, queima legendas estáticas por frase, sobrepõe cards de gráfico quando ajudam e renderiza preview ou versão final. Use quando o usuário colocar um vídeo bruto na pasta e pedir para editá-lo em Reel ("edit this into a reel", "editar em reel"), ou disser "build preview", "montar preview", "final" ou "versão final".
---

# Editor de Reel — Gutmann & Silva

Procedimento completo. Roda a partir da raiz do repositório; todo Python com
`python3 -I`. Formatos e zona segura em `references/formatos-reel.md`; regras de
legenda em `references/legendas.md`; cards de gráfico em `references/graficos.md`.

Existe também uma tela (`Abrir Editor.command`, ver `COMO-USAR.md`) que faz o mesmo
fluxo sem o Claude Code; este procedimento continua válido para quem edita pelo Claude Code.

## Regras que não mudam

- **O texto é do escritório.** O escritório revisa o texto antes de gravar;
  esta ferramenta não confere regras da OAB. Fala, legendas, cards e capa saem
  como o usuário aprovou.
- **Legendas estáticas, por frase.** Sem pop-up, sem efeito palavra a palavra
  (fade de até 150 ms apenas).
- **Cortes são reversíveis.** O original `entrada.<ext>` nunca é alterado; os
  cortes vivem em `cortes.json` e podem ser editados e re-aplicados.
- **Marca só de `brand/brand.json`.** Cores, fontes e @ vêm de lá. Nunca invente
  valor de marca; se faltar, faça a entrevista.

## Antes de começar

Rode `python3 -I scripts/doctor.py` e aja sobre a última linha. Os scripts pedem
**Python 3.11 ou mais novo** (o python3 que vem no macOS é 3.9: `brew install
python@3.13`); o doctor roda em python antigo só para apontar isso (`python >= 3.11`).

- `READY`: siga em frente.
- `READY WITH LIMITS`: falta só item opcional. Sem `faster_whisper`, avise
  que a transcrição automática não está disponível: peça `pip install -r
  requirements.txt` ou uma `transcricao.json` pronta, e continue. Sem o item de
  gráficos (chromium + playwright) ou sem `node`, siga sem cards e diga como instalar
  (`references/graficos.md`). Sem `Pillow` ou sem `node`, a capa automática
  (passos 9 e 10) não roda: peça `pip install -r requirements.txt` / instale o node
  ou siga pelo caminho do Figma.
- `MISSING`: pare. Liste os itens com ✘ (python, ffmpeg, ffprobe, disco) e diga
  como instalar; não tente renderizar.

## Entrevista de marca

Só se `brand/brand.json` faltar, estiver incompleto ou tiver valor inválido
(`python3 -I scripts/brand.py check brand/brand.json` sai com erro).

1. Gere a semente só se `brand/brand.json` estiver ausente:
   `python3 -I scripts/brand.py seed brand/brand.json`. Ela vem de
   `brand/guia-visual.md` (azul-marinho `#001931`, Poppins, legenda estática).
   O `seed` é só para arquivo ausente, nunca sobre um arquivo existente (ele se
   recusa); se o arquivo existe mas está incompleto ou inválido, corrija as
   chaves que o `check` apontar, sem `--force`.
2. Faça **uma pergunta por vez**, sempre propondo o valor da semente e esperando
   a resposta antes da próxima: (a) paleta, (b) fontes, (c) estilo de legenda,
   (d) @ das redes oficiais.
3. Grave cada resposta em `brand/brand.json` e confirme com `brand.py check`.
   Os @ não têm semente: não invente; deixe `handles` vazio até o usuário informar.
   Quando ele informar, grave com
   `python3 -I scripts/brand.py set-handles brand/brand.json @perfil [@perfil2]`.

## Fluxo

1. Crie `projects/<slug>/` (slug curto do tema) e copie o vídeo para
   `projects/<slug>/entrada.<ext>`.
2. `python3 -I scripts/transcribe.py projects/<slug>/entrada.<ext> projects/<slug>/transcricao.json`
   Se o doctor deu `READY WITH LIMITS` (faster-whisper ausente): instale com
   `pip install faster-whisper` antes de transcrever, ou peça uma
   `transcricao.json` pronta. Vídeo sem áudio falha aqui: peça outro arquivo.
3. `python3 -I scripts/cut.py detect projects/<slug>/transcricao.json projects/<slug>/cortes.json`
4. Mostre ao usuário a lista de cortes (id, início–fim, tipo: silêncio, muleta,
   repetição) e o **tempo total economizado**. Corte recusado: grave
   `{"cuts_removed": ["c3"]}` (ids recusados) em `projects/<slug>/decisions.json` e rode
   `python3 -I scripts/review_apply.py apply projects/<slug> projects/<slug>/decisions.json`
   (o corte fica guardado em `revisao.json` e pode voltar); nunca edite
   `cortes.json` à mão.
5. **Gráficos (opcional):** se um card ajudar a entender a fala (prazo,
   condição, passo), proponha no máximo 1 a cada ~8 s e, com o "sim" do usuário,
   grave `projects/<slug>/graficos.json` conforme `references/graficos.md`
   (título até 60, corpo até 140, `at` na linha do tempo cortada, 1–6 s,
   imagem de `materiais/` se houver). Sem card, pule este passo.
6. `python3 -I scripts/render.py projects/<slug> preview` e entregue o caminho de
   `projects/<slug>/saida/preview.mp4` (540x960).
7. **Revisão:** depois do preview, abra a página de revisão num navegador
   Chromium — no macOS `open -a "Google Chrome" review/review.html` (o `open`
   simples pode abrir o Safari, que não dá acesso à pasta); no Linux
   `xdg-open review/review.html` se o padrão for Chromium/Chrome, senão
   `google-chrome review/review.html` — e peça ao usuário para
   escolher a pasta `projects/<slug>/`. Antes, gere a visão de leitura:
   `python3 -I scripts/review_apply.py build projects/<slug>`. Detalhes em
   `references/revisao.md`.
8. **"aplicar revisão"** → rode, em ordem:
   `python3 -I scripts/review_apply.py apply projects/<slug> projects/<slug>/decisions.json`,
   `python3 -I scripts/review_apply.py build projects/<slug>` e
   `python3 -I scripts/render.py projects/<slug> preview`; diga ao usuário para
   tocar em "Recarregar review.json". Se o `apply` falhar (código 1), nada foi
   gravado: leia a mensagem e corrija a decisão. Sem a página (navegador sem
   acesso à pasta e sem plano B), faça a revisão na conversa e grave o
   `decisions.json` no mesmo formato.

9. **Capa — escolher o quadro** (depois que o preview foi aprovado): extraia
    candidatos do vídeo original,
    `python3 -I scripts/cover_frames.py video projects/<slug>/entrada.<ext> projects/<slug>/capa`
    (opcional `--n 3`; imprime um caminho por linha), ou, se o usuário mandar uma
    foto, `python3 -I scripts/cover_frames.py photo <foto> projects/<slug>/capa`
    (grava `capa/foto.png`). Mostre os arquivos `capa/candidato-N.png` e
    pergunte **qual quadro mostra o sorriso que ele quer**: quem escolhe é o
    usuário, a ferramenta só separa quadros nítidos e bem espalhados e não
    detecta sorriso. Se nenhum agradar, peça uma foto ou rode de novo com outro
    `--n`. Insumos em `references/capa.md`.

10. **Capa — compor** (depois de escolhido o quadro). Detalhes em `references/capa.md`.
    (a) **@ obrigatório:** se `handles` de `brand/brand.json` estiver vazio,
    pergunte o @ uma vez e grave com
    `python3 -I scripts/brand.py set-handles brand/brand.json @perfil`; nunca
    invente. (b) Pergunte o **gancho** (até 28 caracteres, ex.: "3 MITOS"), a
    **área** da pill (até 28) e o **subtítulo** (até 90; a parte depois da última
    quebra de linha sai em azul-claro). (c) **Caminho Figma**
    (preferido, se o conector do Figma estiver disponível e autorizado): carregue o
    skill `figma-use` antes de `use_figma`, duplique o frame `272:2` do arquivo
    `POSTS-OUTUBRO`, troque foto e textos, acrescente o @ e exporte PNG 1x para
    `projects/<slug>/capa/capa.png` (passo a passo em `references/capa.md`).
    (d) **Sem Figma** ou se o export falhar:
    `python3 -I scripts/cover_compose.py projects/<slug>/capa/candidato-N.png brand/brand.json projects/<slug>/capa/capa.png --hook "3 MITOS" --area "ISENÇÃO DE IR" --subtitle "linha branca\nlinha em destaque"`
    (ou `capa/foto.png`). Código 1 = nada gravado; leia a mensagem (sem @, foto
    pequena, gancho em mais de 2 linhas, texto longo demais, saída igual a um
    arquivo de entrada, Chromium ausente). (e) Mostre o `capa.png` ao usuário e
    peça aprovação; ajuste e gere de novo se ele pedir.

Falha (código 1, em qualquer script): leia a mensagem, corrija a causa (marca
ausente ou inválida, nenhuma fala na transcrição, arquivo faltando, card
inválido ou renderizador de gráficos ausente — a mensagem diz qual card) e
repita. Não deixe arquivo parcial.

## Gatilhos

- **"build preview" / "montar preview"** → `python3 -I scripts/render.py projects/<slug> preview`.
- **"final" / "versão final"** → `python3 -I scripts/render.py projects/<slug> final`
  (1080x1920, `saida/final.mp4`). Só depois de entregar um preview; o "final"
  do usuário é a aprovação do preview, então renderize sem pedir outra confirmação.

## Duração alvo

Reel **rápido: 12–15 s**; **aprofundado: 30–45 s**. Calcule a duração do vídeo
já cortado (original menos o total dos cortes). Se cair fora das duas faixas,
**avise** e sugira o que ajustar (cortar mais, ou manter trechos). Não bloqueie.

## O que ainda não existe

A revisão em página, a aba Materiais (passos 7 e 8), os cards de gráfico
(passo 5) e a capa (passos 9 e 10: escolha do quadro, composição pelo Figma ou
por `scripts/cover_compose.py`) já existem. Não existe publicação: nada vai
para o Instagram automaticamente. Não há detecção de sorriso (o usuário
escolhe o quadro) e só o arquivo `Poppins-Bold.ttf` está em `assets/fonts/`:
as legendas saem em Poppins Bold, e cards e capa usam esse mesmo peso para
todo o texto (a capa feita pelo Figma é a que sai com a tipografia exata). Para
o desenho completo da marca, ponha em `assets/fonts/` também `Poppins-Regular.ttf`,
`Poppins-SemiBold.ttf` e `Poppins-ExtraBold.ttf` (licença SIL OFL, pode ir para o repositório). Vídeo e legenda só saem pelo
`render.py` (os outros scripts que gravam vídeo ou legenda são de depuração).

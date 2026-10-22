# Gráficos animados (cards)

Cards curtos sobre o vídeo (título, corpo e imagem opcionais), desenhados por
`scripts/graphics.py` e sobrepostos pelo `render.py` no preview e no final.
Só quando ajudam a entender a fala (um prazo, uma condição, um passo): no máximo
1 a cada ~8 s, sem repetir a legenda. Reel sem card é válido.

## `projects/<reel>/graficos.json`

```json
{"cards": [{"id": "k1", "title": "Prazo em dias úteis",
            "body": "Sábados, domingos e feriados ficam fora.",
            "at": 2.0, "dur": 3.0, "material": "materiais/calendario.png"}]}
```

- `id`: texto único (1–64 caracteres); é a chave do "manter/descartar" da revisão.
- `title`: 1–60 caracteres. `body`: até 140 ou `null`.
- `at`: segundos na linha do tempo **cortada** (a do preview), `>= 0`.
- `dur`: de 1 a 6 s. Card que passa do fim do vídeo é encurtado; se sobrar
  menos de 1 s, é ignorado (aviso no terminal).
- `material`: `null` ou imagem (png, jpg, jpeg, webp, svg) **dentro da pasta
  do projeto**, em geral `materiais/<nome>` da aba Materiais. Vídeos e links de
  inspiração não entram no card; servem de referência para quem escreve.

## Revisão
`review_apply.py build` lista os cards em `review.json` (`cards`: id, título,
instante, duração, decisão). Na página, o revisor mantém ou descarta cada um;
`"graphics": {"k1": "drop"}` em `revisao.json` tira o card do render.

## Visual e movimento

- Cartão de vidro azul-marinho (`bg` de `brand/brand.json`, ~90% opaco), borda
  fina, raio 28 px, filete em `accent`, texto em `fg`.
- Poppins: título ExtraBold 76 px, corpo Regular 42 px (em 1080x1920); palavra
  longa quebra dentro do cartão. Imagem como miniatura arredondada 280x280.
- Posição: terço superior, topo a 320 px; nada acima de 250 px nem nos 340 px
  de baixo (faixa das legendas, que ficam por cima do card).
- Entrada 350 ms ease-out `cubic-bezier(.16,1,.3,1)` (sobe 48 px e aparece);
  saída 300 ms `cubic-bezier(.4,0,.2,1)`. Sem cor de alerta, sem piscar.

## Como é desenhado

HTML/CSS (`scripts/js/card.html`) no Chromium headless, quadro a quadro a 30 fps
(`scripts/js/render_card.mjs`, Playwright para Node), fundo transparente, sem
rede; o ffmpeg junta os quadros num WebM VP9 com alfa. Sem HyperFrames.
Requisitos: `node`, `npm i -g playwright`, `npx playwright install chromium` e
ffmpeg com `libvpx-vp9` (item opcional de gráficos no `doctor`). Sem isso, o
render de um projeto com card falha dizendo qual card. Só `Poppins-Bold.ttf` está em `assets/fonts/` (todos os pesos saem em Bold);
acrescente `Poppins-{Regular,SemiBold,ExtraBold}.ttf` ali para o desenho completo.

Card isolado: `python3 -I scripts/graphics.py <spec.json> brand/brand.json <saida.webm>`
(saída 0 ok; 1 erro, com a mensagem e nada gravado).

# Gráficos animados (efeitos e cards)

Efeitos curtos sobre o vídeo, tirados do banco (`banco/efeitos/<id>/`), desenhados por
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

Esse formato antigo continua valendo e é o efeito `card-destaque`
(`title` → `titulo`, `body` → `texto`, `material` → `imagem`).

### Qualquer efeito do banco

```json
{"cards": [{"id": "k2", "efeito": "numero-grande",
            "campos": {"destaque": "60 dias", "frase": "é o prazo para recorrer"},
            "at": 6.0, "dur": 3.0}]}
```

- `efeito`: o nome da pasta em `banco/efeitos/` (`card-destaque`, `numero-grande`,
  `pilula-destaque`, `selos`, `polaroides`, `circulo-a-mao`, `seta-a-mao`, `calendario`,
  `linha-do-tempo`, `palavra-destaque`). Nome que não existe é erro.
- `campos`: o que o `manifesto.json` do efeito pede (tipos, tamanho máximo, obrigatórios,
  listas com quantidade mínima e máxima). Campo que o efeito não tem é erro. Texto sem
  caracteres de controle (quebra de linha pode).
- Imagem: arquivo dentro da pasta do projeto (`materiais/foto.png`) ou
  `quadro:<segundo>`, um quadro do próprio vídeo, no segundo da linha do tempo cortada
  (no máximo 6 quadros por efeito). Ex.: `"imagens": ["quadro:2.5", "materiais/foto.png"]`.
- `dur`: entre a duração mínima e a máxima do efeito (`palavra-destaque`: até 2 s).

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

Cada efeito é uma página `banco/efeitos/<id>/efeito.html` (sem rede, texto só por
`textContent`, `window.setup(dados)` e `window.setTime(t)`), aberta no Chromium headless, quadro a quadro a 30 fps
(`scripts/js/render_card.mjs`, Playwright para Node), fundo transparente, sem
rede; o ffmpeg junta os quadros num WebM VP9 com alfa. Sem HyperFrames.
Requisitos: `node`, `npm i -g playwright`, `npx playwright install chromium` e
ffmpeg com `libvpx-vp9` (item opcional de gráficos no `doctor`). Sem isso, o
render de um projeto com card falha dizendo qual card. A Poppins vem de `assets/fonts/` (só os pesos que o efeito pede, embutidos na página).
Para conferir se todos os efeitos desenham: `python3 -I scripts/banco.py validar --efeitos`.

Card isolado: `python3 -I scripts/graphics.py <spec.json> brand/brand.json <saida.webm>`
(saída 0 ok; 1 erro, com a mensagem e nada gravado).

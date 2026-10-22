# Revisão do Reel (página `review/review.html`)

Página única, sem rede, aberta do disco. Ela só lê e grava arquivos do projeto;
**nunca roda Python**. Quem aplica a revisão é o Claude, com `review_apply.py`.

## Abrir

1. `python3 -I scripts/review_apply.py build projects/<reel>` (gera `review.json`).
2. Abra num navegador Chromium (Chrome, Edge; o Safari não dá acesso à pasta):
   no macOS `open -a "Google Chrome" review/review.html`; no Linux
   `xdg-open review/review.html` se o navegador padrão for Chromium/Chrome, senão
   `google-chrome review/review.html` (ou `chromium`).
3. "Abrir pasta do projeto" → escolha `projects/<reel>/` e permita edição.

## O que é salvo, e onde (tudo dentro de `projects/<reel>/`)

| Arquivo | Quando | Conteúdo |
|---|---|---|
| `decisions.json` | ~0,4 s após cada mudança ("Salvo às HH:MM:SS") | decisões para `review_apply.py apply` |
| `materiais/<nome>` | ao adicionar foto, vídeo ou ícone | cópia do arquivo, nome higienizado (sem `/`, `\`, controle; `-2`, `-3` se repetir) |
| `materiais.json` | ao mudar a aba Materiais | `{"items": [{"id", "kind", "name", "file" ou "url", "note"}]}` |

A página lê `review.json` e `saida/preview.mp4`; não altera mais nada.

`decisions.json` (deltas contra o `review.json` carregado):

```json
{"cuts_removed": ["c3"], "cuts_added": [{"start": 4.9, "end": 5.3}],
 "caption_edits": {"0": {"text": "Novo texto", "base_text": "texto automático que o revisor viu"}},
 "graphics": {"g1": "drop"},
 "notes": [{"t": 2.45, "text": "Ajustar a luz"}]}
```

- Palavra fora de corte: toque = `cuts_added` com início/fim da palavra.
  Palavra dentro de corte ativo: toque = `cuts_removed` com o id (restaura o
  corte inteiro). Silêncios aparecem como marcadores clicáveis. Segundo toque desfaz.
- `caption_edits`: índice da frase → `{"text", "base_text"}`; `text` vazio volta ao
  automático. `base_text` é o texto automático da frase quando o revisor editou:
  se os cortes mudarem antes do `apply` (frase renumerada ou com outro texto), o
  `apply` recusa com erro que nomeia a frase em vez de trocar a legenda errada.
  Na conversa (sem página) vale também a forma curta `{"0": "Novo texto"}`, sem
  essa conferência. Legenda tem no máximo 2 linhas e não aceita `\`, `{` nem `}`.
- `graphics`: id do card → `keep`/`drop`; a lista vem de `cards` no `review.json`
  (ver `references/graficos.md`).
- `notes` é sempre a lista inteira; `t` em segundos **do original** (a página
  converte o ponto do preview cortado).
- Cortes e legendas em rodadas separadas: com cortes pendentes as legendas ficam
  só leitura (e vice-versa), porque os cortes renumeram as frases.
- Ao abrir, um `decisions.json` existente é restaurado; o que já foi aplicado
  (já consta no `review.json`) é descartado sozinho.

## Ciclo aplicar → build → recarregar

Usuário diz "aplicar revisão". O Claude roda:

1. `python3 -I scripts/review_apply.py apply projects/<reel> projects/<reel>/decisions.json`
2. `python3 -I scripts/review_apply.py build projects/<reel>`
3. `python3 -I scripts/render.py projects/<reel> preview`

Depois, "Recarregar review.json" na página mostra o estado novo.
Erro no `apply` (código de saída 1: legenda com mais de 2 linhas, com `\`, `{`
ou `}`, frase cujo texto automático mudou, corte inválido) aparece no
terminal/na conversa com o Claude, não na página: nada é gravado.

## Plano B (sem acesso à pasta)

Se o navegador não tiver a API de pastas ou o acesso for negado: escolha o
`review.json` e, no player, o vídeo. Nada é gravado no projeto.
"Baixar decisions.json" e "Baixar materiais.json" geram os arquivos; coloque-os
em `projects/<reel>/`. Fotos e vídeos da aba Materiais **não são salvos** nesse
modo (a página avisa); copie-os à mão para `projects/<reel>/materiais/`.
Sem página nenhuma, a revisão acontece na conversa.

## Avisos

- Legenda editada cujo texto automático mudou: lista "edição de legenda antiga".
- Preview com duração diferente dos cortes atuais: peça um novo preview.
- O selo de duração (Reel rápido 12–15 s / aprofundado 30–45 s) é informativo.
- Aba Materiais vazia é válida: o editor segue sem materiais.

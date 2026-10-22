# Legendas do Reel

Regras aplicadas por `scripts/captions.py` (decisão do usuário, ver `brand/guia-visual.md`).
A legenda do Reel sai só pelo `render.py`; a CLI de `captions.py` é uso
interno/depuração (grava só o ASS).

- **Estáticas, por frase.** Cada frase aparece inteira de uma vez; sem pop-up, sem efeito palavra a palavra, sem movimento, escala ou rotação.
- **Fade de no máximo 150 ms** (o padrão é 100 ms), apenas na entrada e na saída da frase.
- **Tamanho da frase:** até 2 linhas de 38 caracteres; fecha em ponto final, `!`, `?`, `…` ou pausa maior que 0,6 s. Exibição mínima de 0,4 s, sem sobrepor a próxima.
- **Zona segura do Instagram:** margem inferior de 340 px (em 1080x1920) e 72 px nas laterais; alinhada embaixo, ao centro.
- **Cores e fonte vêm de `brand/brand.json`:** texto em `fg`, faixa em `bg` com ~55% de opacidade, fonte `font_body` em negrito (Poppins Bold: o estilo ASS usa `Bold=-1`). Nada de valor fixo no código.
- **Texto:** acentos, emoji e aspas são preservados; `{`, `}` e `\` são neutralizados para não virarem código ASS (e a revisão recusa esses caracteres numa edição).
- **Fonte:** `assets/fonts/Poppins-Bold.ttf` está no repositório e é a que o libass usa (estilo Bold); sem esse arquivo, cairia numa sans-serif da máquina (ver `README.md`).
- **Corte antes da legenda:** as palavras são remapeadas para a linha do tempo pós-corte (`captions.remap`); palavra cortada some da legenda.

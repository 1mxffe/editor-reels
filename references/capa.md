# Capa do Reel

## Insumos

- **Logotipo do escritório:** `assets/logo.webp` (1908x1045, RGBA, fundo
  transparente; wordmark branco e monograma GS azul-marinho). Copiado de
  `assets/logo.webp` do repositório `site-gutmannesilva` (o do site publicado).
- **Retrato do advogado**, em um destes arquivos na pasta do projeto, gerados por
  `scripts/cover_frames.py`:
  - `projects/<slug>/capa/candidato-N.png` (N = 1, 2, 3): quadros nítidos do
    próprio vídeo, em resolução cheia e em pé. O script não detecta sorriso: o
    usuário escolhe qual quadro mostra o sorriso.
  - `projects/<slug>/capa/foto.png`: foto enviada pelo usuário (lado menor de
    pelo menos 600 px, orientação EXIF aplicada, RGB).
- **Textos:** gancho (1 a 28 caracteres, até 2 linhas, ex.: "3 MITOS"), área da
  pill (até 28, sai em caixa-alta, ex.: "ISENÇÃO DE IR"), subtítulo (até 90; a
  parte depois da última quebra de linha sai em azul-claro) e o @.
- **@ obrigatório:** `handles` de `brand/brand.json`. Se estiver vazio, pergunte
  o @ ao usuário uma vez e grave com
  `python3 -I scripts/brand.py set-handles brand/brand.json @perfil [@perfil2]`
  (letras sem acento, números, ponto e sublinhado, até 30). Nunca invente.

## Saída

`projects/<slug>/capa/capa.png`: PNG 1080x1920, opaco. Padrão do frame
"Capa Reels — Isenção de IR: 3 mitos" (`brand/guia-visual.md`): logotipo
centralizado a ~13 % da altura, retrato ocupando o quadro, degradê azul-marinho
subindo da base, pill da área, gancho em Poppins ExtraBold branco-gelo,
subtítulo em SemiBold com a última linha em azul-claro e o @ embaixo.

**Áreas seguras:** todo texto entre y = 250 e y = 1580 (fora da faixa de
interface do Instagram) e dentro do recorte 3:4 da grade do perfil (y de 240 a
1680); margem lateral de 54 px. O @ fica logo acima de 1580, não no rodapé da
tela.

O texto da capa é o que o usuário aprovou: o escritório revisa o texto antes de
gravar e a ferramenta não confere o conteúdo, só os limites acima e o formato do @.

## Caminho A — Figma (preferido)

Dá o acabamento exato da marca (Poppins verdadeira, ícone e ajustes finos do
time). Exige o conector do Figma autorizado no Claude e acesso de edição ao
arquivo; sem isso, use o caminho B.

1. Carregue o skill `figma-use` antes de chamar `use_figma` (obrigatório).
2. Abra o arquivo `POSTS-OUTUBRO` (key `e47yD4UZB4vNJ75VMMVYyU`, página
   INSTAGRAM) e duplique o frame `Capa Reels — Isenção de IR: 3 mitos (ID nova)`
   (node `272:2`, 1080x1920). Nunca edite o original.
3. Envie a foto escolhida (`capa/candidato-N.png` ou `capa/foto.png`) com
   `upload_assets` e troque o preenchimento da foto no frame duplicado.
4. Edite a pill, o gancho e o subtítulo (última linha em azul-claro) e
   acrescente uma camada de texto com o @, dentro das áreas seguras acima.
5. Exporte o frame em PNG 1x para `projects/<slug>/capa/capa.png`.
6. Se qualquer passo falhar (conector ausente, sem permissão, export com erro),
   avise o usuário e siga pelo caminho B.

## Caminho B — automático (`scripts/cover_compose.py`)

```
python3 -I scripts/cover_compose.py projects/<slug>/capa/candidato-N.png brand/brand.json \
    projects/<slug>/capa/capa.png --hook "3 MITOS" --area "ISENÇÃO DE IR" \
    --subtitle "que podem te fazer pagar\nmais imposto de renda"
```

Página HTML desenhada pelo Chromium headless (mesmo esquema dos cards de
gráfico, sem rede). Não usa o arquivo do Figma: reproduz o layout. Só o
`Poppins-Bold.ttf` está em `assets/fonts/`: a capa sai em Poppins, mas com todo o
texto em Bold; sem os outros pesos (Regular, SemiBold, ExtraBold) o desenho difere
um pouco do final da marca. O degradê acompanha a altura medida do bloco de texto e um véu
azul-marinho no topo escurece o fundo do logotipo conforme a claridade da foto
(wordmark e pill com contraste >= 4,5:1 até em foto clara). Saída: 0 imprime o
caminho; 1 erro claro, nada gravado (sem @, @ inválido, foto pequena ou
ilegível, gancho em mais de 2 linhas, bloco de texto começando acima de y = 520,
saída igual à foto/logotipo/brand.json, Chromium ausente).

Em qualquer caminho, mostre o `capa.png` ao usuário e só considere a capa
pronta depois da aprovação dele. Nada é publicado automaticamente.

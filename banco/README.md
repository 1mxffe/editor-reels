# Banco de estilos e efeitos

Cada item é uma pasta com um arquivo `manifesto.json`. A tela de Estilo lê tudo daqui.

## Como adicionar um item

1. Copie a pasta de um item parecido (por exemplo `paletas/marca`) e dê um novo nome à cópia.
   O nome da pasta é o identificador: só letras minúsculas sem acento, números e hífen
   (`meu-estilo`), até 40 caracteres.
2. Abra o `manifesto.json` da cópia e troque `nome`, `descricao` e os valores em `dados`.
3. Rode `python3 -I scripts/banco.py validar`. Se algo estiver errado, ele diz qual pasta e por quê.
   Item com erro não aparece na tela.

## Tipos (pasta onde fica cada um)

- `paletas/` (tipo `paleta`): quatro cores `#rrggbb` em `dados`: `fundo`, `texto`, `destaque`, `apoio`.
- `legendas/` (tipo `legenda`): `estilo` (`faixa`, `pilula`, `duas-linhas` ou `pequena`),
  `posicao_padrao` (`baixo` ou `meio`) e `tamanho_padrao` (`P`, `M` ou `G`).
- `efeitos/` (tipo `efeito`): precisa de `efeito.html` na pasta e de `duracao`
  (`padrao`, `min`, `max`, em segundos). Em `dados`:
  - `area_segura`: `true` (obrigatório): o efeito promete ficar entre y 250 e 1580 da tela
    1080x1920, longe do topo e da faixa da legenda.
  - `pesos` (opcional): pesos da Poppins que a página usa, entre 400, 500, 600, 700 e 800.
  - `transicao` (opcional): `suave` (entra em 350 ms e sai em 300 ms) ou `corte` (corte seco).
  - `exemplo` (opcional): campos de exemplo, usados no quadro de amostra e na verificação.
  - `mesmo_tamanho` (opcional): grupos de campos-lista que precisam ter a mesma quantidade
    (ex.: `[["datas", "legendas"]]`).
  O `efeito.html` precisa da linha de segurança `Content-Security-Policy` com
  `default-src 'none'` (sem internet) e das funções `window.setup(dados)` e
  `window.setTime(t)`. Para testar no navegador: `python3 -I scripts/banco.py validar --efeitos`
  (efeito que não desenha aparece com o motivo).
- `materiais/` (tipo `material`): fotos, ícones e inspirações do escritório.

## Regras

- `nome` até 60 caracteres e `descricao` até 300, sem caracteres de controle ou invisíveis. Chaves repetidas no JSON não são aceitas.
- Limites: duração até 600 s (efeito: até 30 s); `min`/`max` de campo entre 0 e 1.000.000; cada opção até 60 caracteres; `efeito.html` até 1 MiB.
- `tipo` precisa ser o da pasta onde o item está.
- `campos` é o que a pessoa preenche (`texto`, `numero`, `imagem`, `cor` ou `escolha`);
  `max` e `min` são números e `0 <= min <= max`; `escolha` pede `opcoes` (até 20 textos).
  `itens` (`{"min": 2, "max": 4}`) transforma o campo numa lista (texto, número ou imagem);
  `inteiro: true` só aceita números inteiros. Imagem pode ser um arquivo do projeto
  (`materiais/foto.png`) ou `quadro:<segundo>` (um quadro do próprio vídeo).
- Não use atalhos de pasta (links) nem `..` nos nomes. O manifesto tem no máximo 64 KiB.
- Pastas cujo nome começa com ponto são ignoradas.
- `campos` pode ser `[]` (item sem nada para preencher).
- Chaves que não existem nesta lista fazem o item ser recusado.

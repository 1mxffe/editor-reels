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
  (`padrao`, `min`, `max`, em segundos).
- `materiais/` (tipo `material`): fotos, ícones e inspirações do escritório.

## Regras

- `nome` até 60 caracteres e `descricao` até 300, sem caracteres de controle.
- `tipo` precisa ser o da pasta onde o item está.
- `campos` é o que a pessoa preenche (`texto`, `numero`, `imagem`, `cor` ou `escolha`);
  `max` e `min` são números e `0 <= min <= max`; `escolha` pede `opcoes` (até 20 textos).
- Não use atalhos de pasta (links) nem `..` nos nomes. O manifesto tem no máximo 64 KiB.
- Chaves que não existem nesta lista fazem o item ser recusado.

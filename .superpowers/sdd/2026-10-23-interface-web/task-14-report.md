# Task 14: relatório

**Feito**
- `app/web/passos/estilo.js`: passo Estilo (opcional, não trava os seguintes) com abas Paletas, Fontes, Legendas, Efeitos e Notas; cartões com quadro de exemplo, "Usar", "Mais parecido com este", barra fixa "Aplicar estilo" com indicador de mudanças não aplicadas; formulário de efeitos gerado dos `campos` do manifesto (texto, número, imagem, cor, escolha, `itens`, `inteiro`, `mesmo_tamanho`, limites e obrigatório), grava em `graficos.json` sem apagar cards; aviso recolhido de itens do banco que não carregaram.
- `tarefa.js`: rótulos de `quadros` e `aplicar-estilo`; a versão do preview vale também após aplicar estilo (o player recarrega).
- `mensagens.js`: erros de efeito traduzidos. `graficos.js`: entradas de efeito aparecem sem quebrar (sem botão de editar).
- `serve_for_test.py`: `banco_raiz` e `fonts_dir` (só para a lista).
- Testes: `tests/test_app_ui_flow_c.py` + `tests/js/app_flow_c.mjs` (10 testes). Capturas em `screens-t14/`.

**Preocupações**
- Variações de paleta só aparecem (o estilo.json guarda só o id); as de legenda podem ser usadas.
- Os exemplos de legenda usam a posição/tamanho já aplicados, não os pendentes.
- Cancelar "aplicar-estilo" não desfaz o estilo.json já gravado pelo servidor.
- Verificação do preview: letras claras no centro vs embaixo (limite baixo, 0,1%).

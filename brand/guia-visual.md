# Guia visual — Gutmann & Silva (v1, baseado no Figma "POSTS-OUTUBRO")

> **Origem:** arquivo Figma `POSTS-OUTUBRO` (página INSTAGRAM, 21 frames:
> carrosséis 1080x1350, cards únicos, capas e Reels 1080x1920). Telas lidas:
> capa de Reel "3 mitos" (`272:2`), "Isenção IR – Aposentados" (`16:2`),
> carrossel "Inventário v4" (`259:2`), card "EC 141/2026 / 6x1" (`229:2`).
> O arquivo **não define variáveis ou estilos de cor** (`get_variable_defs`
> retornou vazio). Os hex abaixo foram **medidos nas imagens renderizadas**
> (amostragem de pixels) e são aproximados: confirmar com os valores nativos.
> Esta versão **substitui o rascunho v0**, que veio do CSS do site e não
> bate com os posts (o site usa Inria Serif; os posts usam Poppins).

## Cores (aproximadas)

| Papel | Hex medido | Onde aparece |
|---|---|---|
| Azul-marinho profundo (base escura) | `#001931` / `#011a31` | fundo da capa de Reel, rodapé degradê |
| Azul médio (carrossel) | `#235587` → `#092744` | fundo degradê dos carrosséis |
| Preto-azulado (fundo foto escura) | `#050d13` | post de isenção de IR |
| Gelo (fundo claro) | `#f3f8fb` → `#dde9f3` | card claro (degradê suave) |
| Texto sobre escuro | `#ddebf5` a `#ffffff` | títulos em branco-gelo |
| Azul de destaque no escuro | azul-claro (~`#a8c8f0`) | segunda linha da capa ("mais imposto de renda") |
| Cartões brancos | `#ffffff` | cartões de destaque nos carrosséis |
| Pill / chip translúcido | branco ~10% + borda fina | tag da área ("ISENÇÃO DE IR") |

Regra visual: **azul-marinho dominante**, claro só como variação (card único).
Degradês suaves azul sobre azul; sem cor de alerta.

## Tipografia

- **Poppins em tudo**: títulos em Bold/ExtraBold, corpo em Regular/Medium.
  Números e palavras-gancho gigantes ("60 dias", "3 MITOS", "SIM!").
- Hierarquia: gancho enorme → subtítulo em SemiBold → apoio em Regular.
  Palavra-chave do apoio em **negrito** ou em azul-claro.
- **Serifada só no logotipo** (monograma GS + "Gutmann & Silva — Advogados
  Associados"). Não usar Inria Serif em títulos.

## Componentes recorrentes

- **Logo** centralizado no topo (capas e cards) ou canto superior esquerdo
  (carrossel): monograma "GS" em quadrado azul-marinho + wordmark serifado.
- **Tag de área**: pill arredondada com ícone + área em caixa-alta pequena
  ("FAMÍLIA & SUCESSÕES", "TRABALHISTA", "PREVIDENCIÁRIO", "ISENÇÃO DE IR").
- **Cartões** arredondados (raio generoso), vidro fosco no escuro; brancos
  para destaque.
- **Numeração** nos carrosséis: "02 / 07" no canto, área no topo.
- **Linha do tempo** com pontos e datas em negrito nos cards informativos.
- **Última lâmina**: CTA "Saiba mais no link da bio" em botão branco.
- **Foto**: retrato do advogado sorrindo, de frente, com cenário do escritório;
  degradê azul-marinho subindo da base para dar leitura ao texto.

## Capa de Reel (1080x1920) — padrão a replicar

1. Logo centralizado no topo (~13–20% da altura).
2. Retrato do advogado no centro, sorrindo, olhando para a câmera.
3. Degradê azul-marinho da metade inferior para baixo.
4. Pill da área, acima do título.
5. Gancho em Poppins ExtraBold branco-gelo, 1–2 palavras grandes
   ("3 MITOS").
6. Subtítulo em Poppins SemiBold, com a última linha em azul-claro.
7. Margem lateral ≈ 5% (≈ 54 px); o texto fica no terço inferior, acima
   da base livre.

## Legendas do vídeo (decisão do usuário)

Estáticas, por frase, sem pop-up e sem animação por palavra; Poppins SemiBold,
branco, faixa azul-marinho translúcida quando o fundo for claro; palavra-chave
pode ir em azul-claro **sem** animação (cor fixa).

## Pendências

1. Hex nativos (o arquivo não tem variáveis): se quiser, crie estilos de cor no
   Figma ou me passe a paleta do manual de marca.
2. @ das redes sociais oficiais (não aparecem nos frames lidos).
3. Quais dos 21 frames são a referência "oficial" — li 4; posso ler os demais.

# Editor de Reel — Gutmann & Silva · Design

> **2026-10-22 — decisão do escritório:** o checklist OAB foi removido do editor (revisão humana dupla antes da gravação); as seções sobre OAB abaixo estão superadas.

Data: 2026-10-21 · Status: aguardando revisão do usuário

## Objetivo

Uma skill do Claude Code, instalada localmente no Mac do escritório, que recebe
o vídeo bruto de um advogado falando para a câmera e devolve um Reel vertical
(1080x1920) pronto para postar: silêncios e vícios cortados, legendas na marca,
gráficos animados quando fizerem sentido e capa. Referência de fluxo: guia
"edit your reels with claude" (getgitgirl / claude-reel-editor).

Para quem: equipe do Gutmann & Silva, que produz os Reels do Instagram
(formatos "Reel rápido" 12–15 s e "Reel aprofundado" 30–45 s).

Sucesso: do vídeo bruto ao arquivo final em três gestos (soltar o vídeo, revisar,
dizer "final"), sem nenhum texto que reprove no checklist da OAB.

## Decisões já tomadas

- Skill local, como no guia (não é um editor 100% no navegador).
- Repositório novo e independente, `gutmannesilva-reel-editor`. As regras da OAB
  e do perfil do escritório são copiadas do repositório `auto-copys` com aviso
  de origem no topo de cada arquivo.
- Renderização escolhida por etapa: `ffmpeg` para corte e legendas; HyperFrames
  somente quando houver gráfico animado.
- Legendas estáticas, por frase, **sem animação de pop-up e sem efeito por
  palavra**.
- Entrega em três partes, nesta ordem: (1) pipeline, (2) revisão + materiais,
  (3) capa. Cada parte é utilizável sozinha.
- Marca (paleta, fontes, @ das redes) vem de um manual fora do repositório; é
  coletada em entrevista na primeira execução e salva em `brand/brand.json`.

## Fora do escopo da v1

Publicação automática em redes, trilha sonora automática, versão CapCut, coleta
de métricas por API.

## Estrutura do repositório

```
.claude/skills/editor-reel/SKILL.md   procedimento e gatilhos
references/                           normas-oab.md, formatos-reel.md, legendas.md, capa.md
brand/brand.json                      criado na primeira execução
scripts/                              doctor, transcribe, cut, oab_check, captions, render, cover
projects/<reel>/                      entrada, transcricao.json, cortes.json, saida/
docs/superpowers/specs/               este documento
```

Cada script tem uma responsabilidade, entrada e saída em arquivo (JSON ou
vídeo) e pode ser testado sozinho.

## Entrega 1 — Pipeline

1. **doctor**: verifica `ffmpeg`, `node`, Whisper e espaço em disco. Termina com
   READY, READY WITH LIMITS ou lista o que falta.
2. **Entrevista de marca** (só na primeira vez): paleta, fontes, estilo de
   legenda, @ das redes. Uma pergunta por vez, salva em `brand.json`.
3. **transcribe**: transcrição com tempo por palavra → `transcricao.json`.
4. **cut**: detecta silêncios e vícios ("ãh", "né", repetições). Grava a lista
   de cortes em `cortes.json` sem apagar o original, para a revisão poder
   desfazer qualquer corte.
5. **oab_check (bloqueante)**: aplica o checklist de `references/normas-oab.md`
   à transcrição, às legendas e ao texto de gráficos/capa. Bloqueia: promessa
   de resultado, sensacionalismo/urgência, captação, autoelogio, número de lei
   ou artigo no texto de tela. Em caso de reprovação não renderiza e informa o
   item. Conformidade nunca cede a estética ou métrica.
6. **captions**: legendas por frase, fixas, sem animação, com fonte/cor da marca
   e área segura do Instagram respeitada.
7. **render**: 1080x1920. Rascunho de baixa resolução ("build preview") e
   arquivo final em alta ("final").

## Entrega 2 — Revisão e materiais de apoio

- Artefato privado com: preview do corte, palavras clicáveis para cortar/restaurar,
  manter ou trocar cada gráfico, correção de legenda, notas por instante. Salva
  conforme o usuário interage.
- Aba opcional **Materiais**: upload de fotos, vídeos e ícones e área de
  inspirações (imagens ou links). Vazia = o editor segue sem ela; com itens, os
  gráficos podem usá-los.
- Plano B: se o artefato não estiver disponível, a revisão acontece no chat.

## Entrega 3 — Capa

- Candidatos a capa: 3 frames do vídeo com o advogado sorrindo, ou foto enviada.
- Composição com título, @ das redes e paleta da marca, no **Figma** pelo
  conector. Se o Figma não estiver disponível, versão HTML equivalente
  exportada em PNG.
- O texto da capa passa pelo mesmo `oab_check`.

## Erros

Cada script falha com mensagem clara, código de saída diferente de zero e sem
deixar arquivo parcial. O `render` nunca roda sem `oab_check` aprovado.

## Testes

Vídeo de exemplo curto, versionado em `tests/fixtures`:
- o corte reduz a duração e mantém `cortes.json` reversível;
- as legendas aparecem sem animação;
- um texto proibido bloqueia o render e nomeia o item reprovado;
- `doctor` reporta corretamente uma dependência ausente.

## Riscos e pendências

- Criar o repositório remoto está fora do escopo de GitHub da sessão atual
  (apenas `auto-copys` e `site-gutmannesilva`); depende de autorização ou de o
  usuário criá-lo.
- Whisper não está instalado no ambiente; entra na implementação.
- A exportação do PNG da capa a partir do Figma pode exigir passo manual.
- Paleta e fontes reais da marca ainda não foram fornecidas.

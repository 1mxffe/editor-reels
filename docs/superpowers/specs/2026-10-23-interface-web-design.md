# Interface web do Editor de Reel — Design

Data: 2026-10-23 · Status: aguardando revisão do usuário

## Objetivo

Hoje o editor só se usa pelo Claude Code e pelo terminal. A equipe do
Gutmann & Silva quer **um programa de tela**: dar dois cliques, soltar o
vídeo e clicar nos passos, sem terminal e sem Claude Code. Esta versão
entrega isso como um **app no navegador que roda no próprio Mac**, reaproveitando
os scripts que já existem como "motor".

Para quem: a equipe de marketing do escritório (não técnica), em Mac, usando o Chrome.

Referência visual (reel enviado pelo usuário, 3 capturas): página local com o
**vídeo vertical à esquerda** (Pause, −5s, +5s, tempo) e, à direita, **abas** (Paletas,
Fontes, Legendas, Efeitos, Transições, Notas) com **cartões de opção** que mostram
um quadro do próprio vídeo já com o estilo aplicado, um nome e uma frase; escolhe-se
tocando nos cartões ("usar" / "mais parecido com este"). No exemplo o botão final
copia as escolhas para colar no Claude; **aqui o app aplica direto** (decisão do
usuário: sem depender do Claude).

Sucesso: uma pessoa que nunca abriu o terminal consegue, só com a tela,
ir do vídeo bruto ao Reel final e à capa, e entende em português qualquer
problema de instalação ou de execução.

## Decisões já tomadas

- App no navegador com 1 clique (não `.app` instalável, não Windows).
- O motor continua sendo os scripts em `scripts/` (transcribe, cut, captions,
  render, review_apply, graphics, cover_frames, cover_compose, brand, doctor).
  A interface os chama como subprocessos; **não os reescreve** e não duplica lógica.
- Sem dependências novas: servidor em Python (biblioteca padrão) e página em
  HTML/CSS/JS puros.
- O Claude Code e a skill `editor-reel` continuam funcionando.
- Nada é publicado no Instagram; o checklist OAB não existe mais no projeto.

## Fora desta versão

App `.app` assinado, Windows, vários usuários ao mesmo tempo, edição pelo Figma
na tela, publicação automática, login/contas, envio de arquivos para a internet.

## Arquitetura

```
Abrir Editor.command   duplo clique no Mac; acha o python3 ≥ 3.11, sobe o servidor, abre o Chrome
app/server.py          servidor HTTP em 127.0.0.1 (porta livre), API JSON + arquivos estáticos
app/jobs.py            fila de tarefas longas: roda scripts como subprocessos, guarda estado e log
app/projects.py        lista/cria projetos em projects/<slug>/, validação de nomes e caminhos
app/web/               index.html, app.css, app.js (+ módulos por tela); em português
review/review.html     reaproveitada: ganha um adaptador de armazenamento "HTTP"
tests/                 test_app_*.py (API) e tests/js/ (fluxo na tela com Chromium)
```

### Servidor local

- Escuta só em `127.0.0.1`, em porta livre escolhida na subida; a URL abre o
  navegador com um **token aleatório** (`?t=…`) que toda chamada da API exige
  (cabeçalho). Sem CORS. Recusa pedidos com `Host`/`Origin` de outro lugar.
- Todos os caminhos vêm do slug do projeto (`[a-z0-9-]{1,40}`); o servidor
  resolve dentro de `projects/` e recusa `..`, links simbólicos que saiam da
  pasta e nomes de arquivo fora de uma lista (`entrada.*`, `saida/*`, `capa/*`,
  `materiais/*`).
- Upload do vídeo por streaming direto para o disco (arquivos grandes),
  com limite de tamanho configurável (padrão 4 GB) e checagem de que é vídeo
  (`ffprobe`). Erros viram mensagens em português, nunca traceback.
- Fecha sozinho depois de um tempo sem a página aberta (heartbeat da página).

### Tarefas longas

Transcrever, renderizar, gerar candidatos de capa, compor capa e renderizar
cards rodam em segundo plano: `POST /api/projects/<slug>/jobs/<tipo>` devolve um
`job_id`; a página consulta `GET /api/jobs/<id>` (estado, mensagem, últimas
linhas do log, arquivos produzidos). Um projeto roda **uma tarefa por vez**; uma
segunda recebe "já há uma tarefa em andamento". Tarefas podem ser canceladas.
Cada tarefa usa os mesmos comandos do SKILL (`python3 -I scripts/<x>.py …`), com
os mesmos códigos de saída (0 ok, 1 erro) e as mesmas gravações atômicas.

### API (resumo)

| Rota | O que faz |
|---|---|
| `GET /api/doctor` | resultado do `doctor` já traduzido: item, ok/falta, ação |
| `GET/POST /api/projects` | lista; cria (nome → slug) |
| `PUT /api/projects/<s>/video` | envia o vídeo bruto (streaming) |
| `GET /api/projects/<s>` | estado: etapas concluídas, arquivos, duração, brand |
| `POST …/jobs/transcrever` `…/cortes` `…/preview` `…/final` `…/capa-candidatos` `…/capa` `…/card` | tarefas longas |
| `GET/PUT …/cortes` | cortes ativos/removidos (via `review_apply`) |
| `GET/PUT …/legendas` | frases e edições (via `review_apply`) |
| `GET/PUT …/graficos` | cards (`graficos.json`) |
| `GET/PUT …/materiais` | fotos, vídeos, ícones e inspirações |
| `GET/PUT /api/brand` | `@` das redes e conferência do `brand.json` |
| `GET …/arquivos/<caminho>` | serve preview, final, capa e candidatos (com Range para o `<video>`) |
| `POST …/abrir-pasta` | abre a pasta do projeto no Finder |

## Telas (8 passos + instalação)

Layout em duas colunas, como na referência: **player vertical fixo à esquerda**
(play/pause, ±5 s, tempo, mostra o preview mais recente ou o vídeo bruto) e o
painel do passo à direita. Barra de passos no topo; cada passo mostra o estado
(pendente, em andamento, pronto) e só libera o próximo quando o anterior está
pronto, mas dá para voltar.

1. **Vídeo:** nome do Reel, arrastar/soltar o arquivo, barra de envio, duração e formato detectados.
2. **Cortes:** botão "Transcrever" (barra de progresso; na 1ª vez avisa que baixa o modelo de voz); lista de cortes (silêncio, muleta, repetição) com ligar/desligar, tempo economizado, e as palavras clicáveis (a lógica da página de revisão).
3. **Legendas:** frases editáveis (no máximo 2 linhas), mostrando onde a legenda aparece; edições presas ao texto automático original (como `review_apply` já faz).
4. **Estilo:** abas **Paletas**, **Fontes**, **Legendas**, **Efeitos** e **Notas**, com
   cartões de opção no formato da referência (veja a seção "Passo Estilo"). Botão **Aplicar**.
5. **Preview:** botão "Gerar preview" e player na própria página; notas com marca de tempo.
6. **Gráficos (opcional):** adicionar card (título ≤ 60, texto ≤ 140, momento e duração), escolher imagem dos materiais, manter/remover; a aba **Materiais** (fotos, vídeos, ícones, inspirações) vive aqui.
7. **Capa:** "Escolher quadro" mostra 3 candidatos (ou envia uma foto); campos gancho, tag da área e subtítulo; capa gerada ao lado; aviso se o texto não cabe.
8. **Final:** "Gerar versão final", tempo estimado, player, e botão "Abrir pasta" com `final.mp4` e `capa.png`.

### Passo Estilo (catálogo fixo, aplicado direto)

O usuário escolhe em cartões; cada cartão traz um **quadro do vídeo dele com o estilo
já desenhado** (gerado sob demanda por um comando novo, ver "Motor"), o nome e uma frase
curta. Escolha por aba: um cartão "usar" por aba; "mais parecido com este" reordena os
cartões da aba em torno do escolhido (variações de tamanho, posição e fundo do mesmo estilo).

- **Paletas:** a da marca (azul-marinho `#001931`, gelo `#ddebf5`, acento `#a8c8f0`) e variações
  predefinidas (marinho profundo, claro-gelo, neutro-grafite). Define fundo da faixa/cartões,
  texto e destaque (afeta legendas, cards e capa).
- **Fontes:** só as famílias cujos arquivos existem em `assets/fonts/` (hoje: Poppins Bold).
  Colocar outro `.ttf` ali faz a opção aparecer; a aba diz isso com todas as letras.
- **Legendas** (sempre **estáticas por frase, sem pop-up e sem animação por palavra**, fade ≤ 150 ms):
  quatro estilos — *Faixa azul* (o atual), *Pílula escura no centro*, *Duas linhas grandes*,
  *Pequena, baixa e à esquerda* — mais posição (baixo/meio) e tamanho (P/M/G), respeitando a
  área segura do Instagram (topo 250 px, base 340 px).
- **Efeitos:** os cards animados (ligar/desligar por card, estilo "vidro" ou "branco", entrada
  suave); transições são só corte seco (sem opções).
- **Notas:** anotações com marca de tempo (as mesmas da revisão).
- As escolhas ficam em `projects/<slug>/estilo.json` (paleta, fonte, legenda{estilo,posição,
  tamanho}, cards{estilo}); `render`, `graphics` e `cover_compose` passam a lê-lo; sem o
  arquivo, o resultado é idêntico ao de hoje.
- **Aplicar** grava `estilo.json` e gera um novo preview (tarefa em segundo plano).

**Instalação** (primeira tela, e no menu): cada item do `doctor` em português
(✔/✘, o que falta, comando de correção copiável). Primeira vez: pede o `@`
das redes (grava com a mesma validação de `brand.py set-handles`).

Visual: azul-marinho `#001931`, texto gelo `#ddebf5`, acento `#a8c8f0`, Poppins
(arquivo em `assets/fonts/`), tema claro/escuro, 16 px de margem, funciona em
375 px, foco visível, `lang="pt-BR"`, sem emoji como ícone; movimento calmo.

## Motor: o que muda nos scripts

- `scripts/estilo.py` (novo): catálogo de estilos, validação de `estilo.json`, defaults =
  comportamento atual, e `quadro(project, estilo, t, out)` que desenha **um quadro** do vídeo
  com o estilo (ffmpeg, mesma montagem do render, 540x960, rápido) para os cartões.
- `captions.py`: `to_ass(..., estilo)` ganha os quatro estilos, posição e tamanho; sem
  `estilo` a saída é byte a byte a de hoje (teste de regressão).
- `render.py`, `graphics.py`, `cover_compose.py`: leem `estilo.json` (paleta/fonte/cards)
  quando existe; nenhuma mudança de interface para quem não usa a tela.
- Palavra por palavra, karaokê e qualquer animação de legenda ficam **fora** (pedido do usuário).

## Integração com o que existe

- `review/review.html` ganha um **adaptador "HTTP"** além do de pasta e do de
  arquivos; dentro do app ela não pede para escolher pasta. Os outros modos continuam.
- `review_apply.py`, `render.py` etc. não mudam de interface. Mudanças nos scripts
  só onde faltar um ponto de entrada **sem** alterar o comportamento (por exemplo,
  saída de progresso em linha, `--json` no `doctor`); cada uma com teste.
- `Abrir Editor.command` é o único ponto de entrada para quem não usa terminal;
  README e `COMO-USAR.md` (novo, em português simples) descrevem a instalação em
  passos de clique/cola, usando o resultado real da instalação no Mac da equipe
  (Homebrew `python@3.13`, `PATH`, `pip install --break-system-packages`).

## Erros e segurança

- Toda falha de script vira uma mensagem curta em português + "Detalhes" com o
  log; códigos de saída ≠ 0 nunca deixam arquivo parcial (os scripts já garantem).
- Sem `eval`, sem `shell=True`; argumentos sempre em lista; nenhum texto digitado
  vai para linha de comando sem passar pelos validadores existentes.
- Textos do usuário entram na página só por `textContent`. CSP sem rede.
- O servidor nunca lê nem grava fora de `projects/` e `brand/brand.json`.

## Testes

- `tests/test_app_*.py`: servidor em porta efêmera com vídeo sintético (gerado
  pelo `conftest`): token e `Host`, caminhos maliciosos, upload e limite, uma
  tarefa por vez, cancelamento, progresso, doctor traduzido, cortes/legendas/
  graficos/materiais, arquivos com Range, abrir pasta (substituído por um duplo).
- `tests/js/`: fluxo completo na tela com Chromium (node Playwright): criar
  projeto → subir vídeo → transcrever (com transcrição de teste no lugar do
  Whisper) → cortes → legendas → preview → card → capa → final; 375 px sem
  rolagem horizontal; mensagens de erro.
- A suíte atual (≈ 469 testes) continua passando.

## Riscos e pendências

- A transcrição real só roda no Mac da equipe (faster-whisper não está no
  ambiente de desenvolvimento); o teste de tela usa uma transcrição fixa.
- Safari não consegue abrir a pasta pelo modo antigo; no app não é preciso, mas
  o `Abrir Editor.command` abre o Chrome por padrão.
- Poppins: só o peso Bold está no repositório.
- O Chromium (cards e capa) precisa de `npm i -g playwright` e
  `npx playwright install chromium`; a tela de instalação oferece o comando e,
  depois, um botão "Instalar" que roda esses dois comandos como tarefa.
- Tempos de render (vários minutos para vídeos longos) dependem do Mac.

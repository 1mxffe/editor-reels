# Como usar o Editor de Reels

O editor transforma o vídeo que você gravou falando para a câmera em um Reel
vertical, com cortes e legendas. Tudo acontece no seu Mac: seus vídeos não saem do seu Mac
(só a primeira instalação baixa programas e o modelo de voz) e nada é publicado
sozinho.

Este guia é para quem nunca usou o Terminal. Siga na ordem.

---

## 1. Instalação (só na primeira vez)

Você vai usar o **Terminal**, um programa que já vem no Mac. Para abrir:
aperte `Command + Espaço`, digite **Terminal** e aperte `Enter`.

Em cada passo abaixo: **copie a linha cinza, cole no Terminal e aperte `Enter`**.
Espere terminar (o Terminal volta a mostrar o cursor piscando) antes de ir para o
próximo. Se ele pedir a senha, digite a senha do seu Mac (as letras não aparecem
enquanto você digita; é normal) e aperte `Enter`.

### Passo 1 — Homebrew (o instalador de programas)

Abra o site <https://brew.sh>, copie o comando que aparece logo no começo da
página, cole no Terminal e aperte `Enter`.

No fim, o Homebrew mostra uma parte chamada **"Next steps"** com duas ou três
linhas para copiar. Copie e cole essas linhas também (uma de cada vez). Elas
fazem o Mac encontrar o Homebrew.

### Passo 2 — Os programas do editor

```
brew install python@3.13 ffmpeg node git
```

Isso instala o Python (programa base do editor), o conversor de vídeo, o
desenhista dos gráficos e da capa, e o programa que baixa as atualizações.
Pode levar alguns minutos.

### Passo 3 — Fazer o Mac usar o Python novo

O Mac já vem com um Python antigo. Primeiro descubra onde o Homebrew ficou.
Cole esta linha e aperte `Enter`:

```
brew --prefix
```

- Se aparecer **`/opt/homebrew`** (Mac com chip Apple, M1/M2/M3...), use esta linha:

  ```
  echo 'export PATH="/opt/homebrew/opt/python@3.13/libexec/bin:$PATH"' >> ~/.zprofile
  ```

- Se aparecer **`/usr/local`** (Mac Intel, mais antigo), use esta outra:

  ```
  echo 'export PATH="/usr/local/opt/python@3.13/libexec/bin:$PATH"' >> ~/.zprofile
  ```

Cole só a linha do seu caso e aperte `Enter`.

Depois **feche o Terminal** (`Command + Q`) e abra de novo.

### Passo 4 — Entrar na pasta do editor

Digite `cd` seguido de um espaço (não aperte `Enter` ainda). Depois **arraste a
pasta do editor** (a pasta onde está este arquivo, `COMO-USAR.md`) do Finder para
dentro da janela do Terminal. O caminho da pasta aparece escrito. Agora aperte
`Enter`.

### Passo 5 — Os complementos do editor

```
pip install --break-system-packages -r requirements.txt
```

Isso instala o reconhecimento de fala (que escreve o texto do vídeo) e o
programa das imagens da capa. Pode levar alguns minutos.

Pronto. Pode fechar o Terminal.

> O navegador que desenha os gráficos e a capa é instalado depois, pela própria
> página do editor (veja "Instalar o navegador de gráficos" mais abaixo).

---

## 2. Como abrir o editor

Na pasta do editor, dê **dois cliques em `Abrir Editor`**.

Uma janela do Terminal abre (deixe-a aberta enquanto usa o editor) e, logo
depois, a página do editor aparece no **Google Chrome**. Sem o Chrome instalado,
ela abre no navegador padrão do Mac; o Chrome é o recomendado.

**Na primeira vez**, o Mac pode avisar que o arquivo "não pode ser aberto porque
é de um desenvolvedor não identificado". Nesse caso:

1. Clique em **OK** (ou **Cancelar**) no aviso.
2. Clique com o **botão direito** em `Abrir Editor` (ou `Control` + clique).
3. Escolha **Abrir** e, no aviso, clique em **Abrir** de novo.

Das próximas vezes, dois cliques bastam.

Se você der dois cliques com o editor já aberto, ele só abre a mesma página de
novo; não começa outro.

**Para fechar:** feche a janela do Terminal. Se você só fechar a página no
navegador, o editor fecha sozinho depois de 30 minutos (mas espera terminar
qualquer trabalho que estiver rodando, como gerar o vídeo final).

---

## 3. Os 8 passos

A barra no alto da página mostra os passos. Um passo só abre quando o anterior
está pronto; o que você já fez fica guardado, mesmo se fechar e abrir de novo.

1. **Vídeo** — dê um nome ao Reel e envie o vídeo gravado (arraste o arquivo
   para a área indicada ou clique para escolher).
2. **Cortes** — o editor escreve o texto do vídeo e sugere tirar pausas,
   "éééé" e frases repetidas. Você confere e decide o que sai. Para cortar uma
   palavra, clique nela. Para várias de uma vez, arraste sobre elas, ou clique na
   primeira e segure `Shift` ao clicar na última, ou ligue **Marcar várias palavras**
   (no celular ou no trackpad, é o jeito mais fácil).
3. **Legendas** — confira o texto que aparece na tela e corrija o que precisar.
   Se a janela de Instalação disser "Legendas: usando o modo alternativo", está tudo
   certo: as legendas saem iguais, só que desenhadas de outro jeito (as pílulas
   ficam com cantos retos).
4. **Estilo** — cores, letras e efeitos (veja a seção abaixo).
5. **Preview** — gere e assista a uma prévia do Reel.
6. **Gráficos** — cards de destaque com números, opcionais. Se você não quiser
   nenhum, pule: o Final sai sem eles.
7. **Capa** — opcional. Clique em **Achar quadros**, escolha o quadro em que você
   sorri, escreva o gancho (poucas palavras, em maiúsculas) e clique em **Gerar capa**.
   A imagem sai em 1080 × 1920.
8. **Final** — gere o Reel pronto. O botão **Abrir pasta** mostra o arquivo no
   Finder.

### O passo Estilo

Quatro abas com cartões. Cada cartão mostra um quadro do seu próprio vídeo já com
aquele estilo:

- **Paletas** — as cores do Reel (fundo, texto, destaque).
- **Fontes** — as letras disponíveis. Só aparecem as que o editor consegue usar hoje.
- **Legendas** — o desenho da legenda; abaixo dos cartões, escolha a posição
  (em baixo ou no meio) e o tamanho (pequena, média ou grande).
- **Efeitos** — pequenos efeitos animados (calendário, palavra em destaque,
  polaroides...). Clique em **Adicionar ao vídeo**, preencha o formulário (quando
  entra, quanto dura) e salve. Os efeitos adicionados aparecem numa lista, com
  botão para remover.

Em cada cartão há dois botões: **Usar** marca o estilo para o seu Reel (ainda não
muda nada) e **Mais parecido com este** mostra variações bem próximas, só de cor
ou de tamanho. Quando estiver satisfeito, clique em **Aplicar estilo**: o editor
refaz o preview com as escolhas. Enquanto você não aplicar, nada é gravado.

**Para ter mais fontes:** copie o arquivo `.ttf` para a pasta `assets/fonts` do
editor. Hoje o editor só desenha com a Poppins; outra fonte aparece na aba, mas
com o aviso de que ainda não pode ser usada.

**Para ter mais paletas, legendas ou efeitos:** copie a pasta de um item
parecido dentro de `banco/` (por exemplo `banco/paletas/marca`), dê um novo nome
à cópia e troque o nome e os valores no arquivo `manifesto.json`. O passo a passo
completo está em `banco/README.md`. Item com erro simplesmente não aparece (a tela
avisa quantos foram ignorados e por quê).

### Instalar o navegador de gráficos

Gráficos, efeitos e capa são desenhados por um navegador interno (Chromium).
Se o botão **Instalação**, no alto da página, mostrar **Instalar o navegador de
gráficos**, clique nele e espere alguns minutos com a página aberta. Se preferir
pelo Terminal (precisa do `node`, da parte 1), cole:

```
npm i -g playwright && npx playwright install chromium
```

Sem ele, o editor continua funcionando; só ficam indisponíveis efeitos, gráficos
e capa.

---

## 4. Onde ficam os arquivos

Tudo fica dentro da pasta do editor, em `projects`, uma pasta por Reel:

```
projects/<nome do Reel>/saida/preview.mp4   a prévia
projects/<nome do Reel>/saida/final.mp4     o Reel pronto para postar
```

O nome da pasta é o nome que você deu ao Reel, em letras minúsculas, sem
acentos e com hífens no lugar dos espaços ("Férias 2026" vira `ferias-2026`). O vídeo original que você enviou fica na pasta do
Reel, com o nome `entrada`.

---

## 5. Limites

- Um Reel de cada vez: trabalhe em um projeto por vez, numa só pessoa.
- Vídeos `.mp4`, `.mov`, `.m4v`, `.webm` ou `.mkv`, até 4 GB.
- Efeitos têm duração máxima (de segundos) e ficam numa área segura da tela,
  longe do topo e da faixa da legenda; o formulário avisa se algo passar do limite.
- Se mudar os cortes ou as legendas depois de gerar o preview, a tela avisa que o
  preview está desatualizado: gere de novo.
- Nada é publicado sozinho: você baixa o Reel e a capa e posta por conta própria.

## 6. Se algo der errado

**A página não abre.**
Olhe a janela do Terminal que abriu com o editor: ela mostra o endereço da
página (começa com `http://127.0.0.1:`). Copie o endereço inteiro e cole no
Google Chrome. Se a janela do Terminal disser que falta instalar algo, siga o que
ela diz (ou refaça a parte 1 deste guia) e dê dois cliques em `Abrir Editor` de
novo.

**A página mostra "Acesso negado" ou "A chave de acesso não vale mais".**
O endereço foi digitado à mão, copiado de uma vez antiga ou o editor foi
reiniciado. Feche a aba e dê dois cliques em `Abrir Editor`.

**A página diz "Sem conexão com o editor".**
O editor foi fechado (a janela do Terminal foi fechada ou ele fechou sozinho
depois de 30 minutos sem a página). Dê dois cliques em `Abrir Editor`; o que você
já fez continua guardado.

**O vídeo não envia.**
- Use um vídeo `.mp4`, `.mov`, `.m4v`, `.webm` ou `.mkv`.
- Se a mensagem disser que o arquivo "não parece ser um vídeo", exporte de novo
  pelo celular ou pelo app de fotos e tente outra vez.
- Se disser que o arquivo é grande demais, o limite é 4 GB.
- Se aparecer um aviso sobre o conversor de vídeo, abra o botão **Instalação**
  no alto da página e siga o que ele indica.

**O editor fechou sozinho.**
Ele fecha depois de 30 minutos sem a página aberta, se não houver trabalho rodando.
Nada se perde: dê dois cliques em `Abrir Editor` e continue de onde parou. Com a página
aberta, ele não fecha.

**Um passo mostra erro.**
Clique em **Detalhes** para ver o que aconteceu e tente de novo. Se continuar,
abra o botão **Instalação**: ele mostra o que falta instalar e o comando para
copiar.

**O Terminal diz que a porta já está em uso.**
Outro programa está usando o mesmo endereço. Feche a janela e dê dois cliques em
`Abrir Editor` de novo.

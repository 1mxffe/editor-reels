#!/bin/bash
# Abre o Editor de Reels: dois cliques neste arquivo no Finder.
# Acha um Python 3.11 ou mais novo, sobe o editor e abre a pagina no Google Chrome.
# Sem parar no primeiro erro: as mensagens abaixo precisam aparecer mesmo quando algo falha.

cd "$(dirname "$0")" || exit 1

HOMEBREW_PY="/opt/homebrew/opt/python@3.13/libexec/bin/python3"
VERSAO_OK='import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'

PY=""
if command -v python3 >/dev/null 2>&1 && python3 -c "$VERSAO_OK" >/dev/null 2>&1; then
  PY="python3"
elif [ -x "$HOMEBREW_PY" ] && "$HOMEBREW_PY" -c "$VERSAO_OK" >/dev/null 2>&1; then
  PY="$HOMEBREW_PY"
fi

if [ -z "$PY" ]; then
  echo ""
  echo "Falta instalar um programa para o editor funcionar."
  echo ""
  echo "1. Se ainda não tem o Homebrew, abra o site https://brew.sh,"
  echo "   copie o comando que aparece lá, cole aqui no Terminal e aperte Enter."
  echo ""
  echo "2. Depois copie a linha abaixo, cole aqui no Terminal e aperte Enter:"
  echo ""
  echo "   brew install python@3.13 ffmpeg node git"
  echo ""
  echo "3. Quando terminar, feche esta janela e dê dois cliques em Abrir Editor de novo."
  echo "   O passo a passo completo está no arquivo COMO-USAR.md, nesta mesma pasta."
  echo ""
  read -p "Pressione Enter para fechar esta janela. "
  exit 1
fi

"$PY" -I app/server.py "$@"
CODIGO=$?
if [ "$CODIGO" -ne 0 ]; then
  echo ""
  echo "O editor não conseguiu abrir. A mensagem acima explica o motivo."
  echo "Veja a parte \"Se algo der errado\" do arquivo COMO-USAR.md, nesta mesma pasta."
  read -p "Pressione Enter para fechar esta janela. "
fi
exit "$CODIGO"

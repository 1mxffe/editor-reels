"""Junta varios trechos gravados (``clipes/``) num unico ``entrada.mp4``.

Layout do projeto (``projects/<reel>/``)::

    clipes/<NN>-<nome>.<ext>   um arquivo por trecho enviado (NN cresce a cada envio)
    clipes.json                {"clipes": [{"arquivo","nome","duracao"}], "montado": null | {...}}
                               a ordem da lista e a ordem do video; corrompido -> ignorado e
                               reconstruido da pasta pelo nome do arquivo
    entrada.mp4                resultado da montagem (o resto do editor so ve este arquivo)

Cada trecho e normalizado (cabe em 1080x1920 sem distorcer, faixas pretas; 30 fps; H.264
yuv420p; audio AAC estereo a 48 kHz, com silencio se o trecho nao tem audio) e os trechos
sao emendados. A saida vai para um temporario na mesma pasta e so entao troca ``entrada.mp4``;
as outras ``entrada.<ext>`` e os arquivos derivados do video anterior (so com ``--confirmar``)
saem depois. Se o primeiro trecho nao passa na normalizacao nada e apagado.

Uso: python3 -I scripts/juntar.py <projeto> [--confirmar]
Saida: 0 ok; 1 erro (mensagem ``erro: ...``, em portugues, sem caminhos).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unicodedata  # noqa: E402

import common  # noqa: E402

EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
MAX_CLIPES = 40
MAX_DURACAO = 30 * 60.0  # segundos, soma de todos os trechos
LARGURA, ALTURA, FPS = 1080, 1920, 30
ARQ_RE = re.compile(r"[0-9]{2,}-[a-z0-9][a-z0-9._-]{0,80}\.(?:mp4|mov|m4v|webm|mkv)")
MAX_JSON = 256 * 1024
TIMEOUT_SONDA = 60
TIMEOUT_FFMPEG = 3600

# arquivos que dependem do video anterior (rotulo mostrado -> nomes)
DERIVADOS = (
    ("cortes", ("transcricao.json", "cortes.json", "revisao.json", "review.json")),
    ("legendas", ("legendas.json", "etapas.json")),
    ("gráficos", ("graficos.json",)),
)
ROTULO_SAIDA = "vídeos gerados"


class JuntarErro(Exception):
    """Erro com mensagem em portugues, pronta para o usuario."""


# ------------------------------------------------------------------ nomes
def nome_exibicao(bruto: str) -> str:
    """Nome mostrado na lista: so o ultimo pedaco do caminho, sem extensao nem controles."""
    base = re.split(r"[\\/]", str(bruto or ""))[-1]
    base = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", " ", base)
    stem = os.path.splitext(base)[0] if os.path.splitext(base)[1].lower() in EXT_VIDEO else base
    stem = re.sub(r"\s+", " ", stem).strip(" .-")
    return (stem or "Trecho")[:80]


def _radical_seguro(nome: str) -> str:
    texto = unicodedata.normalize("NFKD", nome)
    texto = "".join(c for c in texto if not unicodedata.combining(c)).lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:60].strip("-")
    return texto or "trecho"


def novo_arquivo(clipes: list[dict], pasta: Path, nome: str, ext: str) -> str:
    """Nome livre ``NN-radical.ext`` (NN = maior numero ja usado + 1)."""
    usados = [int(a.split("-", 1)[0]) for a in (c["arquivo"] for c in clipes)]
    try:
        usados += [int(p.name.split("-", 1)[0]) for p in pasta.iterdir() if ARQ_RE.fullmatch(p.name)]
    except OSError:
        pass
    n = (max(usados) if usados else 0) + 1
    return f"{n:02d}-{_radical_seguro(nome_exibicao(nome))}{ext.lower()}"


# ------------------------------------------------------------------ lista
def pasta_clipes(d: Path, criar: bool = False):
    """``clipes/`` do projeto (pasta de verdade, sem link) ou None."""
    d = Path(d)
    p = d / "clipes"
    if criar:
        try:
            p.mkdir(exist_ok=True)
        except OSError:
            return None
    try:
        if p.is_symlink() or not p.is_dir() or p.resolve().parent != d.resolve():
            return None
    except (OSError, RuntimeError):
        return None
    return p


def _ler_json(path: Path):
    try:
        return json.loads(common.ler_limitado(path, MAX_JSON).decode("utf-8"))
    except (OSError, ValueError, RecursionError, MemoryError, common.LeituraRecusada):
        return None


def _nome_do_arquivo(arquivo: str) -> str:
    return arquivo.split("-", 1)[1].rsplit(".", 1)[0]


def _arquivo_ok(pasta: Path, arquivo) -> bool:
    if not isinstance(arquivo, str) or not ARQ_RE.fullmatch(arquivo):
        return False
    p = pasta / arquivo
    return p.is_file() and not p.is_symlink()


def ler(d: Path) -> tuple[list[dict], dict | None]:
    """(clipes, montado) do projeto, conciliados com a pasta. Nunca levanta.

    Entradas cujo arquivo sumiu saem da lista; arquivos validos da pasta que nao estao na
    lista (lista corrompida/perdida) entram no fim, em ordem de nome."""
    pasta = pasta_clipes(d)
    if pasta is None:
        return [], None
    dados = _ler_json(Path(d) / "clipes.json")
    itens, montado = [], None
    if isinstance(dados, dict):
        bruto = dados.get("clipes")
        if isinstance(bruto, list):
            for c in bruto:
                if isinstance(c, dict) and _arquivo_ok(pasta, c.get("arquivo")):
                    nome = c.get("nome") if isinstance(c.get("nome"), str) and c["nome"].strip() else None
                    dur = c.get("duracao")
                    itens.append({"arquivo": c["arquivo"],
                                  "nome": nome_exibicao(nome) if nome else _nome_do_arquivo(c["arquivo"]),
                                  "duracao": float(dur) if common.is_num(dur) and dur > 0 else None})
        if isinstance(dados.get("montado"), dict):
            montado = dados["montado"]
    vistos = {c["arquivo"] for c in itens}
    unicos = []
    for c in itens:  # sem repetidos
        if c["arquivo"] in vistos:
            vistos.discard(c["arquivo"])
            unicos.append(c)
    itens = unicos
    listados = {c["arquivo"] for c in itens}
    try:
        soltos = sorted(p.name for p in pasta.iterdir() if p.name not in listados
                        and _arquivo_ok(pasta, p.name))
    except OSError:
        soltos = []
    for a in soltos:
        itens.append({"arquivo": a, "nome": _nome_do_arquivo(a), "duracao": None})
    return itens, montado


def gravar(d: Path, clipes: list[dict], montado: dict | None) -> None:
    """Grava ``clipes.json`` de forma atomica."""
    lista = [{"arquivo": c["arquivo"], "nome": c["nome"],
              **({"duracao": round(float(c["duracao"]), 3)} if c.get("duracao") else {})}
             for c in clipes]
    common.write_json_atomic(Path(d) / "clipes.json", {"clipes": lista, "montado": montado})


def impressao_clipes(d: Path, clipes: list[dict]) -> str:
    """Resumo estavel dos trechos e da ordem (nome do arquivo + tamanho), para saber se a
    montagem ficou velha."""
    pasta = Path(d) / "clipes"
    itens = []
    for c in clipes:
        try:
            tam = (pasta / c["arquivo"]).stat().st_size
        except OSError:
            tam = -1
        itens.append([c["arquivo"], tam])
    return hashlib.sha256(json.dumps(itens).encode("utf-8")).hexdigest()


def _assinatura_entrada(d: Path):
    try:
        st = (Path(d) / "entrada.mp4").stat()
    except OSError:
        return None
    return {"tamanho": st.st_size, "mtime_ns": st.st_mtime_ns}


def situacao_montagem(d: Path, clipes: list[dict], montado) -> dict:
    """{"montado": o entrada.mp4 de hoje veio da montagem, "desatualizada": a lista/ordem
    mudou depois}. Trocar o video pelo envio direto desfaz o ``montado``."""
    ok = (isinstance(montado, dict) and _assinatura_entrada(d) is not None
          and montado.get("entrada") == _assinatura_entrada(d))
    velha = bool(ok and montado.get("impressao") != impressao_clipes(d, clipes))
    return {"montado": bool(ok), "desatualizada": velha}


# ------------------------------------------------------------ derivados
def derivados(d: Path) -> list[Path]:
    """Arquivos do projeto que dependem do video atual (nunca estilo, materiais, capa, clipes)."""
    d = Path(d)
    achados = []
    for _rotulo, nomes in DERIVADOS:
        achados += [d / n for n in nomes if (d / n).is_file() or (d / n).is_symlink()]
    saida = d / "saida"
    if saida.is_dir() and not saida.is_symlink():
        try:
            achados += [p for p in saida.iterdir() if p.is_file() or p.is_symlink()]
        except OSError:
            pass
    return achados


def perde(d: Path) -> list[str]:
    """O que a nova montagem apaga, em portugues (lista vazia = nada a confirmar)."""
    d = Path(d)
    itens = []
    for rotulo, nomes in DERIVADOS:
        if any((d / n).is_file() or (d / n).is_symlink() for n in nomes):
            itens.append(rotulo)
    saida = d / "saida"
    try:
        if saida.is_dir() and not saida.is_symlink() and any(
                not p.name.startswith(".") and (p.is_file() or p.is_symlink()) for p in saida.iterdir()):
            itens.append(ROTULO_SAIDA)
    except OSError:
        pass
    return itens


def apagar_derivados(d: Path) -> None:
    for p in derivados(d):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            raise JuntarErro("não foi possível limpar os cortes e legendas antigos") from None


# ------------------------------------------------------------------ ffmpeg
def sondar(caminho: Path) -> dict:
    """{"duracao", "audio"} de um video; JuntarErro se nao for video legivel."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:format=duration",
             "-of", "json", "-i", str(caminho)],
            capture_output=True, text=True, timeout=TIMEOUT_SONDA)
    except FileNotFoundError:
        raise JuntarErro("ffprobe não encontrado — rode a instalação") from None
    except subprocess.TimeoutExpired:
        raise JuntarErro("a verificação do vídeo demorou demais") from None
    if proc.returncode != 0:
        raise JuntarErro("o arquivo não parece ser um vídeo")
    try:
        info = json.loads(proc.stdout)
        tipos = [s.get("codec_type") for s in info.get("streams") or []]
        dur = float((info.get("format") or {}).get("duration"))
    except (ValueError, TypeError, AttributeError):
        raise JuntarErro("o arquivo não parece ser um vídeo") from None
    if "video" not in tipos or not 0 < dur < float("inf"):
        raise JuntarErro("o arquivo não parece ser um vídeo")
    return {"duracao": dur, "audio": "audio" in tipos}


def _ffmpeg(args: list[str], onde: str) -> None:
    cmd = ["ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_FFMPEG)
    except FileNotFoundError:
        raise JuntarErro("ffmpeg não encontrado — rode a instalação") from None
    except subprocess.TimeoutExpired:
        raise JuntarErro(f"{onde} demorou demais") from None
    if proc.returncode != 0:
        raise JuntarErro(f"não foi possível preparar {onde}")


def normalizar(origem: Path, destino: Path, tem_audio: bool, onde: str) -> None:
    """Re-codifica o trecho para o formato comum da montagem (ver docstring do modulo)."""
    video = (f"scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=decrease,"
             f"pad={LARGURA}:{ALTURA}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},format=yuv420p")
    audio = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad"
    entradas = ["-i", str(origem)]
    mapas = ["-map", "0:v:0"]
    if tem_audio:
        mapas += ["-map", "0:a:0"]
    else:
        entradas += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        mapas += ["-map", "1:a:0"]
    _ffmpeg([*entradas, *mapas, "-vf", video, "-af", audio, "-shortest",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k",
             "-movflags", "+faststart", "-f", "mp4", str(destino)], onde)


def emendar(partes: list[Path], lista: Path, destino: Path) -> None:
    """Concatena partes ja normalizadas (mesmos parametros) sem recodificar."""
    lista.write_text("".join(f"file '{p.name}'\n" for p in partes), encoding="utf-8")
    _ffmpeg(["-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy",
             "-movflags", "+faststart", "-f", "mp4", str(destino)], "o vídeo montado")


# ------------------------------------------------------------------ montagem
def conferir(d: Path) -> tuple[list[dict], float]:
    """Valida a lista (quantidade, arquivos, duracao total) e devolve (clipes, total).
    Preenche ``duracao`` e ``audio`` de cada trecho. JuntarErro se algo estiver fora."""
    clipes, _ = ler(d)
    if not clipes:
        raise JuntarErro("envie pelo menos um trecho antes de montar o vídeo")
    if len(clipes) > MAX_CLIPES:
        raise JuntarErro(f"são trechos demais (máximo {MAX_CLIPES})")
    pasta = Path(d) / "clipes"
    total = 0.0
    for i, c in enumerate(clipes, 1):
        info = sondar(pasta / c["arquivo"])
        c["duracao"], c["audio"] = info["duracao"], info["audio"]
        total += info["duracao"]
    if total > MAX_DURACAO:
        raise JuntarErro(f"o vídeo montado passaria de {int(MAX_DURACAO // 60)} minutos; remova alguns trechos")
    return clipes, total


def montar(d: Path, confirmar: bool = False) -> None:
    d = Path(d)
    for velho in d.glob(".juntar-*"):  # sobras de uma montagem interrompida
        shutil.rmtree(velho, ignore_errors=True)
    clipes, total = conferir(d)
    if derivados(d) and not confirmar and perde(d):
        raise JuntarErro("montar um vídeo novo apaga os cortes e legendas atuais; confirme antes")
    pasta = d / "clipes"
    tmp = Path(tempfile.mkdtemp(dir=d, prefix=".juntar-"))
    try:
        partes = []
        n = len(clipes)
        for i, c in enumerate(clipes, 1):
            print(f"Preparando o trecho {i} de {n}…", flush=True)
            parte = tmp / f"p{i:02d}.mp4"
            normalizar(pasta / c["arquivo"], parte, c["audio"], f"o trecho {i} ({c['nome']})")
            partes.append(parte)
            if i == 1 and confirmar:  # primeiro trecho passou: agora o video antigo pode sair
                apagar_derivados(d)
        final = tmp / "montado.mp4"
        if n == 1:
            os.replace(partes[0], final)
        else:
            print("Juntando os trechos…", flush=True)
            emendar(partes, tmp / "lista.txt", final)
        os.replace(final, d / "entrada.mp4")
        for ext in EXT_VIDEO:  # as outras entradas (so depois do sucesso)
            if ext != ".mp4":
                (d / f"entrada{ext}").unlink(missing_ok=True)
        gravar(d, [{k: c[k] for k in ("arquivo", "nome", "duracao")} for c in clipes],
               {"impressao": impressao_clipes(d, clipes), "entrada": _assinatura_entrada(d),
                "duracao": round(total, 3)})
        print(f"Pronto: {n} trecho(s), {total:.1f} s.", flush=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--confirmar"]
    confirmar = len(args) != len(argv)
    if len(args) != 1:
        print("uso: juntar.py <projeto> [--confirmar]", file=sys.stderr)
        return 1
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # cancelar: o finally limpa o temporario
    try:
        montar(Path(args[0]), confirmar)
    except JuntarErro as e:
        print(f"erro: {e}", file=sys.stderr, flush=True)
        return 1
    except OSError:
        print("erro: não foi possível gravar o vídeo montado", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

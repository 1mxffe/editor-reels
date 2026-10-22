"""Candidatos de capa: quadros nítidos e espalhados do vídeo, ou uma foto enviada.

A capa usa um retrato do advogado sorrindo para a câmera. Este script NÃO
detecta rosto nem sorriso (não há biblioteca de visão no ambiente e nenhuma deve
ser instalada): ele escolhe quadros nítidos, bem espalhados no vídeo, e a
PESSOA escolhe qual mostra o sorriso desejado. O PNG escolhido segue para a
composição da capa (``cover_compose``, próximo passo).

Vídeo (``candidates``): a duração vem do ffprobe; a linha do tempo, sem os 5 %
iniciais e finais (a pessoa ainda está se ajeitando), é dividida em ``n``
trechos iguais; em cada trecho o ffmpeg extrai, numa única chamada, o primeiro
quadro em cada marca de ~0,4 s (no máximo ~60 amostras no total; o mesmo quadro
que a extração final no instante da marca devolve), reduzido a 480 px de largura.
Cada amostra recebe:

* nitidez = variância de um filtro Laplaciano 3x3 (``ImageFilter.Kernel``) na
  região central em tons de cinza (60 % do meio da largura x faixa de 5 % a
  75 % da altura, onde costuma estar o rosto);
* rejeição se a luminância média do quadro for < 25 (preto) ou > 235
  (estourado);
* rejeição se for quase igual (diferença média absoluta < 0,3 de 255 numa
  miniatura 64x64 da MESMA região central) a um candidato já escolhido: em vídeo
  de tripé só o rosto muda, e o sorriso não pode virar "duplicado".

Escolhe-se o melhor quadro de cada trecho que fique a pelo menos 1 s (ou metade
de um trecho, se menor) dos já escolhidos. Se um trecho não tem quadro
aceitável, o lugar é preenchido com a melhor amostra restante de qualquer
trecho, com a mesma distância mínima. Só então os quadros escolhidos são extraídos em resolução cheia
(ffmpeg com autorrotação ligada: vídeo de celular com metadado de rotação sai
em pé) como ``candidato-1.png`` ... ``candidato-n.png`` em ordem de tempo.

Vídeo curto: cabe no máximo 1 candidato por segundo, então ``n`` cai para
``max(1, min(n, floor(duração)))`` com um aviso em stderr. Menos candidatos do
que o pedido só acontece com aviso em stderr. Nenhum quadro aceitável em todo o
vídeo é erro. Só Pillow e ffmpeg (numpy não é exigido).

Foto (``from_photo``): abre com Pillow, aplica a orientação EXIF, exige lado
curto >= 600 px, achata transparência sobre branco, converte para RGB e grava
``foto.png``.

Todo erro esperado é ``CoverError`` (a CLI o transforma em ``common.fail``,
código 1). Nada parcial fica para trás: cada PNG é escrito num temporário de nome
único (``common.atomic_write``) e renomeado só quando todos estão prontos; pasta de
amostras temporária sempre removida.

Uso: python3 -I scripts/cover_frames.py video <video> <pasta_saida> [--n 3]
     python3 -I scripts/cover_frames.py photo <foto> <pasta_saida>
Saída: um caminho por linha.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contextlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402

from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat  # noqa: E402

import common  # noqa: E402

SAMPLE_WIDTH = 480        # largura das amostras e da medida de nitidez
SAMPLE_STEP = 0.4         # s entre amostras
MAX_SAMPLES = 60          # teto de amostras em vídeos longos
EDGE_TRIM = 0.05          # fração ignorada no início e no fim
MIN_BRIGHT, MAX_BRIGHT = 25, 235
DUP_DIFF = 0.3            # diferença média (0-255) na região central abaixo da qual é quase duplicado
FALLBACK_GAP = 1.0        # s mínimos entre um candidato de reserva e os escolhidos
MIN_PHOTO_SIDE = 600
CROP_X = (0.20, 0.80)     # região central: 60 % do meio da largura
CROP_Y = (0.05, 0.75)     # e 70 % da altura, a partir de perto do topo

_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


class CoverError(Exception):
    """Erro claro para o usuário (arquivo ausente, sem vídeo, foto pequena...)."""


# ---------------------------------------------------------------- ffmpeg

def _tool(cmd: list[str]) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise CoverError(f"comando não encontrado: {cmd[0]} (rode scripts/doctor.py)")
    except OSError as e:
        raise CoverError(f"não foi possível executar {cmd[0]}: {e}")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-5:])
        raise CoverError(f"{cmd[0]} falhou (código {proc.returncode}): {tail}")
    return proc


def _ffmpeg(args: list) -> None:
    _tool(["ffmpeg", "-v", "error", "-nostdin", "-y", *map(str, args)])


def _probe(video: Path) -> float:
    """Duração em segundos; CoverError se não há vídeo ou não dá para ler."""
    if not video.is_file():
        raise CoverError(f"vídeo não encontrado: {video}")
    out = _tool(["ffprobe", "-v", "error", "-print_format", "json", "-show_entries",
                 "stream=codec_type,duration:stream_disposition=attached_pic:format=duration",
                 str(video)]).stdout
    try:
        info = json.loads(out)
    except ValueError:
        raise CoverError(f"não foi possível ler o arquivo: {video}")
    streams = [s for s in info.get("streams", [])
               if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not streams:
        raise CoverError("o arquivo não tem vídeo")
    for raw in (info.get("format", {}).get("duration"), streams[0].get("duration")):
        try:
            dur = float(raw)
        except (TypeError, ValueError):
            continue
        if common.is_num(dur) and dur > 0:
            return dur
    raise CoverError("não foi possível obter a duração do vídeo")


# ---------------------------------------------------------------- medidas

def sharpness(img: Image.Image) -> float:
    """Variância do Laplaciano na região central, em cinza, a 480 px de largura."""
    g = img.convert("L")
    if g.width != SAMPLE_WIDTH:
        g = g.resize((SAMPLE_WIDTH, max(1, round(g.height * SAMPLE_WIDTH / g.width))),
                     Image.Resampling.BOX if g.width > SAMPLE_WIDTH else Image.Resampling.BILINEAR)
    w, h = g.size
    box = _central_box(w, h)
    if box[2] - box[0] < 3 or box[3] - box[1] < 3:
        box = (0, 0, w, h)
    region = g.crop(box)
    if region.width < 3 or region.height < 3:
        return 0.0
    lap = region.filter(_LAPLACIAN)
    lap = lap.crop((1, 1, lap.width - 1, lap.height - 1))  # a borda de 1 px não é filtrada
    return float(ImageStat.Stat(lap).var[0])


def _brightness(img: Image.Image) -> float:
    return float(ImageStat.Stat(img.convert("L")).mean[0])


def _central_box(w: int, h: int) -> tuple[int, int, int, int]:
    return int(w * CROP_X[0]), int(h * CROP_Y[0]), int(w * CROP_X[1]), int(h * CROP_Y[1])


def _thumb(img: Image.Image) -> Image.Image:
    """Miniatura 64x64 da MESMA região central da nitidez (onde fica o rosto): no
    tripé o resto do quadro não muda, e o sorriso tem que contar."""
    rgb = img.convert("RGB")
    box = _central_box(*rgb.size)
    if box[2] - box[0] >= 4 and box[3] - box[1] >= 4:
        rgb = rgb.crop(box)
    return rgb.resize((64, 64), Image.Resampling.BOX)


def _thumb_diff(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


# ---------------------------------------------------------------- vídeo

class _Sample:
    __slots__ = ("seg", "t", "score", "ok", "thumb")

    def __init__(self, seg, t, score, ok, thumb):
        self.seg, self.t, self.score, self.ok, self.thumb = seg, t, score, ok, thumb


def _sample_segment(video: Path, seg: int, start: float, length: float, step: float,
                    workdir: Path) -> list[_Sample]:
    count = max(1, int(length / step + 1e-9))
    pattern = workdir / f"s{seg}-%04d.png"
    # Amostra k = o PRIMEIRO quadro em t >= start + k*step: e o mesmo quadro que a
    # extracao final (-ss <t>) devolve. (O filtro fps pegava o ultimo quadro antes
    # do meio do intervalo, ate step/2 depois do rotulo: outro quadro que o medido.)
    _ffmpeg(["-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", video, "-an",
             "-vf", f"select='gte(t\\,selected_n*{step:.6f})',scale=min({SAMPLE_WIDTH}\\,iw):-2",
             "-fps_mode", "passthrough", "-frames:v", count, "-compression_level", 1, pattern])
    samples = []
    for k in range(1, count + 1):
        path = workdir / f"s{seg}-{k:04d}.png"
        if not path.is_file():
            break
        with Image.open(path) as im:
            im.load()
            bright = _brightness(im)
            samples.append(_Sample(seg, round(start + (k - 1) * step, 3), sharpness(im),
                                   MIN_BRIGHT <= bright <= MAX_BRIGHT, _thumb(im)))
        path.unlink()
    return samples


def _is_dup(sample: _Sample, chosen: list[_Sample]) -> bool:
    return any(_thumb_diff(sample.thumb, c.thumb) < DUP_DIFF for c in chosen)


def _created_chain(path: Path) -> list[Path]:
    """Pastas que `mkdir -p path` vai criar, da mais funda para a mais rasa."""
    chain = []
    p = path
    while not p.exists() and p != p.parent:
        chain.append(p)
        p = p.parent
    return chain


def candidates(video: Path, out_dir: Path, n: int = 3) -> list[Path]:
    """Até ``n`` PNG (``out_dir/candidato-1.png`` ...), nítidos, em ordem de tempo."""
    video, out_dir = Path(video), Path(out_dir)
    if n < 1:
        raise CoverError("n deve ser pelo menos 1")
    duration = _probe(video)
    n_eff = max(1, min(n, math.floor(duration)))
    if n_eff < n:
        print(f"aviso: vídeo curto ({duration:.1f} s): {n_eff} candidato(s) em vez de {n}",
              file=sys.stderr)
    if out_dir.exists() and not out_dir.is_dir():
        raise CoverError(f"a saída não é uma pasta: {out_dir}")

    lo, hi = duration * EDGE_TRIM, duration * (1 - EDGE_TRIM)
    seg_len = (hi - lo) / n_eff
    step = max(SAMPLE_STEP, (hi - lo) / MAX_SAMPLES)
    work = Path(tempfile.mkdtemp(prefix="cover-frames-"))
    try:
        samples: list[_Sample] = []
        for i in range(n_eff):
            samples += _sample_segment(video, i, lo + i * seg_len, seg_len, step, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    usable = [s for s in samples if s.ok]
    if not usable:
        raise CoverError("nenhum quadro utilizável no vídeo (tudo escuro, estourado ou ilegível)")
    usable.sort(key=lambda s: -s.score)

    chosen: dict[int, _Sample] = {}
    gap = min(FALLBACK_GAP, seg_len / 2)
    for i in range(n_eff):  # 1o passo: o melhor quadro de cada trecho, longe dos ja escolhidos
        for s in usable:
            picked = list(chosen.values())
            if s.seg == i and not _is_dup(s, picked) and all(abs(s.t - c.t) >= gap for c in picked):
                chosen[i] = s
                break
    for i in range(n_eff):  # 2o passo: trecho sem quadro aceitável usa a melhor reserva
        if i in chosen:
            continue
        picked = list(chosen.values())
        for s in usable:
            if s not in picked and not _is_dup(s, picked) \
                    and all(abs(s.t - c.t) >= gap for c in picked):
                chosen[i] = s
                break
    final = sorted(chosen.values(), key=lambda s: s.t)
    if len(final) < n_eff:
        print(f"aviso: só foi possível escolher {len(final)} de {n_eff} candidatos "
              f"distintos e nítidos", file=sys.stderr)

    created = _created_chain(out_dir)
    try:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise CoverError(f"não foi possível criar {out_dir}: {e}")
        paths = []
        try:
            # um temporário único por candidato; todos renomeados só no fim (ou apagados)
            with contextlib.ExitStack() as stack:
                for i, s in enumerate(final, 1):
                    dest = out_dir / f"candidato-{i}.png"
                    tmp = stack.enter_context(common.atomic_write(dest, suffix=".png"))
                    _ffmpeg(["-ss", f"{s.t:.3f}", "-i", video, "-an", "-frames:v", 1,
                             "-c:v", "png", "-f", "image2", "-update", 1, tmp])
                    if tmp.stat().st_size == 0:
                        raise CoverError(f"o ffmpeg não extraiu o quadro em {s.t:.1f} s")
                    paths.append(dest)
        except OSError as e:
            raise CoverError(f"não foi possível gravar os candidatos em {out_dir}: {e}") from None
    except BaseException:
        for d in created:  # só o que esta chamada criou, e só se ficou vazio
            try:
                d.rmdir()
            except OSError:
                break
        raise
    for old in out_dir.glob("candidato-*.png"):  # sobras de uma execução com n maior
        m = re.fullmatch(r"candidato-(\d+)\.png", old.name)
        if m and int(m.group(1)) > len(paths):
            old.unlink(missing_ok=True)
    return paths


# ---------------------------------------------------------------- foto

def load_photo(photo: Path) -> Image.Image:
    """Abre a foto pelo conteúdo (a extensão não importa): orientação EXIF aplicada,
    lado menor >= 600 px, transparência achatada sobre branco, cinza de 16 bits levado a
    8 bits, RGB. Não grava nada."""
    photo = Path(photo)
    if not photo.is_file():
        raise CoverError(f"foto não encontrada: {photo}")
    try:
        with Image.open(photo) as im:
            im.load()
            img = ImageOps.exif_transpose(im)
            if img is im:
                img = im.copy()
    except Exception as e:  # formato desconhecido, truncado, bomba de descompressão...
        raise CoverError(f"o arquivo não é uma imagem que dê para abrir ({photo.name}): {e}")
    short = min(img.size)
    if short < MIN_PHOTO_SIDE:
        raise CoverError(f"foto pequena demais: {img.width}x{img.height}; "
                         f"o lado menor precisa ter pelo menos {MIN_PHOTO_SIDE} px")
    if img.mode.startswith("I"):  # cinza de 16/32 bits: convert("RGB") satura em branco
        img = img.convert("I")
        if img.getextrema()[1] > 255:
            img = img.point(lambda v: v * (1 / 256))
        img = img.convert("L")
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        base = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        img = Image.alpha_composite(base, rgba).convert("RGB")  # transparente vira branco
    else:
        img = img.convert("RGB")
    return img


def from_photo(photo: Path, out_dir: Path) -> Path:
    """Valida a foto enviada e grava ``out_dir/foto.png`` (RGB, em pé)."""
    photo, out_dir = Path(photo), Path(out_dir)
    img = load_photo(photo)
    created = _created_chain(out_dir)
    dest = out_dir / "foto.png"
    try:
        if out_dir.exists() and not out_dir.is_dir():
            raise CoverError(f"a saída não é uma pasta: {out_dir}")
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            with common.atomic_write(dest, suffix=".png") as tmp:
                img.save(tmp, format="PNG")
        except OSError as e:
            raise CoverError(f"não foi possível gravar {dest}: {e}")
    except BaseException:
        for d in created:
            try:
                d.rmdir()
            except OSError:
                break
        raise
    return dest


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> None:
    parser = common.UsageParser(prog="cover_frames.py",
                                     description="Candidatos de capa a partir de vídeo ou foto.")
    sub = parser.add_subparsers(dest="mode", required=True)
    pv = sub.add_parser("video", help="extrai quadros nítidos do vídeo")
    pv.add_argument("video", type=Path)
    pv.add_argument("out_dir", type=Path)
    pv.add_argument("--n", type=int, default=3, help="quantidade de candidatos (padrão 3)")
    pp = sub.add_parser("photo", help="valida e normaliza uma foto enviada")
    pp.add_argument("photo", type=Path)
    pp.add_argument("out_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "video":
            paths = candidates(args.video, args.out_dir, n=args.n)
        else:
            paths = [from_photo(args.photo, args.out_dir)]
    except CoverError as e:
        common.fail(str(e))
    for p in paths:
        print(p)


if __name__ == "__main__":
    main()

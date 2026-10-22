import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def build_sample(out: Path) -> Path:
    """Gera um video vertical de 6 s (1080x1920) com tom de audio e ~1 s de silencio no meio.

    Sem ffmpeg no PATH o teste e pulado (nao falha); a saida do ffmpeg e
    capturada e vai no CalledProcessError em vez de sujar o terminal.
    """
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg ausente")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=30:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=6",
        "-af", "volume=enable='between(t,2.5,3.5)':volume=0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out


@pytest.fixture
def make_sample(tmp_path):
    return build_sample(tmp_path / "sample.mp4")

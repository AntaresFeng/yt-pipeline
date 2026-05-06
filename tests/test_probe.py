"""probe 模块测试：ffprobe 尺寸探测。"""

import shutil
from pathlib import Path

import pytest

from yt_pipeline.assessment_worker import probe
from yt_pipeline.model import StreamSpec
from tests.conftest import make_test_image

ffprobe_available = shutil.which("ffprobe") is not None
ffmpeg_available = shutil.which("ffmpeg") is not None
media_available = ffprobe_available and ffmpeg_available


@pytest.mark.skipif(not media_available, reason="ffmpeg/ffprobe 未安装")
@pytest.mark.asyncio
async def test_probe_png_dimensions(tmp_path: Path):
    png = tmp_path / "test.png"
    make_test_image(png, 16, 9)
    spec = await probe(png)
    assert spec.width == 16
    assert spec.height == 9


@pytest.mark.skipif(not ffprobe_available, reason="ffprobe 未安装")
@pytest.mark.asyncio
async def test_probe_nonexistent_file(tmp_path: Path):
    with pytest.raises(RuntimeError):
        await probe(tmp_path / "no_such_file.png")


@pytest.mark.skipif(not media_available, reason="ffmpeg/ffprobe 未安装")
@pytest.mark.asyncio
async def test_probe_returns_streamspec(tmp_path: Path):
    png = tmp_path / "test.png"
    make_test_image(png, 640, 480)
    spec = await probe(png)
    assert isinstance(spec, StreamSpec)
    assert spec.width == 640
    assert spec.height == 480

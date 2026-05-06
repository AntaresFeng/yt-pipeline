"""thumbnail 模块测试：封面查找与处理。"""

import shutil
from pathlib import Path

import pytest

from yt_pipeline.download_worker import find_thumbnail
from yt_pipeline.assessment_worker import process_thumbnail
from tests.conftest import make_test_image

ffmpeg_available = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


class TestFindThumbnail:
    def test_by_video_extensions(self, tmp_path: Path):
        import os
        video = tmp_path / "video.mp4"
        video.touch()
        thumb = tmp_path / "video.png"
        thumb.touch()
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = find_thumbnail(video, "abc123")
            assert result is not None
            assert result.name == "video.png"
        finally:
            os.chdir(orig)

    def test_by_video_id_glob(self, tmp_path: Path):
        import os
        video = tmp_path / "test.mp4"
        video.touch()
        thumb = tmp_path / "[Channel] Title [abc123].png"
        thumb.touch()
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = find_thumbnail(video, "abc123")
            assert result is not None
            assert "abc123" in result.name
        finally:
            os.chdir(orig)

    def test_no_thumbnail(self, tmp_path: Path):
        import os
        video = tmp_path / "video.mp4"
        video.touch()
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = find_thumbnail(video, "no_match")
            assert result is None
        finally:
            os.chdir(orig)


@pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg 或 ffprobe 未安装")
@pytest.mark.asyncio
async def test_process_thumbnail_below_threshold(tmp_path: Path):
    """封面高度 < 720 → 应处理。"""
    import os
    thumb = tmp_path / "cover.png"
    upscaled = thumb.with_name("cover_169_2x.png")
    make_test_image(thumb, 640, 360)

    orig = os.getcwd()
    try:
        os.chdir(tmp_path)
        await process_thumbnail(thumb)
        assert upscaled.exists()
    finally:
        os.chdir(orig)


@pytest.mark.skipif(not ffmpeg_available, reason="ffmpeg 或 ffprobe 未安装")
@pytest.mark.asyncio
async def test_process_thumbnail_above_threshold(tmp_path: Path):
    """封面高度 >= 720 → 应跳过。"""
    thumb = tmp_path / "cover.png"
    make_test_image(thumb, 1280, 720)

    await process_thumbnail(thumb)  # 不抛异常即通过

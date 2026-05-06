"""download 模块测试：credits 生成 + 路径解析。"""

from pathlib import Path

from yt_pipeline.download_worker import generate_credits, resolve_video_path
from yt_pipeline.constants import VIDEO_EXTS


class TestGenerateCredits:
    def test_basic(self, tmp_path: Path):
        video = tmp_path / "test.mkv"
        video.touch()
        info = {
            "channel": "TestChannel",
            "title": "Test Title",
            "description": "A description.",
        }
        result = generate_credits(info, "https://example.com/v", video)
        assert result.exists()
        assert result.suffix == ".description"
        content = result.read_text(encoding="utf-8")
        assert "https://example.com/v" in content
        assert "TestChannel" in content
        assert "Test Title" in content
        assert "A description." in content
        assert "转载经原作者允许" in content

    def test_missing_fields(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        info: dict = {}
        result = generate_credits(info, "https://x.com/v", video)
        content = result.read_text(encoding="utf-8")
        assert "未知" in content


class TestResolveVideoPath:
    def test_from_requested_downloads(self, tmp_path: Path):
        import os
        video = tmp_path / "video.mp4"
        video.touch()
        info = {
            "requested_downloads": [{"filepath": str(video)}],
        }
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = resolve_video_path(info, "abc")
            assert result == video
        finally:
            os.chdir(orig)

    def test_from_filename(self, tmp_path: Path):
        import os
        video = tmp_path / "video.mkv"
        video.touch()
        info = {"_filename": str(video)}
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = resolve_video_path(info, "abc")
            assert result == video
        finally:
            os.chdir(orig)

    def test_from_glob(self, tmp_path: Path):
        import os
        video = tmp_path / "[Channel] Title [abc123].mp4"
        video.touch()
        info: dict = {}
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = resolve_video_path(info, "abc123")
            assert result is not None
            assert "abc123" in result.name
        finally:
            os.chdir(orig)

    def test_not_found(self, tmp_path: Path):
        import os
        orig = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = resolve_video_path({}, "nonexistent")
            assert result is None
        finally:
            os.chdir(orig)

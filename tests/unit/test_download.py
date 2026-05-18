"""download 模块单元测试：credits 生成 + 路径解析 + WorkerLogger。"""

from pathlib import Path

from yt_pipeline.download_worker import (
    WorkerLogger,
    generate_credits,
    resolve_video_path,
)


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
    def test_from_requested_downloads(self, tmp_path: Path, chdir):
        video = tmp_path / "video.mp4"
        video.touch()
        info = {
            "requested_downloads": [{"filepath": str(video)}],
        }
        result = resolve_video_path(info, "abc")
        assert result == video

    def test_from_filename(self, tmp_path: Path, chdir):
        video = tmp_path / "video.mkv"
        video.touch()
        info = {"_filename": str(video)}
        result = resolve_video_path(info, "abc")
        assert result == video

    def test_from_glob(self, tmp_path: Path, chdir):
        video = tmp_path / "[Channel] Title [abc123].mp4"
        video.touch()
        info: dict = {}
        result = resolve_video_path(info, "abc123")
        assert result is not None
        assert "abc123" in result.name

    def test_not_found(self, tmp_path: Path, chdir):
        result = resolve_video_path({}, "nonexistent")
        assert result is None


class TestWorkerLogger:
    def test_debug_info_warning_silent(self):
        lg = WorkerLogger(label="test")
        lg.debug("d")
        lg.info("i")
        lg.warning("w")
        assert lg.errors == []

    def test_error_captured(self):
        lg = WorkerLogger(label="test")
        lg.error("something went wrong")
        assert lg.errors == ["something went wrong"]

    def test_multiple_errors(self):
        lg = WorkerLogger()
        lg.error("first")
        lg.error("second")
        assert lg.errors == ["first", "second"]

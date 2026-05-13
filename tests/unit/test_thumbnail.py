"""thumbnail 模块单元测试：封面查找。"""

from pathlib import Path

from yt_pipeline.download_worker import find_thumbnail


class TestFindThumbnail:
    def test_by_video_extensions(self, tmp_path: Path, chdir):
        video = tmp_path / "video.mp4"
        video.touch()
        thumb = tmp_path / "video.png"
        thumb.touch()
        result = find_thumbnail(video, "abc123")
        assert result is not None
        assert result.name == "video.png"

    def test_by_video_id_glob(self, tmp_path: Path, chdir):
        video = tmp_path / "test.mp4"
        video.touch()
        thumb = tmp_path / "[Channel] Title [abc123].png"
        thumb.touch()
        result = find_thumbnail(video, "abc123")
        assert result is not None
        assert "abc123" in result.name

    def test_no_thumbnail(self, tmp_path: Path, chdir):
        video = tmp_path / "video.mp4"
        video.touch()
        result = find_thumbnail(video, "no_match")
        assert result is None

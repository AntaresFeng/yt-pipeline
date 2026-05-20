"""deps 模块单元测试：依赖检测、路径解析、可执行性验证。"""

import subprocess

import pytest

import yt_pipeline.config as config
from yt_pipeline.deps import (
    DependencyError,
    _resolve_tool_path,
    _verify_executable,
    check_dependencies,
)


class TestResolveToolPath:
    def test_resolve_from_env(self):
        result = _resolve_tool_path("ffmpeg", "/custom/ffmpeg")
        assert result == "/custom/ffmpeg"

    def test_resolve_from_which(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        result = _resolve_tool_path("ffmpeg", None)
        assert result == "/usr/bin/ffmpeg"

    def test_resolve_not_found(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(DependencyError) as exc_info:
            _resolve_tool_path("ffmpeg", None)
        assert exc_info.value.tool_name == "ffmpeg"


class TestVerifyExecutable:
    def test_verify_success(self, monkeypatch):
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0),
        )
        _verify_executable("/usr/bin/ffmpeg", "ffmpeg")

    def test_verify_nonzero_exit(self, monkeypatch):
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 1),
        )
        with pytest.raises(DependencyError) as exc_info:
            _verify_executable("/bad/ffmpeg", "ffmpeg")
        assert exc_info.value.tool_name == "ffmpeg"

    def test_verify_file_not_found(self, monkeypatch):
        def _raise(*a, **kw):
            raise FileNotFoundError

        monkeypatch.setattr("subprocess.run", _raise)
        with pytest.raises(DependencyError) as exc_info:
            _verify_executable("/missing/ffmpeg", "ffmpeg")
        assert exc_info.value.tool_name == "ffmpeg"


class TestCheckDependencies:
    def test_all_ok(self, monkeypatch):
        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0),
        )
        check_dependencies()

    def test_ytdlp_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "yt_dlp":
                raise ImportError("No module named 'yt_dlp'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)
        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0),
        )
        with pytest.raises(DependencyError) as exc_info:
            check_dependencies()
        assert exc_info.value.tool_name == "yt-dlp"

    def test_ffmpeg_missing(self, monkeypatch):
        monkeypatch.setattr(config, "FFMPEG_PATH", None)
        monkeypatch.setattr(config, "FFPROBE_PATH", None)
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(DependencyError) as exc_info:
            check_dependencies()
        assert exc_info.value.tool_name == "ffmpeg"

    def test_ffprobe_not_executable(self, monkeypatch):
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # ffmpeg -version succeeds
                return subprocess.CompletedProcess(args[0], 0)
            return subprocess.CompletedProcess(args[0], 1)  # ffprobe fails

        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("subprocess.run", _mock_run)
        with pytest.raises(DependencyError) as exc_info:
            check_dependencies()
        assert exc_info.value.tool_name == "ffprobe"

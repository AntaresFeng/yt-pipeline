"""deps 模块单元测试：依赖检测、路径解析、可执行性验证。"""

import subprocess

import pytest

import yt_pipeline.config as config
from yt_pipeline.deps import (
    DependencyError,
    _resolve_tool_path,
    _verify_executable,
    check_dependencies,
    resolve_dependency_paths,
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

    def test_resolve_from_candidate_names(self, monkeypatch):
        calls = []

        def _which(name):
            calls.append(name)
            if name == "NVEncC64.exe":
                return "C:/Tools/NVEncC64.exe"
            return None

        monkeypatch.setattr("shutil.which", _which)

        result = _resolve_tool_path(
            "nvencc",
            None,
            candidates=["NVEncC64.exe", "nvencc64"],
        )

        assert result == "C:/Tools/NVEncC64.exe"
        assert calls == ["NVEncC64.exe"]


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

    def test_verify_uses_custom_version_arg(self, monkeypatch):
        calls = []

        def _run(*args, **kwargs):
            calls.append(args[0])
            return subprocess.CompletedProcess(args[0], 0)

        monkeypatch.setattr("subprocess.run", _run)

        _verify_executable("/tools/NVEncC64.exe", "nvencc", version_arg="--version")

        assert calls == [["/tools/NVEncC64.exe", "--version"]]


class TestCheckDependencies:
    def test_resolve_dependency_paths_without_verifying(self, monkeypatch):
        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "nvencc", raising=False)
        monkeypatch.setattr(config, "FFMPEG_PATH", None)
        monkeypatch.setattr(config, "FFPROBE_PATH", None)
        monkeypatch.setattr(config, "NVENCC_PATH", None, raising=False)

        def _which(name):
            return {
                "ffmpeg": "/usr/bin/ffmpeg",
                "ffprobe": "/usr/bin/ffprobe",
                "NVEncC64.exe": "C:/Tools/NVEncC64.exe",
            }.get(name)

        def _run(*args, **kwargs):
            raise AssertionError("resolve_dependency_paths must not verify tools")

        monkeypatch.setattr("shutil.which", _which)
        monkeypatch.setattr("subprocess.run", _run)

        resolve_dependency_paths()

        assert config.FFMPEG_PATH == "/usr/bin/ffmpeg"
        assert config.FFPROBE_PATH == "/usr/bin/ffprobe"
        assert config.NVENCC_PATH == "C:/Tools/NVEncC64.exe"

    def test_all_ok(self, monkeypatch):
        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "ffmpeg", raising=False)
        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0),
        )
        check_dependencies()

    def test_nvencc_backend_all_ok_from_path_candidate(self, monkeypatch):
        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "nvencc", raising=False)
        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr(config, "NVENCC_PATH", None, raising=False)

        def _which(name):
            return {
                "NVEncC64.exe": "C:/Tools/NVEncC64.exe",
            }.get(name)

        calls = []

        def _run(*args, **kwargs):
            calls.append(args[0])
            return subprocess.CompletedProcess(args[0], 0)

        monkeypatch.setattr("shutil.which", _which)
        monkeypatch.setattr("subprocess.run", _run)

        check_dependencies()

        assert config.NVENCC_PATH == "C:/Tools/NVEncC64.exe"
        assert ["/tools/NVEncC64.exe", "--version"] not in calls
        assert ["C:/Tools/NVEncC64.exe", "--version"] in calls

    def test_ytdlp_missing(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "yt_dlp":
                raise ImportError("No module named 'yt_dlp'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)
        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "ffmpeg", raising=False)
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
        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "ffmpeg", raising=False)
        monkeypatch.setattr(config, "FFMPEG_PATH", None)
        monkeypatch.setattr(config, "FFPROBE_PATH", None)
        monkeypatch.setattr("shutil.which", lambda name: None)
        with pytest.raises(DependencyError) as exc_info:
            check_dependencies()
        assert exc_info.value.tool_name == "ffmpeg"

    def test_nvencc_missing_for_nvencc_backend(self, monkeypatch):
        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "nvencc", raising=False)
        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr(config, "NVENCC_PATH", None, raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: subprocess.CompletedProcess(a[0], 0),
        )

        with pytest.raises(DependencyError) as exc_info:
            check_dependencies()

        assert exc_info.value.tool_name == "nvencc"

    def test_ffprobe_not_executable(self, monkeypatch):
        call_count = 0

        def _mock_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # ffmpeg -version succeeds
                return subprocess.CompletedProcess(args[0], 0)
            return subprocess.CompletedProcess(args[0], 1)  # ffprobe fails

        monkeypatch.setattr(config, "TRANSCODE_BACKEND", "ffmpeg", raising=False)
        monkeypatch.setattr(config, "FFMPEG_PATH", "/usr/bin/ffmpeg")
        monkeypatch.setattr(config, "FFPROBE_PATH", "/usr/bin/ffprobe")
        monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
        monkeypatch.setattr("subprocess.run", _mock_run)
        with pytest.raises(DependencyError) as exc_info:
            check_dependencies()
        assert exc_info.value.tool_name == "ffprobe"

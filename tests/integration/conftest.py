"""集成测试共享 fixture：mock 外部边界，保留业务逻辑。"""

import asyncio
from pathlib import Path

import pytest

from yt_pipeline.pipeline import ShutdownManager

# ---- Mock 数据常量 ----

FFPROBE_1081 = (
    0,
    '{"streams":[{"width":1920,"height":1081,"codec_name":"vp9"}]}',
    "",
)
FFPROBE_1080 = (
    0,
    '{"streams":[{"width":1920,"height":1080,"codec_name":"vp9"}]}',
    "",
)
FFPROBE_ULTRAWIDE = (
    0,
    '{"streams":[{"width":3840,"height":1081,"codec_name":"vp9"}]}',
    "",
)
FFPROBE_FAILURE = (1, "", "ffprobe error: could not find stream info")

FFPROBE_THUMBNAIL_TALL = (0, '{"streams":[{"width":320,"height":180}]}', "")
FFPROBE_THUMBNAIL_OK = (0, '{"streams":[{"width":1280,"height":720}]}', "")


def make_download_info(video_path: Path, video_id: str = "testvid") -> dict:
    """构造 yt-dlp 返回的 info dict。"""
    return {
        "id": video_id,
        "channel": "TestChannel",
        "title": "Test Title",
        "description": "Test",
        "webpage_url": f"https://youtube.com/watch?v={video_id}",
        "requested_downloads": [{"filepath": str(video_path)}],
    }


def make_video_files(tmp_path: Path, video_id: str = "testvid") -> Path:
    """在 tmp_path 创建视频 + 封面文件，返回视频路径。"""
    video_path = tmp_path / f"Test Video [{video_id}].mp4"
    video_path.write_bytes(b"\x00" * 1024)
    thumb_path = tmp_path / f"Test Video [{video_id}].png"
    thumb_path.write_bytes(b"\x89PNG" + b"\x00" * 100)
    return video_path


# ---- Fixtures ----


@pytest.fixture
def mock_download(tmp_path: Path, monkeypatch):
    """替换 _do_download。自动创建视频+封面文件，返回 info dict。

    返回一个 set_fn(video_id, video_filename) 函数用于自定义参数。
    """
    _config = {"video_id": "testvid", "video_filename": None}

    def _do_download(url: str) -> dict:
        video_id = _config["video_id"]
        video_path = make_video_files(tmp_path, video_id)
        return make_download_info(video_path, video_id)

    monkeypatch.setattr("yt_pipeline.download_worker._do_download", _do_download)

    def set_fn(video_id: str = "testvid", video_filename: str | None = None):
        _config["video_id"] = video_id
        _config["video_filename"] = video_filename

    return set_fn


@pytest.fixture
def mock_subprocess(monkeypatch):
    """替换 assessment_worker.run_command。

    返回一个配置函数 set_responses(ffprobe=..., ffmpeg=..., ffprobe_cover=...)。
    默认 ffprobe 返回 1920x1081 (upscale)，ffmpeg 返回成功。
    封面探测默认返回 720px 高度（跳过封面处理）。
    """
    _responses = {
        "ffprobe": FFPROBE_1081,
        "ffmpeg": (0, "", ""),
        "ffprobe_cover": FFPROBE_THUMBNAIL_OK,
    }

    async def _run_command(cmd: list[str]) -> tuple[int, str, str]:
        cmd_name = Path(cmd[0]).name
        if cmd_name == "ffprobe":
            target = cmd[-1]
            if any(target.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                return _responses["ffprobe_cover"]
            return _responses["ffprobe"]
        elif cmd_name == "ffmpeg":
            return _responses["ffmpeg"]
        return (1, "", f"unknown command: {cmd[0]}")

    monkeypatch.setattr("yt_pipeline.assessment_worker.run_command", _run_command)

    def set_responses(
        ffprobe: tuple | None = None,
        ffmpeg: tuple | None = None,
        ffprobe_cover: tuple | None = None,
    ):
        if ffprobe is not None:
            _responses["ffprobe"] = ffprobe
        if ffmpeg is not None:
            _responses["ffmpeg"] = ffmpeg
        if ffprobe_cover is not None:
            _responses["ffprobe_cover"] = ffprobe_cover

    return set_responses


@pytest.fixture
def mock_transcode(monkeypatch):
    """替换 run_transcode 为 no-op 异步函数，记录调用参数。

    返回一个 call_args_list 列表。
    """
    call_log: list[list[str]] = []

    async def _run_transcode(cmd: list[str], shutdown, *, label: str = ""):
        call_log.append(cmd)

    monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _run_transcode)
    return call_log


@pytest.fixture
def pipeline_env(tmp_path: Path, monkeypatch):
    """组合 fixture：tmp_path + chdir + ShutdownManager + state_file 路径。"""
    import os

    from yt_pipeline import config

    monkeypatch.setattr(config, "FFMPEG_PATH", "ffmpeg")
    monkeypatch.setattr(config, "FFPROBE_PATH", "ffprobe")
    monkeypatch.setattr(config, "TRANSCODE_ENCODER", "nvenc", raising=False)
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr("yt_pipeline.download_worker.OUTPUT_DIR", tmp_path)

    orig = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(orig)


@pytest.fixture
def shutdown():
    """创建不 attach 信号的 ShutdownManager。"""
    return ShutdownManager()


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch):
    """替换 pipeline 中的 STATE_FILE 到 tmp_path。"""
    sf = tmp_path / "progress.json"
    monkeypatch.setattr("yt_pipeline.pipeline.STATE_FILE", sf)
    return sf


@pytest.fixture
def gate():
    """用于 shutdown 时序控制的 asyncio.Event。测试在 mock 函数中 await gate.wait()，
    然后触发 shutdown.event.set()，再 gate.set() 放行 mock。"""
    return asyncio.Event()

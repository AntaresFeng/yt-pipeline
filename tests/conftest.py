"""pytest fixtures: progress.json 构造、配置预设、进程内 pipeline 测试环境。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path

import pytest

from yt_pipeline import config as constants
from yt_pipeline.model import StreamSpec
from yt_pipeline.pipeline import ShutdownManager
from yt_pipeline.model import States


@dataclass
class PipelineEnv:
    """进程内 pipeline 测试环境。"""

    state_file: Path
    shutdown: ShutdownManager
    dl_started: asyncio.Event
    dl_proceed: asyncio.Event
    tc_started: asyncio.Event
    tc_proceed: asyncio.Event
    monkeypatch: pytest.MonkeyPatch

    def release_all(self) -> None:
        """释放所有阻塞事件，让 mock 快速完成。"""
        self.dl_proceed.set()
        self.tc_proceed.set()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """隔离的工作目录，progress.json 在这里创建。"""
    return tmp_path


@pytest.fixture
async def pipeline_env(tmp_path: Path, monkeypatch) -> AsyncGenerator[PipelineEnv, None]:
    """进程内 pipeline 测试环境。默认 mock 快速完成，测试可按需覆盖。"""
    state_file = tmp_path / "progress.json"
    monkeypatch.setattr(constants, "STATE_FILE", state_file)
    shutdown = ShutdownManager()

    dl_started = asyncio.Event()
    dl_proceed = asyncio.Event()
    tc_started = asyncio.Event()
    tc_proceed = asyncio.Event()

    async def mock_download(task, _shutdown):
        task.state = States.DOWNLOADING
        task.video_id = "test123"
        task.title = "Test Video"
        task.video_path = str(tmp_path / "test123.mp4")
        Path(task.video_path).touch()
        task.thumbnail_path = str(tmp_path / "test123.png")
        Path(task.thumbnail_path).touch()
        task.credits_path = str(tmp_path / "test123.description")
        Path(task.credits_path).write_text("credits", encoding="utf-8")
        dl_started.set()
        await dl_proceed.wait()
        if _shutdown.is_set:
            raise asyncio.CancelledError("Download cancelled by shutdown")
        task.state = States.DOWNLOADED

    async def mock_transcode(task, _shutdown):
        task.state = States.PROCESSING_VIDEO
        tc_started.set()
        await tc_proceed.wait()
        if _shutdown.is_set:
            raise asyncio.CancelledError("Transcode cancelled by shutdown")
        task.state = States.DONE

    async def mock_probe(path):
        return StreamSpec(width=1920, height=1440)

    monkeypatch.setattr("yt_pipeline.download_worker.download_video", mock_download)
    monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", mock_transcode)
    monkeypatch.setattr("yt_pipeline.assessment_worker.probe", mock_probe)

    yield PipelineEnv(
        state_file=state_file,
        shutdown=shutdown,
        dl_started=dl_started,
        dl_proceed=dl_proceed,
        tc_started=tc_started,
        tc_proceed=tc_proceed,
        monkeypatch=monkeypatch,
    )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def make_progress_json(tasks: list[dict], path: Path) -> None:
    """写入 progress.json 文件。"""
    data = {"tasks": tasks}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_progress_json(path: Path) -> dict | None:
    """读取 progress.json，不存在返回 None。"""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def make_test_image(path: Path, width: int, height: int) -> None:
    """用 ffmpeg lavfi 生成测试图片。"""
    # fmt: off
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=red:s={width}x{height}:d=0.1",
            "-frames:v", "1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # fmt: on


def make_test_video(path: Path, width: int = 320, height: int = 240) -> None:
    """用 ffmpeg lavfi 生成测试视频片段。"""
    # fmt: off
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc=s={width}x{height}:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", "0.5",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    # fmt: on


def check_states(progress: dict, expected: dict[str, str]) -> bool:
    """检查 progress.json 中各 URL 的状态是否符合预期。"""
    if progress is None:
        return False
    tasks_by_url = {t["url"]: t["state"] for t in progress["tasks"]}
    for url, expected_state in expected.items():
        if tasks_by_url.get(url) != expected_state:
            return False
    return True

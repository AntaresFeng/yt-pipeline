"""transcoder 模块测试：转码薄层。"""

import asyncio
import sys
from pathlib import Path

import pytest

from yt_pipeline.pipeline import ShutdownManager
from yt_pipeline.model import Task
from yt_pipeline.transcode_worker import transcode_video

_MOCK_FFMPEG = str(
    (Path(__file__).parent.parent / "scripts" / "mock_ffmpeg.py").resolve()
)


@pytest.mark.asyncio
async def test_transcode_normal():
    task = Task(
        url="test://video",
        ffmpeg_command=[
            sys.executable,
            _MOCK_FFMPEG,
            "--frames", "1",
            "--frame-delay", "0.05",
            "--cleanup-delay", "0.05",
        ],
    )
    shutdown = ShutdownManager()
    await transcode_video(task, shutdown)


@pytest.mark.asyncio
async def test_transcode_shutdown():
    task = Task(
        url="test://video",
        ffmpeg_command=[
            sys.executable,
            _MOCK_FFMPEG,
            "--frames", "10",
            "--frame-delay", "1.0",
            "--cleanup-delay", "0.05",
        ],
    )
    shutdown = ShutdownManager()
    shutdown.event.set()
    with pytest.raises(asyncio.CancelledError, match="Shutdown during transcode"):
        await transcode_video(task, shutdown)


def test_transcode_no_command():
    task = Task(url="test://video")
    shutdown = ShutdownManager()

    async def _run():
        await transcode_video(task, shutdown)

    with pytest.raises(ValueError, match="ffmpeg_command"):
        asyncio.run(_run())

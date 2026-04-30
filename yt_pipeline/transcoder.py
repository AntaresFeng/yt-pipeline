"""转码入口。薄封装 process.run_transcode。"""

from __future__ import annotations

import logging

from yt_pipeline.process import run_transcode
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task

logger = logging.getLogger("pipeline.transcoder")


async def transcode_video(task: Task, shutdown: ShutdownManager) -> None:
    """执行视频转码。"""
    if task.ffmpeg_command is None:
        raise ValueError("task.ffmpeg_command 未设置")
    await run_transcode(task.ffmpeg_command, shutdown, label=task.url)

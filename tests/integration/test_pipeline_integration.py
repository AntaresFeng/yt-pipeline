"""Pipeline 集成测试：验证 worker 间编排逻辑。"""

import asyncio
from pathlib import Path

import pytest

from yt_pipeline.model import Task, States, RESUME_RESET
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.pipeline import run_pipeline, ShutdownManager


class TestFullPipeline:
    async def test_full_pipeline_upscale(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """1920x1081 -> upscale_4k 策略：全链路 pending->done，ffmpeg_command 含 scale=3840:2160。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert any("scale=3840:2160" in " ".join(cmd) for cmd in mock_transcode)
        assert len(mock_transcode) == 1

    async def test_full_pipeline_pad(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """3840x1081 -> pad_1600 策略：全链路 pending->done，ffmpeg_command 含 pad=iw:1600。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":3840,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert any("pad=iw:1600" in " ".join(cmd) for cmd in mock_transcode)
        assert len(mock_transcode) == 1

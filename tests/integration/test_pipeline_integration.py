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


class TestSkipStrategy:
    async def test_skip_strategy(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """1920x1080 → skip：不经 processing_video，run_transcode 未被调用。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1080}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 0


class TestShutdown:
    async def test_shutdown_during_download(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """download 阶段触发 shutdown：任务保留 DOWNLOADING 状态。"""
        async def _gated_download(task, shutdown_mgr):
            gate.set()
            await shutdown_mgr.event.wait()
            raise asyncio.CancelledError("Shutdown during download")

        monkeypatch.setattr("yt_pipeline.download_worker.download_video", _gated_download)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.DOWNLOADING

    async def test_shutdown_during_assessment(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """assessment 阶段触发 shutdown：任务回退到 DOWNLOADED。"""
        call_count = 0

        async def _gated_run_command(cmd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                gate.set()
                await shutdown.event.wait()
                raise asyncio.CancelledError("Shutdown during assessment")
            return (0, '{"streams":[{"width":1920,"height":1081}]}', '')

        monkeypatch.setattr("yt_pipeline.assessment_worker.run_command", _gated_run_command)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.DOWNLOADED

    async def test_shutdown_during_transcode(
        self, pipeline_env, mock_download, mock_subprocess,
        shutdown, gate, monkeypatch,
    ):
        """transcode 阶段触发 shutdown：任务保留 PROCESSING_VIDEO 状态。"""
        async def _gated_transcode(cmd, shutdown_mgr, *, label=""):
            gate.set()
            await shutdown_mgr.event.wait()
            raise asyncio.CancelledError("Shutdown during transcode")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _gated_transcode)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.PROCESSING_VIDEO

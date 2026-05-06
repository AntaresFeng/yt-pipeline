"""进程内 pipeline 中断/恢复测试。

用 monkeypatch 替换 download_video / transcode_video / probe，
用 asyncio.Event 控制执行时序，用 shutdown.event.set() 模拟 Ctrl+C。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from yt_pipeline.model import StreamSpec
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.pipeline import run_pipeline
from yt_pipeline.model import Task, States, RESUME_RESET

from tests.conftest import make_progress_json, read_progress_json, check_states


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_URL = "https://example.com/video{}"


def _dl(n_downloading: int, n_pending: int) -> list[dict]:
    """构造 downloading + pending 混合状态。"""
    tasks = []
    for i in range(n_downloading):
        tasks.append({"url": _URL.format(i + 1), "state": States.DOWNLOADING, "error": None})
    for i in range(n_pending):
        tasks.append({"url": _URL.format(n_downloading + i + 1), "state": States.PENDING, "error": None})
    return tasks


def _pv(n: int) -> list[dict]:
    """构造 processing_video 状态。"""
    return [
        {
            "url": _URL.format(i + 1),
            "state": States.PROCESSING_VIDEO,
            "error": None,
            "strategy": "upscale_4k",
            "video_path": f"/tmp/example.com_video{i + 1}.mp4",
        }
        for i in range(n)
    ]


def _dd(n: int) -> list[dict]:
    """构造 downloaded 状态。"""
    return [{"url": _URL.format(i + 1), "state": States.DOWNLOADED, "error": None} for i in range(n)]


# ---------------------------------------------------------------------------
# interrupt tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interrupt_during_download(pipeline_env, tmp_path):
    """下载阶段 Ctrl+C → progress.json 状态为 downloading。"""
    env = pipeline_env
    task = Task(url="https://example.com/video1")
    make_progress_json([{"url": task.url, "state": States.PENDING, "error": None}], env.state_file)

    async def mock_download(t, _shutdown):
        t.state = States.DOWNLOADING
        t.video_id = "test123"
        t.video_path = str(tmp_path / "test123.mp4")
        Path(t.video_path).touch()
        save_all_progress([t], env.state_file)
        env.dl_started.set()
        await env.dl_proceed.wait()
        # 不设 t.state = FAILED，让 worker 持久化的状态保持 DOWNLOADING
        raise asyncio.CancelledError("Download cancelled by shutdown")

    env.monkeypatch.setattr("yt_pipeline.download_worker.download_video", mock_download)

    pipeline_task = asyncio.create_task(run_pipeline([task], env.shutdown, env.state_file))
    await env.dl_started.wait()
    env.shutdown.event.set()
    env.dl_proceed.set()
    await pipeline_task

    progress = read_progress_json(env.state_file)
    assert progress is not None
    assert check_states(progress, {task.url: States.DOWNLOADING})


@pytest.mark.asyncio
async def test_interrupt_during_transcode(pipeline_env):
    """转码阶段 Ctrl+C → progress.json 状态为 processing_video。"""
    env = pipeline_env
    task = Task(url="https://example.com/video1")

    env.dl_proceed.set()

    async def mock_transcode(t, _shutdown):
        t.state = States.PROCESSING_VIDEO
        env.tc_started.set()
        await env.tc_proceed.wait()
        if _shutdown.is_set:
            raise asyncio.CancelledError("Transcode cancelled by shutdown")
        t.state = States.DONE

    env.monkeypatch.setattr("yt_pipeline.transcode_worker.transcode_video", mock_transcode)

    pipeline_task = asyncio.create_task(run_pipeline([task], env.shutdown, env.state_file))
    await env.tc_started.wait()
    env.shutdown.event.set()
    env.tc_proceed.set()
    await pipeline_task

    progress = read_progress_json(env.state_file)
    assert progress is not None
    assert check_states(progress, {task.url: States.PROCESSING_VIDEO})


@pytest.mark.asyncio
async def test_interrupt_during_assessment(pipeline_env):
    """探测阶段 Ctrl+C → progress.json 状态不为 DONE。"""
    env = pipeline_env
    task = Task(url="https://example.com/video1")

    env.dl_proceed.set()

    probe_started = asyncio.Event()
    probe_proceed = asyncio.Event()

    async def mock_probe(path):
        probe_started.set()
        await probe_proceed.wait()
        return StreamSpec(width=1082, height=1082)

    env.monkeypatch.setattr("yt_pipeline.assessment_worker.probe", mock_probe)

    pipeline_task = asyncio.create_task(run_pipeline([task], env.shutdown, env.state_file))
    await probe_started.wait()
    env.shutdown.event.set()
    probe_proceed.set()
    env.tc_proceed.set()
    await pipeline_task

    progress = read_progress_json(env.state_file)
    assert progress is not None
    state = progress["tasks"][0]["state"]
    assert state != States.DONE, f"Task should not be DONE after interrupt, got: {state}"


# ---------------------------------------------------------------------------
# resume / completion tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_after_download_interrupt(pipeline_env):
    """从 downloading 中断恢复 → 加载状态 → 最终完成。"""
    env = pipeline_env
    env.release_all()

    make_progress_json(_dl(1, 2), env.state_file)

    tasks = [
        Task(url="https://example.com/video1", state=States.DOWNLOADING),
        Task(url="https://example.com/video2", state=States.PENDING),
        Task(url="https://example.com/video3", state=States.PENDING),
    ]
    for task in tasks:
        new_state = RESUME_RESET.get(task.state)
        if new_state is not None:
            task.state = new_state

    await run_pipeline(tasks, env.shutdown, env.state_file)

    assert all(t.state == States.DONE for t in tasks)
    assert not env.state_file.exists()


@pytest.mark.asyncio
async def test_resume_after_ffmpeg_interrupt(pipeline_env):
    """从 processing_video 中断恢复 → 转码完成 → 最终完成。"""
    env = pipeline_env
    env.release_all()

    make_progress_json(_pv(1), env.state_file)

    tasks = [
        Task(
            url="https://example.com/video1",
            state=States.PROCESSING_VIDEO,
            strategy="upscale_4k",
            video_path="/tmp/example.com_video1.mp4",
        ),
    ]

    await run_pipeline(tasks, env.shutdown, env.state_file)

    assert tasks[0].state == States.DONE
    assert not env.state_file.exists()


@pytest.mark.asyncio
async def test_auto_discard_n(pipeline_env):
    """-n 标志自动丢弃已完成任务。"""
    env = pipeline_env
    env.release_all()

    make_progress_json(_dd(2), env.state_file)

    env.state_file.unlink()
    tasks = [Task(url="https://example.com/video1"), Task(url="https://example.com/video2")]

    await run_pipeline(tasks, env.shutdown, env.state_file)

    assert all(t.state == States.DONE for t in tasks)
    assert not env.state_file.exists()


@pytest.mark.asyncio
async def test_happy_path(pipeline_env):
    """正常走完 → All tasks processed + progress.json 删除。"""
    env = pipeline_env
    env.release_all()

    tasks = [Task(url="https://example.com/video1")]

    await run_pipeline(tasks, env.shutdown, env.state_file)

    assert tasks[0].state == States.DONE
    assert not env.state_file.exists()

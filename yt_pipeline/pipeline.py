"""Pipeline 编排器：管理队列、worker 生命周期、完成检测。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from yt_pipeline.config import PipelineConfig
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task, States, TERMINAL_STATES
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.strategy import build_ffmpeg_command
from yt_pipeline.workers import download_worker, assessment_worker, transcode_worker

logger = logging.getLogger("pipeline")


async def _drain_queue(q: asyncio.Queue) -> None:
    """清空队列中剩余的所有项并标记 task_done。"""
    while True:
        try:
            q.get_nowait()
            q.task_done()
        except asyncio.QueueEmpty:
            break


async def _join_or_shutdown(
    q: asyncio.Queue,
    worker: asyncio.Task,
    shutdown: ShutdownManager,
) -> None:
    """等待队列清空或退出信号。信号触发时排空队列，正常完成时取消 worker。"""
    join_task = asyncio.create_task(q.join())
    shutdown_task = asyncio.create_task(shutdown.event.wait())
    done, pending = await asyncio.wait(
        [join_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for t in pending:
        t.cancel()

    if shutdown_task in done:
        await _drain_queue(q)
    else:
        worker.cancel()

    try:
        await worker
    except asyncio.CancelledError:
        pass


async def run_pipeline(
    tasks: list[Task],
    shutdown: ShutdownManager,
    cfg: PipelineConfig,
) -> None:
    """执行完整的下载→assessment→转码流水线。"""
    pending_queue: asyncio.Queue[Task] = asyncio.Queue()
    assessment_queue: asyncio.Queue[Task] = asyncio.Queue()
    transcode_queue: asyncio.Queue[Task] = asyncio.Queue()

    for task in tasks:
        if task.state == States.PENDING:
            await pending_queue.put(task)
        elif task.state == States.DOWNLOADED:
            await assessment_queue.put(task)
        elif task.state == States.PROCESSING_VIDEO:
            if task.ffmpeg_command is None and task.strategy and task.video_path:
                cmd, _ = build_ffmpeg_command(Path(task.video_path), task.strategy)
                task.ffmpeg_command = cmd
            await transcode_queue.put(task)

    sem = asyncio.Semaphore(cfg.download_concurrency)

    downloaders = [
        asyncio.create_task(
            download_worker(sem, pending_queue, assessment_queue, tasks, shutdown, cfg)
        )
        for _ in range(cfg.download_concurrency)
    ]
    assessment_task = asyncio.create_task(
        assessment_worker(assessment_queue, transcode_queue, tasks, shutdown, cfg)
    )
    transcode_task = asyncio.create_task(
        transcode_worker(transcode_queue, tasks, shutdown, cfg)
    )

    try:
        await asyncio.gather(*downloaders)
    except asyncio.CancelledError:
        pass

    await _join_or_shutdown(assessment_queue, assessment_task, shutdown)
    await _join_or_shutdown(transcode_queue, transcode_task, shutdown)

    save_all_progress(tasks, cfg.state_file)

    if all(t.state in TERMINAL_STATES for t in tasks):
        logger.info("All tasks processed.")
        if cfg.state_file.exists():
            cfg.state_file.unlink()
    else:
        logger.info("Pipeline stopped, progress saved.")

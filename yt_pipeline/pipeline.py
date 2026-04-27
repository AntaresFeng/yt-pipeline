"""Pipeline 编排器：管理队列、worker 生命周期、完成检测。"""

from __future__ import annotations

import asyncio
import logging

from yt_pipeline.config import PipelineConfig
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task, States, TERMINAL_STATES
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.workers import download_worker, transcode_worker

logger = logging.getLogger("pipeline")


async def run_pipeline(
    tasks: list[Task],
    shutdown: ShutdownManager,
    cfg: PipelineConfig,
) -> None:
    """执行完整的下载→转码流水线。"""
    pending_queue: asyncio.Queue[Task] = asyncio.Queue()
    transcode_queue: asyncio.Queue[Task] = asyncio.Queue()

    # 根据状态分配队列
    for task in tasks:
        if task.state == States.PENDING:
            await pending_queue.put(task)
        elif task.state == States.DOWNLOADED:
            await transcode_queue.put(task)

    sem = asyncio.Semaphore(cfg.download_concurrency)

    # 启动 workers
    downloaders = [
        asyncio.create_task(
            download_worker(sem, pending_queue, transcode_queue, tasks, shutdown, cfg)
        )
        for _ in range(cfg.download_concurrency)
    ]
    transcoder = asyncio.create_task(
        transcode_worker(transcode_queue, tasks, shutdown, cfg)
    )

    try:
        await asyncio.gather(*downloaders)
    except asyncio.CancelledError:
        pass

    if not shutdown.is_set:
        # 正常完成：等转码结束
        await transcode_queue.join()
        transcoder.cancel()
        try:
            await transcoder
        except asyncio.CancelledError:
            pass
    else:
        # 优雅退出：转码 worker 自行退出
        await transcoder

    save_all_progress(tasks, cfg.state_file)

    if all(t.state in TERMINAL_STATES for t in tasks):
        logger.info("All tasks processed.")
        if cfg.state_file.exists():
            cfg.state_file.unlink()
    else:
        logger.info("Pipeline stopped, progress saved.")

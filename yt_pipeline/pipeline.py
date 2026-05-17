"""Pipeline 编排器：管理队列、worker 生命周期、完成检测、优雅退出。"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

from yt_pipeline.config import DOWNLOAD_CONCURRENCY
from yt_pipeline.model import Task, States, TERMINAL_STATES
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.download_worker import download_worker
from yt_pipeline.assessment_worker import assessment_worker
from yt_pipeline.transcode_worker import transcode_worker

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
    state_file: Path,
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
            await transcode_queue.put(task)

    sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

    downloaders = [
        asyncio.create_task(
            download_worker(
                sem, pending_queue, assessment_queue, tasks, shutdown, state_file
            )
        )
        for _ in range(DOWNLOAD_CONCURRENCY)
    ]
    assessment_task = asyncio.create_task(
        assessment_worker(
            assessment_queue, transcode_queue, tasks, shutdown, state_file
        )
    )
    transcode_task = asyncio.create_task(
        transcode_worker(transcode_queue, tasks, shutdown, state_file)
    )

    try:
        await asyncio.gather(*downloaders)
    except asyncio.CancelledError:
        pass

    await _join_or_shutdown(assessment_queue, assessment_task, shutdown)
    await _join_or_shutdown(transcode_queue, transcode_task, shutdown)

    save_all_progress(tasks, state_file)

    failed_count = sum(1 for t in tasks if t.state == States.FAILED)
    if all(t.state == States.DONE for t in tasks):
        logger.info("All tasks processed.")
        if state_file.exists():
            state_file.unlink()
    elif failed_count:
        logger.info(
            "Pipeline stopped, %d tasks failed. Resume to retry.", failed_count
        )
    else:
        logger.info("Pipeline stopped, progress saved.")


class ShutdownManager:
    """管理优雅退出流程。

    使用方式:
        shutdown = ShutdownManager()
        shutdown.attach(asyncio.get_running_loop())
        ...
        if shutdown.is_set:
            break
    """

    def __init__(self):
        self.event: asyncio.Event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定事件循环并注册信号处理器。"""
        self._loop = loop
        try:
            loop.add_signal_handler(signal.SIGINT, self._handle_signal)
            loop.add_signal_handler(signal.SIGBREAK, self._handle_signal)
        except NotImplementedError:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGBREAK, self._handle_signal)

    def _handle_signal(self, signum: int | None = None, frame=None) -> None:
        logger.warning("Received Ctrl+C, requesting graceful shutdown...")
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self.event.set)

    @property
    def is_set(self) -> bool:
        return self.event.is_set()

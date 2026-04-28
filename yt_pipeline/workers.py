"""工作协程：并发下载 worker + assessment worker + 串行转码 worker。"""

from __future__ import annotations

import asyncio
import logging

from yt_pipeline.config import PipelineConfig
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task, States
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.mocks import (
    mock_download,
    mock_probe,
    mock_cover_process,
    mock_video_process,
)

logger = logging.getLogger("pipeline.workers")


async def download_worker(
    sem: asyncio.Semaphore,
    pending_queue: asyncio.Queue[Task],
    assessment_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: ShutdownManager,
    cfg: PipelineConfig,
) -> None:
    """并发下载 worker：从 pending_queue 取任务，完成后放入 assessment_queue。"""
    while True:
        if shutdown.is_set:
            break

        if not any(t.state == States.PENDING for t in tasks):
            break

        try:
            task = await asyncio.wait_for(pending_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != States.PENDING:
            pending_queue.task_done()
            continue

        async with sem:
            if shutdown.is_set:
                pending_queue.task_done()
                break

            task.state = States.DOWNLOADING
            save_all_progress(tasks, cfg.state_file)
            try:
                await mock_download(task, shutdown, cfg)
                task.state = States.DOWNLOADED
                save_all_progress(tasks, cfg.state_file)
                await assessment_queue.put(task)
            except asyncio.CancelledError:
                logger.warning("[%s] Download cancelled by shutdown", task.url)
                raise
            except Exception as e:
                task.state = States.FAILED
                task.error = str(e)
                save_all_progress(tasks, cfg.state_file)
                logger.error("[%s] Download failed: %s", task.url, e)
            finally:
                pending_queue.task_done()


async def assessment_worker(
    assessment_queue: asyncio.Queue[Task],
    transcode_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: ShutdownManager,
    cfg: PipelineConfig,
) -> None:
    """串行 assessment worker：探测封面/视频并决策是否需要转码。"""
    while True:
        if shutdown.is_set:
            break

        try:
            task = await asyncio.wait_for(assessment_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != States.DOWNLOADED:
            assessment_queue.task_done()
            continue

        try:
            task.state = States.PROBING_COVER
            save_all_progress(tasks, cfg.state_file)
            cover_info = await mock_probe(task, "cover", cfg)
            need_cover = cover_info["height"] < 720

            if need_cover:
                task.state = States.PROCESSING_COVER
                save_all_progress(tasks, cfg.state_file)
                await mock_cover_process(task, cfg)

            task.state = States.PROBING_VIDEO
            save_all_progress(tasks, cfg.state_file)
            video_info = await mock_probe(task, "video", cfg)
            need_video = 1080 < video_info["height"] < 1600

            if need_video:
                task.state = States.PROCESSING_VIDEO
                save_all_progress(tasks, cfg.state_file)
                await transcode_queue.put(task)
            else:
                task.state = States.DONE
                save_all_progress(tasks, cfg.state_file)
                logger.info("[%s] Completed (no video processing needed)", task.url)
        except asyncio.CancelledError:
            logger.warning(
                "[%s] Assessment cancelled, resetting to downloaded", task.url
            )
            task.state = States.DOWNLOADED
            save_all_progress(tasks, cfg.state_file)
            raise
        except Exception as e:
            task.state = States.FAILED
            task.error = str(e)
            save_all_progress(tasks, cfg.state_file)
            logger.error("[%s] Assessment failed: %s", task.url, e)
        finally:
            assessment_queue.task_done()


async def transcode_worker(
    transcode_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: ShutdownManager,
    cfg: PipelineConfig,
) -> None:
    """串行转码 worker：仅处理 PROCESSING_VIDEO → 视频转码 → DONE。"""
    while True:
        if shutdown.is_set:
            break

        try:
            task = await asyncio.wait_for(transcode_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != States.PROCESSING_VIDEO:
            transcode_queue.task_done()
            continue

        try:
            await mock_video_process(task, shutdown, cfg)

            task.state = States.DONE
            save_all_progress(tasks, cfg.state_file)
            logger.info("[%s] Transcode completed", task.url)
        except asyncio.CancelledError:
            logger.warning(
                "[%s] Transcode cancelled, preserving processing_video state",
                task.url,
            )
            raise
        except Exception as e:
            task.state = States.FAILED
            task.error = str(e)
            save_all_progress(tasks, cfg.state_file)
            logger.error("[%s] Transcode failed: %s", task.url, e)
        finally:
            transcode_queue.task_done()

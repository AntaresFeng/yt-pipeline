"""工作协程：并发下载 worker + assessment worker + 串行转码 worker。"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from yt_pipeline.config import PipelineConfig
from yt_pipeline.constants import STRATEGY_SKIP, THUMBNAIL_MIN_HEIGHT
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task, States
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.process import run_transcode
from yt_pipeline.download import download_video
from yt_pipeline.probe import probe_dimensions, ffprobe_dimensions
from yt_pipeline.thumbnail import find_thumbnail, process_thumbnail
from yt_pipeline.strategy import decide_video_strategy, build_ffmpeg_command
from yt_pipeline.transcoder import transcode_video

logger = logging.getLogger("pipeline.workers")

_MOCK_SCRIPT = str(
    (Path(__file__).parent.parent / "scripts" / "mock_ffmpeg.py").resolve()
)


async def _dry_run_download(task: Task, shutdown: ShutdownManager) -> None:
    """用 ffmpeg lavfi 生成测试视频，填充 task 下载相关字段。"""
    logger.info("[%s] Downloading...", task.url)

    output_dir = Path.cwd() / "tests"
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = task.url.replace("https://", "").replace("/", "_") or "test"
    video_path = (output_dir / safe_name).with_suffix(".mp4").resolve()

    # 1082x1082 → 触发 upscale_4k 策略
    await _run_or_shutdown([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=s=1082x1082:d=0.2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", "0.2", str(video_path),
    ], shutdown)

    thumb_path = video_path.with_suffix(".png")
    await _run_or_shutdown([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=640x360:d=0.1",
        "-frames:v", "1", str(thumb_path),
    ], shutdown)

    task.video_id = "dry_run"
    task.title = "Dry Run Test"
    task.video_path = str(video_path)
    task.thumbnail_path = str(thumb_path)

    credits = video_path.with_suffix(".description")
    credits.write_text("dry_run test credits", encoding="utf-8")
    task.credits_path = str(credits)

    logger.info("[%s] Download done", task.url)


async def _run_or_shutdown(cmd: list[str], shutdown: ShutdownManager) -> None:
    """执行命令，shutdown 触发时 raise CancelledError。无额外日志。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    wait_proc = asyncio.create_task(proc.wait())
    shutdown_task = asyncio.create_task(shutdown.event.wait())
    done, pending = await asyncio.wait(
        [wait_proc, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )
    try:
        if shutdown_task in done:
            proc.terminate()
            raise asyncio.CancelledError("Shutdown during dry-run download")
        if proc.returncode != 0:
            raise RuntimeError(f"Command failed with code {proc.returncode}")
    finally:
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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
                if cfg.dry_run:
                    await _dry_run_download(task, shutdown)
                else:
                    await download_video(task, shutdown)

                # 补充封面查找（dry_run 已设置，真实下载可能通过 download_video 设置了）
                if not task.thumbnail_path and task.video_path and task.video_id:
                    found = find_thumbnail(Path(task.video_path), task.video_id)
                    if found:
                        task.thumbnail_path = str(found)

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
    """串行 assessment worker：探测封面/视频尺寸并决策是否需要转码。"""
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
            # 封面探测与处理
            if task.thumbnail_path:
                task.state = States.PROBING_COVER
                save_all_progress(tasks, cfg.state_file)
                thumb_path = Path(task.thumbnail_path)
                try:
                    spec = await probe_dimensions(thumb_path)
                    if spec.height < THUMBNAIL_MIN_HEIGHT:
                        task.state = States.PROCESSING_COVER
                        save_all_progress(tasks, cfg.state_file)
                        await process_thumbnail(thumb_path)
                except Exception as e:
                    logger.warning("[%s] Cover processing skipped: %s", task.url, e)

            # 视频探测与策略决策
            task.state = States.PROBING_VIDEO
            save_all_progress(tasks, cfg.state_file)
            video_path = Path(task.video_path) if task.video_path else None
            if video_path is None:
                raise RuntimeError("video_path 未设置")

            spec = await ffprobe_dimensions(video_path)
            strategy, reason = decide_video_strategy(spec)

            if strategy == STRATEGY_SKIP:
                task.state = States.DONE
                save_all_progress(tasks, cfg.state_file)
                logger.info("[%s] Skipped: %s", task.url, reason)
            else:
                cmd, output = build_ffmpeg_command(video_path, strategy)
                task.strategy = strategy
                task.output_path = str(output)
                task.ffmpeg_command = cmd
                task.state = States.PROCESSING_VIDEO
                save_all_progress(tasks, cfg.state_file)
                await transcode_queue.put(task)
        except asyncio.CancelledError:
            logger.warning("[%s] Assessment cancelled, resetting to downloaded", task.url)
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
            if cfg.mock_transcode:
                await run_transcode(
                    [sys.executable, _MOCK_SCRIPT],
                    shutdown,
                    label=task.url,
                    extra_env={
                        "MOCK_FFMPEG_FRAMES": "30",
                        "MOCK_FFMPEG_FRAME_DELAY": "0.5",
                        "MOCK_FFMPEG_CLEANUP_DELAY": "0.05",
                    },
                )
            else:
                await transcode_video(task, shutdown)
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

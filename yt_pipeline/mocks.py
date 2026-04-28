"""Mock 操作：模拟 yt-dlp 下载、ffprobe 探测、ffmpeg 转码。"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

from yt_pipeline.config import PipelineConfig
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task

logger = logging.getLogger("pipeline.mocks")

# mock_ffmpeg 脚本路径（相对于项目根目录）
_MOCK_SCRIPT = str(
    (Path(__file__).parent.parent / "scripts" / "mock_ffmpeg.py").resolve()
)


async def mock_download(
    task: Task, shutdown: ShutdownManager, cfg: PipelineConfig
) -> None:
    """模拟 yt-dlp 下载，支持中途退出。"""
    logger.info("[%s] Downloading...", task.url)
    try:
        await asyncio.wait_for(shutdown.event.wait(), timeout=cfg.download_delay)
        raise asyncio.CancelledError("Shutdown during download")
    except asyncio.TimeoutError:
        pass
    logger.info("[%s] Download done", task.url)


async def mock_probe(task: Task, item: str, cfg: PipelineConfig) -> dict:
    """模拟 ffprobe 探测封面/视频尺寸。基于 URL 中视频编号确定返回值。"""
    await asyncio.sleep(cfg.probe_delay)
    # 从 URL 提取视频编号，例如 https://example.com/video3 → 3
    video_id = int(task.url.rsplit("video", 1)[-1])
    if item == "cover":
        if video_id % 2 == 0:
            return {"width": 640, "height": 360}
        return {"width": 1280, "height": 720}
    else:
        if video_id % 3 == 0:
            return {"width": 2560, "height": 1440}
        return {"width": 3840, "height": 2160}


async def mock_cover_process(task: Task, cfg: PipelineConfig) -> None:
    """模拟封面处理。"""
    logger.info("[%s] Processing cover...", task.url)
    await asyncio.sleep(cfg.cover_process_delay)
    logger.info("[%s] Cover done", task.url)


async def mock_video_process(
    task: Task, shutdown: ShutdownManager, cfg: PipelineConfig
) -> None:
    """模拟 ffmpeg 转码。子进程放入独立进程组以隔离 Ctrl+C。"""
    logger.info("[%s] Starting ffmpeg (mock)...", task.url)

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        # 独立进程组，防止 Ctrl+C 波及子进程
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    env = {**os.environ, **cfg.to_env()}

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        _MOCK_SCRIPT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **popen_kwargs,
    )

    # 使用 proc.wait() 而非 proc.communicate() 竞速，避免 communicate
    # 在后台关闭 stdin pipe（ProactorEventLoop + CREATE_NEW_PROCESS_GROUP
    # 组合下 communicate 会提前标记 stdin 为 closing）
    wait_proc = asyncio.create_task(proc.wait())
    shutdown_task = asyncio.create_task(shutdown.event.wait())
    done, pending = await asyncio.wait(
        [wait_proc, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    try:
        if shutdown_task in done:
            logger.info("[%s] Sending 'q' to ffmpeg for graceful exit...", task.url)
            if proc.stdin and not proc.stdin.is_closing():
                try:
                    proc.stdin.write(b"q\n")
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()
            await proc.communicate()
            if proc.returncode == 42:
                logger.info("[%s] ffmpeg exited gracefully (sent 'q')", task.url)
            elif proc.returncode == 0:
                logger.info("[%s] ffmpeg finished before receiving 'q'", task.url)
            else:
                logger.warning(
                    "[%s] ffmpeg exited with code %d", task.url, proc.returncode
                )
            raise asyncio.CancelledError("Shutdown during video processing")

        # 子进程自行退出
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "[%s] ffmpeg exited with code %d, likely killed by external signal. stderr: %s",
                task.url,
                proc.returncode,
                stderr.decode()[:200] if stderr else "N/A",
            )
            shutdown.event.set()
            raise asyncio.CancelledError("ffmpeg killed by external signal")
        logger.info("[%s] ffmpeg finished", task.url)
    finally:
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)  # 让 event loop 清理子进程 transport

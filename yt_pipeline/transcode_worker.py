"""转码 worker：串行执行转码命令 + 薄封装入口。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from yt_pipeline.model import Task, States
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.utils import handle_worker_error

if TYPE_CHECKING:
    from yt_pipeline.pipeline import ShutdownManager

logger = logging.getLogger("pipeline.transcode_worker")


async def _read_stderr(proc: asyncio.subprocess.Process) -> bytes:
    """读取转码进程 stderr 直到 EOF。"""
    chunks: list[bytes] = []
    if proc.stderr is not None:
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def _format_transcode_error(tool_name: str, returncode: int, stderr: bytes) -> str:
    """构建转码错误消息，附带截断的 stderr 片段。"""
    msg = f"{tool_name} exited with code {returncode}"
    if stderr:
        msg += f": {stderr.decode(errors='replace')[:200]}"
    return msg


async def run_transcode(
    cmd: list[str],
    shutdown: ShutdownManager,
    *,
    label: str = "",
) -> None:
    """执行转码命令。shutdown 触发时通过 stdin 发 'q' 优雅退出。

    注意：不能使用 proc.communicate()，因为它会在 input=None 时立即关闭 stdin 管道，
    导致后续无法发送 'q' 命令。

    Raises:
        asyncio.CancelledError: shutdown 触发，转码中断（含 stderr 信息）
        RuntimeError: 转码进程异常退出 (returncode != 0)
    """
    prefix = f"[{label}] " if label else ""
    tool_name = Path(cmd[0]).name if cmd else "transcode"
    logger.info("%sStarting %s...", prefix, tool_name)

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        **popen_kwargs,
    )

    stderr_task = asyncio.create_task(_read_stderr(proc))
    shutdown_task = asyncio.create_task(shutdown.event.wait())
    done, pending = await asyncio.wait(
        [stderr_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    try:
        if shutdown_task in done:
            logger.info("%sSending 'q' to %s for graceful exit...", prefix, tool_name)
            if proc.stdin and not proc.stdin.is_closing():
                try:
                    proc.stdin.write(b"q\n")
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()

            try:
                await asyncio.wait_for(proc.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            if proc.returncode == 0:
                logger.info("%s%s exited gracefully (sent 'q')", prefix, tool_name)
                raise asyncio.CancelledError("Shutdown during transcode")

            try:
                await asyncio.wait_for(asyncio.shield(stderr_task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

            stderr = b""
            if stderr_task.done() and not stderr_task.cancelled():
                stderr = stderr_task.result()

            msg = _format_transcode_error(tool_name, proc.returncode, stderr)
            logger.warning("%s%s", prefix, msg)
            raise RuntimeError(msg)

        # 等待进程结束，可能是转码完成、自身错误退出，或者收到 'q' 后退出
        await proc.wait()
        stderr = await stderr_task
        if proc.returncode != 0:
            msg = _format_transcode_error(tool_name, proc.returncode, stderr)
            logger.warning("%s%s", prefix, msg)
            raise RuntimeError(msg)
        logger.info("%s%s finished", prefix, tool_name)
    finally:
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)


async def transcode_worker(
    transcode_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: ShutdownManager,
    state_file: Path,
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
            if task.transcode_command is None:
                raise ValueError("task.transcode_command 未设置")
            await run_transcode(task.transcode_command, shutdown, label=task.url)
            task.state = States.DONE
            save_all_progress(tasks, state_file)
            logger.info("[%s] Transcode completed", task.url)
        except asyncio.CancelledError:
            logger.warning(
                "[%s] Transcode cancelled, preserving processing_video state",
                task.url,
            )
            raise
        except Exception as e:
            handle_worker_error(task, e, tasks, state_file)
        finally:
            transcode_queue.task_done()

"""通用异步子进程运行器。

提供两级接口：
- run_command: 短命令（ffprobe、封面 ffmpeg），无 shutdown 交互
- run_transcode: 长时 ffmpeg 转码，支持优雅退出
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from yt_pipeline.shutdown import ShutdownManager

logger = logging.getLogger("pipeline.process")


async def run_command(cmd: list[str]) -> tuple[int, str, str]:
    """执行短命令，返回 (returncode, stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode() if stdout else "",
        stderr.decode() if stderr else "",
    )


async def run_transcode(
    cmd: list[str],
    shutdown: ShutdownManager,
    *,
    label: str = "",
    extra_env: dict[str, str] | None = None,
) -> None:
    """执行 ffmpeg 转码。shutdown 触发时通过 stdin 发 'q' 优雅退出。

    Raises:
        asyncio.CancelledError: shutdown 触发，转码中断
        RuntimeError: ffmpeg 异常退出 (returncode != 0)
    """
    prefix = f"[{label}] " if label else ""
    logger.info("%sStarting ffmpeg...", prefix)

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    env = None
    if extra_env:
        import os as _os
        env = {**_os.environ, **extra_env}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **popen_kwargs,
    )

    wait_proc = asyncio.create_task(proc.wait())
    shutdown_task = asyncio.create_task(shutdown.event.wait())
    done, pending = await asyncio.wait(
        [wait_proc, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    try:
        if shutdown_task in done:
            logger.info("%sSending 'q' to ffmpeg for graceful exit...", prefix)
            if proc.stdin and not proc.stdin.is_closing():
                try:
                    proc.stdin.write(b"q\n")
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()
            await proc.communicate()
            if proc.returncode == 0:
                logger.info("%sffmpeg exited gracefully (sent 'q')", prefix)
            else:
                logger.warning(
                    "%sffmpeg exited with code %d after 'q'", prefix, proc.returncode
                )
            raise asyncio.CancelledError("Shutdown during transcode")

        # 子进程自行退出
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"ffmpeg exited with code {proc.returncode}"
            if stderr:
                msg += f": {stderr.decode()[:200]}"
            logger.warning("%s%s", prefix, msg)
            raise RuntimeError(msg)
        logger.info("%sffmpeg finished", prefix)
    finally:
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)

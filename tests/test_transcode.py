"""run_transcode 管道死锁回归测试。"""

from __future__ import annotations

import asyncio

import pytest

from yt_pipeline.pipeline import ShutdownManager
from yt_pipeline.transcode_worker import run_transcode

# Windows: echo 是内建命令，需要用 cmd /c 包装
_STDERR_FLOOD = [
    "python", "-c",
    "import sys; [sys.stderr.write(f'frame={i:06d} fps=30 q=28.0 size=12345kB "
    "time=00:01:23.45 bitrate=1234.5kbits/s speed=1.5x\\n') "
    "for i in range(3000)]; sys.exit(0)",
]


@pytest.mark.asyncio
async def test_run_transcode_large_stderr_does_not_deadlock():
    """子进程产生大量 stderr 输出 → run_transcode 应正常完成，不卡死。"""
    shutdown = ShutdownManager()

    try:
        await asyncio.wait_for(
            run_transcode(_STDERR_FLOOD, shutdown),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        pytest.fail("run_transcode 卡死（管道缓冲区满导致的死锁）")


@pytest.mark.asyncio
async def test_run_transcode_nonzero_exit_raises():
    """子进程非零退出 → run_transcode 应抛出 RuntimeError 并包含 stderr。"""
    shutdown = ShutdownManager()
    cmd = ["python", "-c", "import sys; sys.stderr.write('something went wrong'); sys.exit(1)"]

    with pytest.raises(RuntimeError, match="ffmpeg exited with code 1"):
        await run_transcode(cmd, shutdown)

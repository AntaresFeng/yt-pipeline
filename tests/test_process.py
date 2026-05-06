"""通用子进程运行器测试：run_command + run_transcode。"""

import asyncio
import sys
from pathlib import Path

import pytest

from yt_pipeline.assessment_worker import run_command
from yt_pipeline.transcode_worker import run_transcode
from yt_pipeline.pipeline import ShutdownManager

_MOCK_FFMPEG = str(
    (Path(__file__).parent.parent / "scripts" / "mock_ffmpeg.py").resolve()
)


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_command_hello():
    rc, stdout, stderr = await run_command(
        [sys.executable, "-c", "print('hello')"]
    )
    assert rc == 0
    assert "hello" in stdout


@pytest.mark.asyncio
async def test_run_command_failure():
    rc, stdout, stderr = await run_command(
        [sys.executable, "-c", "import sys; print('err', file=sys.stderr); sys.exit(1)"]
    )
    assert rc == 1
    assert "err" in stderr


# ---------------------------------------------------------------------------
# run_transcode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_transcode_normal_completion():
    """mock_ffmpeg 正常完成（不触发 shutdown）。"""
    shutdown = ShutdownManager()
    # 1 帧，短延时 — mock 快速完成
    cmd = [
        sys.executable,
        _MOCK_FFMPEG,
        "--frames", "1",
        "--frame-delay", "0.05",
        "--cleanup-delay", "0.05",
    ]
    await run_transcode(cmd, shutdown, label="test")


@pytest.mark.asyncio
async def test_run_transcode_graceful_shutdown():
    """shutdown 触发 → 发 'q' → mock 返回 0。"""
    shutdown = ShutdownManager()
    shutdown.event.set()  # 预先设置，模拟立即 shutdown

    cmd = [
        sys.executable,
        _MOCK_FFMPEG,
        "--frames", "10",
        "--frame-delay", "1.0",
        "--cleanup-delay", "0.05",
    ]
    with pytest.raises(asyncio.CancelledError, match="Shutdown during transcode"):
        await run_transcode(cmd, shutdown, label="test")


@pytest.mark.asyncio
async def test_run_transcode_ffmpeg_failure():
    """ffmpeg 非零退出应 raise RuntimeError。"""
    shutdown = ShutdownManager()
    cmd = [
        sys.executable,
        "-c",
        "import sys; sys.exit(3)",
    ]
    with pytest.raises(RuntimeError, match="ffmpeg exited with code 3"):
        await run_transcode(cmd, shutdown, label="test")

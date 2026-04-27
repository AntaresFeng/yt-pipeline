"""验证 Windows 下 CTRL_BREAK_EVENT → asyncio.Event 的信号链路。"""

from __future__ import annotations

import signal
import subprocess
import sys
import textwrap
import time

CHILD_SCRIPT = textwrap.dedent("""\
    import asyncio, signal, sys

    shutdown_event = asyncio.Event()
    _loop = None

    def on_signal(signum=None, frame=None):
        signame = signal.Signals(signum).name if signum else "UNKNOWN"
        print(f"signal_handler: received {signame}", flush=True)
        if _loop and _loop.is_running():
            _loop.call_soon_threadsafe(shutdown_event.set)

    async def main():
        global _loop
        _loop = asyncio.get_running_loop()
        signal.signal(signal.SIGINT, on_signal)
        signal.signal(signal.SIGBREAK, on_signal)
        print("child_ready", flush=True)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=10.0)
            print("signal_detected_by_asyncio", flush=True)
            return 0
        except asyncio.TimeoutError:
            print("timeout_no_signal", flush=True)
            return 1

    sys.exit(asyncio.run(main()))
""")


def test_ctrl_break_delivers_sigbreak():
    """CTRL_BREAK_EVENT 到达子进程并触发 asyncio.Event。"""
    p = subprocess.Popen(
        [sys.executable, "-c", CHILD_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )

    # 等子进程就绪
    ready = False
    start = time.time()
    while time.time() - start < 10:
        line = p.stdout.readline()
        if not line:
            break
        if "child_ready" in line:
            ready = True
            break
    assert ready, "Child did not signal ready"

    time.sleep(0.3)
    p.send_signal(signal.CTRL_BREAK_EVENT)

    try:
        stdout, stderr = p.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        p.kill()
        p.wait()
        raise AssertionError("Child did not exit within 15s")

    output = stdout + stderr

    assert "signal_handler: received" in output, "Signal handler was NOT called"
    assert "signal_detected_by_asyncio" in output, "asyncio did NOT detect the signal"
    assert p.returncode == 0, f"Expected exit code 0, got {p.returncode}"

"""pytest fixtures: 子进程管理、progress.json 构造、配置预设。"""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from yt_pipeline.config import PipelineConfig

PROJECT_ROOT = Path(__file__).parent.parent
MAIN_SCRIPT = PROJECT_ROOT / "main.py"

# 常见错误消息（任何测试中出现即为失败）
FORBIDDEN_MESSAGES = [
    "Event loop is closed",
    "task_done() called too many times",
    "Traceback (most recent call last)",
]


class PipelineProcess:
    """封装子进程的启动、信号发送、输出收集。"""

    def __init__(
        self,
        args: list[str],
        env: dict[str, str],
        cwd: Path,
    ):
        self.args = args
        self.env = env
        self.cwd = cwd
        self._process: subprocess.Popen | None = None
        self.stderr_lines: list[str] = []
        self._trigger_event = threading.Event()
        self._trigger_count = 0
        self._reader_thread: threading.Thread | None = None
        self._reading = False

    # ---- 启动 ----

    def start(
        self, trigger_msg: str | None = None, trigger_occurrence: int = 1
    ) -> None:
        """启动子进程，始终开启 stderr 读取线程。可选触发消息监听。"""
        self._process = subprocess.Popen(
            [sys.executable, str(MAIN_SCRIPT)] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            env=self.env,
            cwd=str(self.cwd),
        )
        self._process.stdin.close()
        self._reading = True

        def _read():
            count = 0
            try:
                for line in self._process.stderr:
                    self.stderr_lines.append(line)
                    if trigger_msg and trigger_msg in line:
                        count += 1
                        if count == trigger_occurrence:
                            self._trigger_event.set()
            except Exception:
                pass

        self._reader_thread = threading.Thread(target=_read, daemon=True)
        self._reader_thread.start()

    # ---- 信号 ----

    def send_ctrl_break(self) -> None:
        """发送 CTRL_BREAK_EVENT 到子进程。"""
        if self._process:
            self._process.send_signal(signal.CTRL_BREAK_EVENT)

    # ---- 等待 ----

    def wait_for_trigger(self, timeout: float = 30) -> bool:
        """等待触发消息出现。"""
        return self._trigger_event.wait(timeout=timeout)

    def wait(self, timeout: float = 60) -> int:
        """等待子进程退出，返回 exit code。"""
        try:
            self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill()
            raise
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=5)
        # 持续读取残留输出（reader 线程可能还在写）
        if self._reading and self._process.stderr:
            try:
                for line in self._process.stderr:
                    self.stderr_lines.append(line)
            except Exception:
                pass
        return self._process.returncode

    def _kill(self) -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._process.pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass

    # ---- 属性 ----

    @property
    def output(self) -> str:
        return "".join(self.stderr_lines)

    @property
    def returncode(self) -> int | None:
        return self._process.returncode if self._process else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_cfg() -> PipelineConfig:
    return PipelineConfig.from_env()


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """隔离的工作目录，progress.json 在这里创建。"""
    return tmp_path


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def make_progress_json(tasks: list[dict], path: Path) -> None:
    """写入 progress.json 文件。"""
    data = {"tasks": tasks}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_progress_json(path: Path) -> dict | None:
    """读取 progress.json，不存在返回 None。"""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def make_test_image(path: Path, width: int, height: int) -> None:
    """用 ffmpeg lavfi 生成测试图片。"""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=red:s={width}x{height}:d=0.1",
            "-frames:v", "1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def make_test_video(path: Path, width: int = 320, height: int = 240) -> None:
    """用 ffmpeg lavfi 生成测试视频片段。"""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"testsrc=s={width}x{height}:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-t", "0.5",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def check_states(progress: dict, expected: dict[str, str]) -> bool:
    """检查 progress.json 中各 URL 的状态是否符合预期。"""
    if progress is None:
        return False
    tasks_by_url = {t["url"]: t["state"] for t in progress["tasks"]}
    for url, expected_state in expected.items():
        if tasks_by_url.get(url) != expected_state:
            return False
    return True

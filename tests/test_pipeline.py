"""Ctrl+C 场景集成测试：覆盖下载/转码/探测各阶段的中断与恢复。

测试通过子进程 + CTRL_BREAK_EVENT 模拟真实用户中断，
验证优雅退出、状态持久化、无崩溃（Event loop is closed 等）。
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from yt_pipeline.config import PipelineConfig
from tests.conftest import (
    PipelineProcess,
    FORBIDDEN_MESSAGES,
    make_progress_json,
    read_progress_json,
    check_states,
)


# ---------------------------------------------------------------------------
# 测试用例数据
# ---------------------------------------------------------------------------


class _Case:
    __test__ = False  # 不是 pytest 测试类

    def __init__(
        self,
        name: str,
        *,
        cli_args: list[str] | None = None,
        env: dict[str, str] | None = None,
        pre_state: list[dict] | None = None,
        trigger_msg: str | None = None,
        trigger_n: int = 1,
        fixed_delay: float | None = None,
        delay_after_trigger: float = 0.0,
        send_interrupt: bool = True,
        double_ctrlc: bool = False,
        expected_msgs: list[str] | None = None,
        expected_states: dict[str, str] | None = None,
        timeout: int = 60,
    ):
        self.name = name
        self.cli_args = cli_args or []
        self.env = env or {}
        self.pre_state = pre_state
        self.trigger_msg = trigger_msg
        self.trigger_n = trigger_n
        self.fixed_delay = fixed_delay
        self.delay_after_trigger = delay_after_trigger
        self.send_interrupt = send_interrupt
        self.double_ctrlc = double_ctrlc
        self.expected_msgs = expected_msgs or []
        self.expected_states = expected_states or {}
        self.timeout = timeout


def _dl(n: int, p: int) -> list[dict]:
    """构造: n 个 downloading + p 个 pending。"""
    tasks = []
    for i in range(n):
        tasks.append(
            {
                "url": f"https://example.com/video{i + 1}",
                "state": "downloading",
                "error": None,
            }
        )
    off = n
    for i in range(p):
        tasks.append(
            {
                "url": f"https://example.com/video{off + i + 1}",
                "state": "pending",
                "error": None,
            }
        )
    return tasks


def _dd(n: int) -> list[dict]:
    """构造: n 个 downloaded。"""
    return [
        {
            "url": f"https://example.com/video{i + 1}",
            "state": "downloaded",
            "error": None,
        }
        for i in range(n)
    ]


INTERRUPT_TESTS = [
    _Case(
        "interrupt_during_download",
        cli_args=["-n"],
        trigger_msg="Downloading...",
        expected_msgs=["Received Ctrl+C", "Download cancelled by shutdown"],
        expected_states={"https://example.com/video1": "downloading"},
    ),
    _Case(
        "interrupt_during_ffmpeg",
        cli_args=["-n"],
        trigger_msg="Starting ffmpeg",
        expected_msgs=[
            "Received Ctrl+C",
            "Sending 'q' to ffmpeg",
            "ffmpeg exited gracefully",
            "Transcode cancelled by shutdown",
        ],
        expected_states={"https://example.com/video5": "downloaded"},
    ),
    _Case(
        "double_ctrlc_during_ffmpeg",
        cli_args=["-n"],
        trigger_msg="Starting ffmpeg",
        double_ctrlc=True,
        expected_msgs=["Received Ctrl+C", "Sending 'q' to ffmpeg"],
        expected_states={"https://example.com/video5": "downloaded"},
    ),
    _Case(
        "interrupt_at_start",
        cli_args=["-n"],
        fixed_delay=0.3,
        expected_msgs=["Received Ctrl+C"],
    ),
    _Case(
        "interrupt_during_probe",
        cli_args=["-n"],
        trigger_msg="Download done",
        delay_after_trigger=0.1,
        expected_msgs=["Received Ctrl+C", "Transcode cancelled by shutdown"],
        expected_states={"https://example.com/video5": "downloaded"},
    ),
]

RESUME_TESTS = [
    _Case(
        "resume_after_download_interrupt",
        cli_args=["-y"],
        env=PipelineConfig.fast().to_env(),
        pre_state=_dl(1, 4),
        send_interrupt=False,
        expected_msgs=["Loaded 5 tasks from saved state", "Completed successfully"],
        timeout=60,
    ),
    _Case(
        "resume_after_ffmpeg_interrupt",
        cli_args=["-y"],
        env=PipelineConfig.fast().to_env(),
        pre_state=_dd(5),
        send_interrupt=False,
        expected_msgs=["Loaded 5 tasks from saved state", "Completed successfully"],
        timeout=60,
    ),
    _Case(
        "auto_discard_n",
        cli_args=["-n"],
        env=PipelineConfig.fast().to_env(),
        pre_state=_dd(3),
        send_interrupt=False,
        expected_msgs=[
            "Loaded 3 tasks from saved state",
            "Auto-discarding (-n)",
            "Completed successfully",
        ],
        timeout=60,
    ),
    _Case(
        "happy_path",
        cli_args=["-n"],
        env=PipelineConfig.fast().to_env(),
        send_interrupt=False,
        expected_msgs=["Completed successfully", "All tasks processed"],
        timeout=60,
    ),
]


# src 目录的绝对路径，确保子进程能找到 yt_pipeline 包
_SRC_DIR = str(Path(__file__).parent.parent)


def _make_env(tc: _Case, cfg: PipelineConfig) -> dict[str, str]:
    """构建子进程环境变量：继承当前环境 + PYTHONPATH + 配置 + 测试用例覆盖。"""
    import os

    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_SRC_DIR}{os.pathsep}{existing}" if existing else _SRC_DIR
    env.update(cfg.to_env())
    env.update(tc.env)
    return env


# ---------------------------------------------------------------------------
# 中断场景参数化测试
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tc", INTERRUPT_TESTS, ids=[t.name for t in INTERRUPT_TESTS])
def test_interrupt_scenario(tc: _Case, tmp_path: Path):
    """验证在各种时机按 Ctrl+C 后的行为。"""
    state_file = tmp_path / "progress.json"
    cfg = replace(PipelineConfig.fast(), state_file=state_file)

    # 准备预置状态
    if tc.pre_state:
        make_progress_json(tc.pre_state, state_file)

    env = _make_env(tc, cfg)

    proc = PipelineProcess(args=tc.cli_args, env=env, cwd=tmp_path)

    if tc.fixed_delay is not None:
        proc.start()
        time.sleep(tc.fixed_delay)
        proc.send_ctrl_break()
    elif tc.trigger_msg:
        proc.start(trigger_msg=tc.trigger_msg, trigger_occurrence=tc.trigger_n)
        assert proc.wait_for_trigger(timeout=30), (
            f"Trigger '{tc.trigger_msg}' not seen within 30s"
        )
        if tc.delay_after_trigger:
            time.sleep(tc.delay_after_trigger)
        proc.send_ctrl_break()
    else:
        proc.start()

    if tc.double_ctrlc:
        time.sleep(0.3)
        proc.send_ctrl_break()

    exit_code = proc.wait(timeout=tc.timeout)
    _ = exit_code  # 中断场景不检查确切退出码

    # 验证 — 禁止消息
    for forbidden in FORBIDDEN_MESSAGES:
        assert forbidden not in proc.output, (
            f"[{tc.name}] Forbidden message found: {forbidden}"
        )

    # 验证 — 期望消息
    for msg in tc.expected_msgs:
        assert msg in proc.output, f"[{tc.name}] Expected message not found: {msg}"

    # 验证 — 状态
    if tc.expected_states:
        progress = read_progress_json(state_file)
        assert progress is not None, f"[{tc.name}] progress.json not found"
        assert check_states(progress, tc.expected_states), (
            f"[{tc.name}] State mismatch. Got: {progress}"
        )


# ---------------------------------------------------------------------------
# 恢复/完成场景参数化测试
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tc", RESUME_TESTS, ids=[t.name for t in RESUME_TESTS])
def test_resume_scenario(tc: _Case, tmp_path: Path):
    """验证恢复/正常完成场景。"""
    state_file = tmp_path / "progress.json"
    cfg = PipelineConfig.from_env(state_file=state_file)

    if tc.pre_state:
        make_progress_json(tc.pre_state, state_file)

    env = _make_env(tc, cfg)

    proc = PipelineProcess(args=tc.cli_args, env=env, cwd=tmp_path)
    proc.start()

    exit_code = proc.wait(timeout=tc.timeout)

    # 正常完成应返回 0
    assert exit_code == 0, f"[{tc.name}] Expected exit code 0, got {exit_code}"

    for forbidden in FORBIDDEN_MESSAGES:
        assert forbidden not in proc.output, (
            f"[{tc.name}] Forbidden message found: {forbidden}"
        )

    for msg in tc.expected_msgs:
        assert msg in proc.output, f"[{tc.name}] Expected message not found: {msg}"

    # 全部完成后 progress.json 应被删除
    if "All tasks processed" in proc.output:
        assert not state_file.exists(), (
            f"[{tc.name}] progress.json should be deleted after completion"
        )

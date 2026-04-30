"""Ctrl+C 场景集成测试：覆盖下载/assessment/转码各阶段的中断与恢复。

测试通过子进程 + CTRL_BREAK_EVENT 模拟真实用户中断，
使用 --dry-run 模式（无需网络）+ mock_ffmpeg.py（快速可控）。
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import pytest

from tests.conftest import (
    PipelineProcess,
    FORBIDDEN_MESSAGES,
    make_progress_json,
    read_progress_json,
    check_states,
)

_SRC_DIR = str(Path(__file__).parent.parent)
_FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _env(**overrides) -> dict[str, str]:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{_SRC_DIR}{os.pathsep}{existing}" if existing else _SRC_DIR
    env["PIPELINE_DRY_RUN"] = "true"
    env["PIPELINE_MOCK_TRANSCODE"] = "true"
    env.update(overrides)
    return env


def _dl(n: int, p: int) -> list[dict]:
    tasks = []
    for i in range(n):
        tasks.append({"url": f"https://example.com/video{i + 1}", "state": "downloading", "error": None})
    off = n
    for i in range(p):
        tasks.append({"url": f"https://example.com/video{off + i + 1}", "state": "pending", "error": None})
    return tasks


def _dd(n: int) -> list[dict]:
    return [{"url": f"https://example.com/video{i + 1}", "state": "downloaded", "error": None} for i in range(n)]


def _pv(n: int) -> list[dict]:
    return [
        {
            "url": f"https://example.com/video{i + 1}",
            "state": "processing_video",
            "error": None,
            "strategy": "upscale_4k",
            "video_path": f"/tmp/example.com_video{i + 1}.mp4",
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# test case data class
# ---------------------------------------------------------------------------


class _Case:
    __test__ = False

    def __init__(
        self,
        name: str,
        *,
        urls: list[str] | None = None,
        pre_state: list[dict] | None = None,
        trigger_msg: str | None = None,
        trigger_n: int = 1,
        delay_after_trigger: float = 0.0,
        send_interrupt: bool = True,
        expected_msgs: list[str] | None = None,
        expected_states: dict[str, str] | None = None,
        timeout: int = 60,
        cli_extra: list[str] | None = None,
    ):
        self.name = name
        self.urls = urls or [f"https://example.com/video{i}" for i in range(1, 4)]
        self.pre_state = pre_state
        self.trigger_msg = trigger_msg
        self.trigger_n = trigger_n
        self.delay_after_trigger = delay_after_trigger
        self.send_interrupt = send_interrupt
        self.expected_msgs = expected_msgs or []
        self.expected_states = expected_states or {}
        self.timeout = timeout
        self.cli_extra = cli_extra or []


# ---------------------------------------------------------------------------
# test cases
# ---------------------------------------------------------------------------

INTERRUPT_TESTS = [
    _Case(
        "interrupt_during_download",
        trigger_msg="Downloading...",
        expected_msgs=["Received Ctrl+C", "Download cancelled by shutdown"],
        expected_states={"https://example.com/video1": "downloading"},
    ),
    _Case(
        "interrupt_during_ffmpeg",
        trigger_msg="Starting ffmpeg",
        expected_msgs=["Received Ctrl+C", "Sending 'q' to ffmpeg"],
        expected_states={"https://example.com/video1": "processing_video"},
    ),
    _Case(
        "interrupt_during_assessment",
        trigger_msg="Download done",
        delay_after_trigger=0.2,
        expected_msgs=["Received Ctrl+C"],
    ),
]

RESUME_TESTS = [
    _Case(
        "resume_after_download_interrupt",
        pre_state=_dl(1, 2),
        expected_msgs=["Loaded 3 tasks from saved state", "All tasks processed."],
        timeout=120,
        cli_extra=["-y"],
    ),
    _Case(
        "resume_after_ffmpeg_interrupt",
        pre_state=_pv(1),
        expected_msgs=["Loaded 1 tasks from saved state", "Transcode completed", "All tasks processed."],
        timeout=120,
        cli_extra=["-y"],
    ),
    _Case(
        "auto_discard_n",
        pre_state=_dd(2),
        expected_msgs=["Loaded 2 tasks from saved state", "Auto-discarding (-n)", "All tasks processed."],
        timeout=120,
        cli_extra=["-n"],
    ),
    _Case(
        "happy_path",
        expected_msgs=["All tasks processed."],
        timeout=120,
    ),
]


# ---------------------------------------------------------------------------
# interrupt tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe 未安装")
@pytest.mark.parametrize("tc", INTERRUPT_TESTS, ids=[t.name for t in INTERRUPT_TESTS])
def test_interrupt_scenario(tc: _Case, tmp_path: Path):
    state_file = tmp_path / "progress.json"
    env = _env(PIPELINE_STATE_FILE=str(state_file))

    if tc.pre_state:
        make_progress_json(tc.pre_state, state_file)

    cli_args = tc.cli_extra + ["-n", "--dry-run"] + tc.urls
    proc = PipelineProcess(args=cli_args, env=env, cwd=tmp_path)

    if tc.trigger_msg:
        proc.start(trigger_msg=tc.trigger_msg, trigger_occurrence=tc.trigger_n)
        assert proc.wait_for_trigger(timeout=30), f"Trigger '{tc.trigger_msg}' not seen within 30s"
        if tc.delay_after_trigger:
            time.sleep(tc.delay_after_trigger)
        proc.send_ctrl_break()
    else:
        proc.start()

    exit_code = proc.wait(timeout=tc.timeout)
    _ = exit_code

    for forbidden in FORBIDDEN_MESSAGES:
        assert forbidden not in proc.output, f"[{tc.name}] Forbidden: {forbidden}"

    for msg in tc.expected_msgs:
        assert msg in proc.output, f"[{tc.name}] Expected msg not found: {msg}"

    if tc.expected_states:
        progress = read_progress_json(state_file)
        assert progress is not None, f"[{tc.name}] progress.json not found"
        assert check_states(progress, tc.expected_states), f"[{tc.name}] State mismatch. Got: {progress}"


# ---------------------------------------------------------------------------
# resume / completion tests
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe 未安装")
@pytest.mark.parametrize("tc", RESUME_TESTS, ids=[t.name for t in RESUME_TESTS])
def test_resume_scenario(tc: _Case, tmp_path: Path):
    state_file = tmp_path / "progress.json"
    env = _env(PIPELINE_STATE_FILE=str(state_file))

    if tc.pre_state:
        make_progress_json(tc.pre_state, state_file)

    cli_args = tc.cli_extra + ["--dry-run"] + tc.urls
    proc = PipelineProcess(args=cli_args, env=env, cwd=tmp_path)
    proc.start()

    exit_code = proc.wait(timeout=tc.timeout)
    assert exit_code == 0, f"[{tc.name}] Expected exit 0, got {exit_code}"

    for forbidden in FORBIDDEN_MESSAGES:
        assert forbidden not in proc.output, f"[{tc.name}] Forbidden: {forbidden}"

    for msg in tc.expected_msgs:
        assert msg in proc.output, f"[{tc.name}] Expected msg not found: {msg}"

    if "All tasks processed" in proc.output:
        assert not state_file.exists(), f"[{tc.name}] progress.json should be deleted"

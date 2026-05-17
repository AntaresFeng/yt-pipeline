# Integration Tests 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 9 个集成测试用例，验证 pipeline worker 间编排逻辑：状态流转、策略分支、shutdown 协调、resume 恢复、异常退出。

**Architecture:** mock 最低外部边界（`_do_download`、`run_command`、`run_transcode`），业务逻辑全真实执行。使用 pytest-asyncio auto 模式，gate Event 控制 shutdown 时序。

**Tech Stack:** pytest, pytest-asyncio, monkeypatch, asyncio.Event

---

## File Structure

```
tests/
  integration/
    __init__.py                        # 空文件
    conftest.py                        # 共享 fixture：mock_download, mock_subprocess, mock_transcode, pipeline_env
    test_pipeline_integration.py       # 9 个测试用例
```

不修改任何生产代码。

---

### Task 1: 创建目录和 conftest.py 核心 fixture

**Files:**
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Test: `pytest tests/integration/ -v` (应无测试可收集，仅验证 fixture 无语法错误)

- [ ] **Step 1: 创建 `__init__.py`**

```python
"""集成测试包。"""
```

- [ ] **Step 2: 编写 conftest.py**

```python
"""集成测试共享 fixture：mock 外部边界，保留业务逻辑。"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from yt_pipeline.model import Task, States
from yt_pipeline.pipeline import ShutdownManager


# ---- Mock 数据常量 ----

FFPROBE_1081 = (0, '{"streams":[{"width":1920,"height":1081}]}', '')
FFPROBE_1080 = (0, '{"streams":[{"width":1920,"height":1080}]}', '')
FFPROBE_ULTRAWIDE = (0, '{"streams":[{"width":3840,"height":1081}]}', '')
FFPROBE_FAILURE = (1, '', 'ffprobe error: could not find stream info')

FFPROBE_THUMBNAIL_TALL = (0, '{"streams":[{"width":320,"height":180}]}', '')
FFPROBE_THUMBNAIL_OK = (0, '{"streams":[{"width":1280,"height":720}]}', ''')


def make_download_info(video_path: Path, video_id: str = "testvid") -> dict:
    """构造 yt-dlp 返回的 info dict。"""
    return {
        "id": video_id,
        "channel": "TestChannel",
        "title": "Test Title",
        "description": "Test",
        "webpage_url": f"https://youtube.com/watch?v={video_id}",
        "requested_downloads": [{"filepath": str(video_path)}],
    }


def make_video_files(tmp_path: Path, video_id: str = "testvid") -> Path:
    """在 tmp_path 创建视频 + 封面文件，返回视频路径。"""
    video_path = tmp_path / f"Test Video [{video_id}].mp4"
    video_path.write_bytes(b"\x00" * 1024)
    thumb_path = tmp_path / f"Test Video [{video_id}].png"
    thumb_path.write_bytes(b"\x89PNG" + b"\x00" * 100)
    return video_path


# ---- Fixtures ----


@pytest.fixture
def mock_download(tmp_path: Path, monkeypatch):
    """替换 _do_download。自动创建视频+封面文件，返回 info dict。

    返回一个 set_fn(video_id, video_filename) 函数用于自定义参数。
    """
    _config = {"video_id": "testvid", "video_filename": None}

    def _do_download(url: str) -> dict:
        video_id = _config["video_id"]
        video_path = make_video_files(tmp_path, video_id)
        return make_download_info(video_path, video_id)

    monkeypatch.setattr("yt_pipeline.download_worker._do_download", _do_download)

    def set_fn(video_id: str = "testvid", video_filename: str | None = None):
        _config["video_id"] = video_id
        _config["video_filename"] = video_filename

    return set_fn


@pytest.fixture
def mock_subprocess(monkeypatch):
    """替换 assessment_worker.run_command。

    返回一个配置函数 set_responses(ffprobe=..., ffmpeg=...)。
    默认 ffprobe 返回 1920x1081 (upscale)，ffmpeg 返回成功。
    封面探测默认返回 720px 高度（跳过封面处理）。
    """
    _responses = {
        "ffprobe": FFPROBE_1081,
        "ffmpeg": (0, "", ""),
        "ffprobe_cover": FFPROBE_THUMBNAIL_OK,
    }

    async def _run_command(cmd: list[str]) -> tuple[int, str, str]:
        if cmd[0] == "ffprobe":
            # 区分封面探测和视频探测：封面路径含 .png/.jpg
            target = cmd[-1]
            if any(target.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")):
                return _responses["ffprobe_cover"]
            return _responses["ffprobe"]
        elif cmd[0] == "ffmpeg":
            return _responses["ffmpeg"]
        return (1, "", f"unknown command: {cmd[0]}")

    monkeypatch.setattr("yt_pipeline.assessment_worker.run_command", _run_command)

    def set_responses(
        ffprobe: tuple | None = None,
        ffmpeg: tuple | None = None,
        ffprobe_cover: tuple | None = None,
    ):
        if ffprobe is not None:
            _responses["ffprobe"] = ffprobe
        if ffmpeg is not None:
            _responses["ffmpeg"] = ffmpeg
        if ffprobe_cover is not None:
            _responses["ffprobe_cover"] = ffprobe_cover

    return set_responses


@pytest.fixture
def mock_transcode(monkeypatch):
    """替换 run_transcode 为 no-op 异步函数，记录调用参数。

    返回一个 MagicMock 风格的 call_args_list 列表。
    """
    call_log: list[list[str]] = []

    async def _run_transcode(cmd: list[str], shutdown, *, label: str = ""):
        call_log.append(cmd)

    monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _run_transcode)
    return call_log


@pytest.fixture
def pipeline_env(tmp_path: Path, monkeypatch):
    """组合 fixture：tmp_path + chdir + ShutdownManager + state_file 路径。"""
    import os

    orig = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(orig)


@pytest.fixture
def shutdown():
    """创建不 attach 信号的 ShutdownManager。"""
    return ShutdownManager()


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch):
    """替换 pipeline 中的 STATE_FILE 到 tmp_path。"""
    sf = tmp_path / "progress.json"
    monkeypatch.setattr("yt_pipeline.pipeline.STATE_FILE", sf)
    return sf
```

- [ ] **Step 3: 验证 fixture 无语法错误**

Run: `python -c "from tests.integration.conftest import make_download_info; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/conftest.py
git commit -m "test: add integration test shared fixtures (mock_download, mock_subprocess, mock_transcode, pipeline_env)"
```

---

### Task 2: 全链路正常流转测试（upscale + pad）

**Files:**
- Create: `tests/integration/test_pipeline_integration.py`
- Test: `pytest tests/integration/test_pipeline_integration.py::TestFullPipeline -v`

- [ ] **Step 1: 创建测试文件，编写 upscale 和 pad 两个全链路测试**

```python
"""Pipeline 集成测试：验证 worker 间编排逻辑。"""

import asyncio
from pathlib import Path

import pytest

from yt_pipeline.model import Task, States, RESUME_RESET
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.pipeline import run_pipeline, ShutdownManager


class TestFullPipeline:
    async def test_full_pipeline_upscale(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """1920x1081 → upscale_4k 策略：全链路 pending→done，ffmpeg_command 含 scale=3840:2160。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert any("scale=3840:2160" in " ".join(cmd) for cmd in mock_transcode)
        assert len(mock_transcode) == 1

    async def test_full_pipeline_pad(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """3840x1081 → pad_1600 策略：全链路 pending→done，ffmpeg_command 含 pad=iw:1600。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":3840,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert any("pad=iw:1600" in " ".join(cmd) for cmd in mock_transcode)
        assert len(mock_transcode) == 1
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/integration/test_pipeline_integration.py::TestFullPipeline -v`
Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_pipeline_integration.py
git commit -m "test: add full pipeline integration tests (upscale_4k, pad_1600)"
```

---

### Task 3: skip 策略测试

**Files:**
- Modify: `tests/integration/test_pipeline_integration.py`
- Test: `pytest tests/integration/test_pipeline_integration.py::TestSkipStrategy -v`

- [ ] **Step 1: 添加 skip 策略测试类**

在 `test_pipeline_integration.py` 末尾追加：

```python
class TestSkipStrategy:
    async def test_skip_strategy(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """1920x1080 → skip：不经 processing_video，run_transcode 未被调用。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1080}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 0
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/integration/test_pipeline_integration.py::TestSkipStrategy -v`
Expected: 1 passed

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_pipeline_integration.py
git commit -m "test: add skip strategy integration test"
```

---

### Task 4: shutdown 协调测试（download / assessment / transcode）

**Files:**
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/test_pipeline_integration.py`
- Test: `pytest tests/integration/test_pipeline_integration.py::TestShutdown -v`

- [ ] **Step 1: 在 conftest.py 中添加 gate fixture**

在 `conftest.py` 的 `# ---- Fixtures ----` 部分末尾追加：

```python
@pytest.fixture
def gate():
    """用于 shutdown 时序控制的 asyncio.Event。测试在 mock 函数中 await gate.wait()，
    然后触发 shutdown.event.set()，再 gate.set() 放行 mock。"""
    return asyncio.Event()
```

- [ ] **Step 2: 添加 shutdown 测试类**

在 `test_pipeline_integration.py` 末尾追加：

```python
class TestShutdown:
    async def test_shutdown_during_download(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """download 阶段触发 shutdown：任务保留 DOWNLOADING 状态。"""
        original_download = None

        async def _gated_download(task, shutdown_mgr):
            gate.set()            # 通知测试：mock 已到达
            await shutdown_mgr.event.wait()
            raise asyncio.CancelledError("Shutdown during download")

        # 保存原始 download_video 并替换
        from yt_pipeline import download_worker
        original_download = download_worker.download_video
        monkeypatch.setattr("yt_pipeline.download_worker.download_video", _gated_download)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.DOWNLOADING

    async def test_shutdown_during_assessment(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """assessment 阶段触发 shutdown：任务回退到 DOWNLOADED。"""
        call_count = 0
        original_run_command = None

        async def _gated_run_command(cmd):
            nonlocal call_count
            call_count += 1
            # 第一个 ffprobe 调用（封面或视频探测）时触发 gate
            if call_count == 1:
                gate.set()
                await shutdown.event.wait()
                raise asyncio.CancelledError("Shutdown during assessment")
            # 后续调用走正常逻辑
            return (0, '{"streams":[{"width":1920,"height":1081}]}', '')

        monkeypatch.setattr("yt_pipeline.assessment_worker.run_command", _gated_run_command)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.DOWNLOADED

    async def test_shutdown_during_transcode(
        self, pipeline_env, mock_download, mock_subprocess,
        shutdown, gate, monkeypatch,
    ):
        """transcode 阶段触发 shutdown：任务保留 PROCESSING_VIDEO 状态。"""
        async def _gated_transcode(cmd, shutdown_mgr, *, label=""):
            gate.set()
            await shutdown_mgr.event.wait()
            raise asyncio.CancelledError("Shutdown during transcode")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _gated_transcode)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.PROCESSING_VIDEO
```

- [ ] **Step 3: 运行测试验证通过**

Run: `pytest tests/integration/test_pipeline_integration.py::TestShutdown -v`
Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py tests/integration/test_pipeline_integration.py
git commit -m "test: add shutdown coordination integration tests (download, assessment, transcode)"
```

---

### Task 5: resume 恢复测试

**Files:**
- Modify: `tests/integration/test_pipeline_integration.py`
- Test: `pytest tests/integration/test_pipeline_integration.py::TestResume -v`

- [ ] **Step 1: 添加 resume 测试类**

在 `test_pipeline_integration.py` 末尾追加：

```python
class TestResume:
    async def test_resume_from_interrupted_state(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """从 downloading 中断状态恢复：RESUME_RESET 回退到 pending → 重新走完全链路。"""
        # 预设 progress.json 含 downloading 状态的 task
        task = Task(url="https://youtube.com/watch?v=testvid", state=States.DOWNLOADING)
        state_file = pipeline_env / "progress.json"
        save_all_progress([task], state_file)

        # 模拟 resume：按 RESUME_RESET 回退
        assert task.state in RESUME_RESET
        task.state = RESUME_RESET[task.state]  # DOWNLOADING → PENDING

        # 重新跑 pipeline
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 1
        assert not state_file.exists()  # 全部终态，progress.json 被删除
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/integration/test_pipeline_integration.py::TestResume -v`
Expected: 1 passed

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_pipeline_integration.py
git commit -m "test: add resume from interrupted state integration test"
```

---

### Task 6: ffmpeg/ffprobe 异常退出测试

**Files:**
- Modify: `tests/integration/test_pipeline_integration.py`
- Test: `pytest tests/integration/test_pipeline_integration.py::TestFailure -v`

- [ ] **Step 1: 添加异常退出测试类**

在 `test_pipeline_integration.py` 末尾追加：

```python
class TestFailure:
    async def test_assessment_ffprobe_failure(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """ffprobe 异常退出：任务标记为 FAILED，error 包含 ffprobe，progress.json 存在。"""
        from yt_pipeline.conftest_data import FFPROBE_FAILURE
        mock_subprocess(
            ffprobe=(1, '', 'ffprobe error: could not find stream info'),
        )
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.FAILED
        assert "ffprobe" in task.error
        assert state_file.exists()

    async def test_transcode_ffmpeg_failure(
        self, pipeline_env, mock_download, mock_subprocess, shutdown, monkeypatch,
    ):
        """ffmpeg 异常退出：任务标记为 FAILED，error 包含 ffmpeg，progress.json 存在。"""
        async def _failing_transcode(cmd, shutdown_mgr, *, label=""):
            raise RuntimeError("ffmpeg exited with code 1")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _failing_transcode)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.FAILED
        assert "ffmpeg" in task.error
        assert state_file.exists()
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/integration/test_pipeline_integration.py::TestFailure -v`
Expected: 2 passed

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_pipeline_integration.py
git commit -m "test: add ffprobe/ffmpeg failure integration tests"
```

---

### Task 7: 全量测试验证 + lint

**Files:**
- 无新文件
- Test: `pytest tests/ -v`

- [ ] **Step 1: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 所有测试通过（单元测试 40 + 集成测试 9）

- [ ] **Step 2: 运行 lint**

Run: `ruff check tests/integration/`
Expected: 无错误

- [ ] **Step 3: 如有 lint 问题，修复后追加 commit**

```bash
git add -A
git commit -m "fix: lint issues in integration tests"
```

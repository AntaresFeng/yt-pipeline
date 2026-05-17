# Resume 终态处理改进 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改进 resume 时 DONE/FAILED 任务的处理——DONE 过滤移除、FAILED 可重试、错误历史可追溯、progress.json 有 FAILED 时不删除。

**Architecture:** 将 `Task.error: str | None` 重命名为 `Task.errors: list[str]`，统一错误历史；扩展 `RESUME_RESET` 含 `FAILED→PENDING`；`prepare_tasks` 过滤 DONE 任务；`run_pipeline` 仅全 DONE 时删除 progress.json。

**Tech Stack:** pytest, pytest-asyncio, monkeypatch, dataclasses

---

## File Structure

```
yt_pipeline/
  model.py                    # Task.errors 字段 + RESUME_RESET 新增 FAILED
  persistence.py              # load_progress 旧格式兼容
  utils.py                    # handle_worker_error 改 append
  cli.py                      # prepare_tasks 过滤 DONE + FAILED 重试日志
  pipeline.py                 # 删除条件改为全 DONE
tests/
  integration/
    conftest.py               # 无改动
    test_pipeline_integration.py  # error→errors[-1] + 3 个新测试
  unit/
    test_cli.py               # 新增 FAILED→PENDING 测试
```

不修改任何 worker 文件（download_worker.py、assessment_worker.py、transcode_worker.py）。

---

### Task 1: 模型层改动 — Task.errors + RESUME_RESET

**Files:**
- Modify: `yt_pipeline/model.py:19-38`

- [ ] **Step 1: 修改 Task dataclass**

将 `error: str | None = None` 改为 `errors: list[str] = field(default_factory=list)`。需要在文件顶部添加 `field` 导入。

`yt_pipeline/model.py` 完整修改后的内容：

```python
"""任务状态模型与数据规格。"""

from dataclasses import dataclass, field


class States:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROBING_COVER = "probing_cover"
    PROCESSING_COVER = "processing_cover"
    PROBING_VIDEO = "probing_video"
    PROCESSING_VIDEO = "processing_video"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    url: str
    state: str = States.PENDING
    errors: list[str] = field(default_factory=list)
    video_id: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    ffmpeg_command: list[str] | None = None


# 终端状态：任务不再需要处理
TERMINAL_STATES = frozenset({States.DONE, States.FAILED})

# 中断恢复时的状态重置映射
RESUME_RESET: dict[str, str] = {
    States.DOWNLOADING: States.PENDING,
    States.PROBING_COVER: States.DOWNLOADED,
    States.PROCESSING_COVER: States.DOWNLOADED,
    States.PROBING_VIDEO: States.DOWNLOADED,
    States.FAILED: States.PENDING,
}


@dataclass
class StreamSpec:
    width: int
    height: int

    @property
    def short_edge(self) -> int:
        return min(self.width, self.height)

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)

    @property
    def ratio(self) -> float:
        return self.long_edge / self.short_edge
```

- [ ] **Step 2: 验证无语法错误**

Run: `python -c "from yt_pipeline.model import Task, RESUME_RESET, States; t = Task(url='x'); print(t.errors, RESUME_RESET[States.FAILED])"`
Expected: `[] pending`

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/model.py
git commit -m "refactor: Task.error→errors list, add FAILED to RESUME_RESET"
```

---

### Task 2: 持久化层改动 — 旧格式兼容

**Files:**
- Modify: `yt_pipeline/persistence.py:12-28`

- [ ] **Step 1: 修改 load_progress 增加旧格式迁移**

在 `Task(**t)` 之前，对每个 task dict 做字段迁移：如果有 `error` 字段且非 None，转为 `errors=[error]` 并删除 `error` 键；如果没有 `errors` 键，设为 `[]`。

`yt_pipeline/persistence.py` 修改后的 `load_progress` 函数：

```python
def load_progress(state_file: Path) -> list[Task] | None:
    """从文件加载任务列表，不存在或损坏时返回 None。"""
    if not state_file.exists():
        logger.info("No saved state found.")
        return None

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        for t in data["tasks"]:
            # 旧格式兼容：error → errors
            if "errors" not in t:
                if "error" in t and t["error"] is not None:
                    t["errors"] = [t.pop("error")]
                else:
                    t["errors"] = []
            t.pop("error", None)
        tasks = [Task(**t) for t in data["tasks"]]
        logger.info(f"Loaded {len(tasks)} tasks from saved state.")
        return tasks
    except json.JSONDecodeError:
        logger.error("Failed to parse progress file: invalid JSON.")
        return None
    except Exception as e:
        logger.error(f"Failed to load progress: {e}")
        return None
```

- [ ] **Step 2: 验证旧格式兼容**

Run: `python -c "from yt_pipeline.persistence import load_progress; from pathlib import Path; import json, tempfile; f = Path(tempfile.mktemp(suffix='.json')); f.write_text(json.dumps({'tasks': [{'url': 'x', 'state': 'failed', 'error': 'boom'}]})); ts = load_progress(f); print(ts[0].errors, ts[0].state); f.unlink()"`
Expected: `['boom'] failed`

- [ ] **Step 3: 验证新格式也正常**

Run: `python -c "from yt_pipeline.persistence import load_progress; from pathlib import Path; import json, tempfile; f = Path(tempfile.mktemp(suffix='.json')); f.write_text(json.dumps({'tasks': [{'url': 'x', 'state': 'pending', 'errors': ['a', 'b']}]})); ts = load_progress(f); print(ts[0].errors); f.unlink()"`
Expected: `['a', 'b']`

- [ ] **Step 4: Commit**

```bash
git add yt_pipeline/persistence.py
git commit -m "fix: add old-format error→errors migration in load_progress"
```

---

### Task 3: 错误处理改动 — handle_worker_error

**Files:**
- Modify: `yt_pipeline/utils.py:14-21`

- [ ] **Step 1: 修改 handle_worker_error**

`yt_pipeline/utils.py` 修改后完整内容：

```python
"""通用工具：错误处理。"""

from __future__ import annotations

import logging
from pathlib import Path

from yt_pipeline.model import Task, States
from yt_pipeline.persistence import save_all_progress

logger = logging.getLogger("pipeline.utils")


def handle_worker_error(
    task: Task, error: Exception, tasks: list[Task], state_file: Path
) -> None:
    """异常处理：标记 FAILED + 持久化 + 日志。"""
    task.state = States.FAILED
    task.errors.append(str(error))
    save_all_progress(tasks, state_file)
    logger.error("[%s] failed (attempt %d): %s", task.url, len(task.errors), error)
```

- [ ] **Step 2: 验证**

Run: `python -c "from yt_pipeline.utils import handle_worker_error; from yt_pipeline.model import Task, States; t = Task(url='x'); handle_worker_error(t, RuntimeError('test'), [], Path('dummy')); print(t.state, t.errors)"`
Expected: `failed ['test']`

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/utils.py
git commit -m "refactor: handle_worker_error uses errors.append + attempt count in log"
```

---

### Task 4: Resume 逻辑改动 — prepare_tasks

**Files:**
- Modify: `yt_pipeline/cli.py:58-89`

- [ ] **Step 1: 修改 prepare_tasks**

在 `RESUME_RESET` 回退循环之前，先过滤 DONE 任务并记录日志；对 FAILED→PENDING 的回退打印重试日志。

`yt_pipeline/cli.py` 中 `prepare_tasks` 函数替换为：

```python
def prepare_tasks(args: argparse.Namespace) -> list[Task]:
    saved_tasks = load_progress(STATE_FILE)

    should_resume = False
    if saved_tasks:
        if args.resume:
            should_resume = True
            logger.info("Found previous progress. Auto-resuming (-y).")
        elif args.fresh:
            logger.info("Found previous progress. Auto-discarding (-n).")
            STATE_FILE.unlink()
        else:
            try:
                answer = (
                    input("Found previous progress. Resume? [Y/n] ").strip().lower()
                )
                should_resume = answer in ("", "y", "yes")
            except (EOFError, KeyboardInterrupt, OSError):
                should_resume = False
            if should_resume:
                logger.info("Resuming from saved state.")
            else:
                logger.info("Starting fresh, discarding old state.")
                STATE_FILE.unlink()

    if should_resume and saved_tasks:
        # 过滤已完成的任务
        done_tasks = [t for t in saved_tasks if t.state == States.DONE]
        if done_tasks:
            logger.info("Skipping %d completed tasks.", len(done_tasks))
        tasks = [t for t in saved_tasks if t.state != States.DONE]

        # 中断态/失败态回退
        for task in tasks:
            new_state = RESUME_RESET.get(task.state)
            if new_state is not None:
                if task.state == States.FAILED:
                    logger.info(
                        "Retrying failed task: %s (previous errors: %d)",
                        task.url,
                        len(task.errors),
                    )
                task.state = new_state
        return tasks
    else:
        urls = collect_urls(args.urls, args.file)
        if not urls:
            logger.info("No URLs to process. Exiting.")
            return []
        return [Task(url) for url in urls]
```

注意：需要在 `cli.py` 顶部 import 中添加 `States`。当前 import 行为：

```python
from yt_pipeline.model import Task, RESUME_RESET
```

改为：

```python
from yt_pipeline.model import Task, States, RESUME_RESET
```

- [ ] **Step 2: 验证**

Run: `python -c "from yt_pipeline.cli import prepare_tasks; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/cli.py
git commit -m "feat: prepare_tasks filters DONE tasks, logs FAILED retry on resume"
```

---

### Task 5: Pipeline 删除条件改动

**Files:**
- Modify: `yt_pipeline/pipeline.py:101-108`

- [ ] **Step 1: 修改 run_pipeline 结尾逻辑**

将 `pipeline.py:101-108` 替换为：

```python
    save_all_progress(tasks, state_file)

    failed_count = sum(1 for t in tasks if t.state == States.FAILED)
    if all(t.state == States.DONE for t in tasks):
        logger.info("All tasks processed.")
        if state_file.exists():
            state_file.unlink()
    elif failed_count:
        logger.info(
            "Pipeline stopped, %d tasks failed. Resume to retry.", failed_count
        )
    else:
        logger.info("Pipeline stopped, progress saved.")
```

- [ ] **Step 2: 验证**

Run: `python -c "from yt_pipeline.pipeline import run_pipeline; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/pipeline.py
git commit -m "feat: keep progress.json when FAILED tasks exist, delete only on all-DONE"
```

---

### Task 6: 集成测试改动 — 修复现有断言 + 新增 3 个测试

**Files:**
- Modify: `tests/integration/test_pipeline_integration.py`
- Modify: `tests/integration/conftest.py`

- [ ] **Step 1: 修复现有断言 error→errors[-1]**

在 `test_pipeline_integration.py` 中：

将 `assert "ffprobe" in task.error`（约第 173 行）改为：
```python
        assert "ffprobe" in task.errors[-1]
```

将 `assert "ffmpeg" in task.error`（约第 191 行）改为：
```python
        assert "ffmpeg" in task.errors[-1]
```

- [ ] **Step 2: 在 conftest.py 中添加 FAILED 状态的辅助常量**

在 `tests/integration/conftest.py` 的 Mock 数据常量部分不需要改动——现有 fixture 已支持 FAILED 场景。

- [ ] **Step 3: 新增 TestResumeTerminalStates 测试类**

在 `test_pipeline_integration.py` 末尾追加：

```python
class TestResumeTerminalStates:
    async def test_resume_filters_done_tasks(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """resume 时 DONE 任务被过滤，不进入 pipeline。"""
        done_task = Task(url="https://youtube.com/watch?v=done1", state=States.DONE)
        pending_task = Task(url="https://youtube.com/watch?v=testvid", state=States.PENDING)

        state_file = pipeline_env / "progress.json"
        save_all_progress([done_task, pending_task], state_file)

        # 模拟 prepare_tasks 过滤：只保留非 DONE 任务
        tasks = [t for t in [done_task, pending_task] if t.state != States.DONE]
        await run_pipeline(tasks, shutdown, state_file)

        assert pending_task.state == States.DONE
        assert done_task.state == States.DONE
        assert len(mock_transcode) == 1  # 只有 pending_task 走了转码

    async def test_resume_failed_to_pending(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """FAILED 任务经 RESUME_RESET 回退到 PENDING，重新走完全链路。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid", state=States.FAILED, errors=["old error"])

        # 模拟 prepare_tasks 中的 RESUME_RESET 回退
        assert task.state in RESUME_RESET
        task.state = RESUME_RESET[task.state]  # FAILED → PENDING

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 1
        assert "old error" in task.errors  # 旧错误保留

    async def test_mixed_done_failed_keeps_progress(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown, monkeypatch,
    ):
        """混合 DONE+FAILED 场景：progress.json 保留（因为有 FAILED 任务）。"""
        async def _failing_transcode(cmd, shutdown_mgr, *, label=""):
            raise RuntimeError("ffmpeg exited with code 1")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _failing_transcode)

        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.FAILED
        assert state_file.exists()  # FAILED 存在，progress.json 保留
```

- [ ] **Step 4: 运行全部集成测试**

Run: `pytest tests/integration/ -v`
Expected: 12 passed (9 原有 + 3 新增)

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_pipeline_integration.py
git commit -m "test: fix error→errors[-1] assertions, add resume terminal state tests"
```

---

### Task 7: 单元测试改动 — prepare_tasks FAILED→PENDING

**Files:**
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: 新增 FAILED→PENDING resume 测试**

在 `tests/unit/test_cli.py` 的 `TestPrepareTasks` 类中追加：

```python
    def test_prepare_tasks_resume_failed(
        self, state_file, mock_load_progress
    ):
        saved = [Task(url="https://old.com", state=States.FAILED, errors=["boom"])]
        mock_load_progress(saved)

        args = argparse.Namespace(resume=True, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert len(tasks) == 1
        assert tasks[0].state == States.PENDING  # FAILED → PENDING via RESUME_RESET
        assert tasks[0].errors == ["boom"]  # errors 保留

    def test_prepare_tasks_resume_filters_done(
        self, state_file, mock_load_progress
    ):
        saved = [
            Task(url="https://done.com", state=States.DONE),
            Task(url="https://old.com", state=States.DOWNLOADING),
        ]
        mock_load_progress(saved)

        args = argparse.Namespace(resume=True, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert len(tasks) == 1
        assert tasks[0].url == "https://old.com"
        assert tasks[0].state == States.PENDING  # DOWNLOADING → PENDING
```

- [ ] **Step 2: 运行 CLI 单元测试**

Run: `pytest tests/unit/test_cli.py -v`
Expected: 11 passed (9 原有 + 2 新增)

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add prepare_tasks resume FAILED and DONE filter unit tests"
```

---

### Task 8: 全量测试验证 + lint

**Files:**
- 无新文件

- [ ] **Step 1: 运行全量测试**

Run: `pytest tests/ -v`
Expected: 所有测试通过

- [ ] **Step 2: 运行 lint**

Run: `ruff check yt_pipeline/ tests/`
Expected: 无错误

- [ ] **Step 3: 如有 lint 问题，修复后追加 commit**

```bash
git add -A
git commit -m "fix: lint issues"
```

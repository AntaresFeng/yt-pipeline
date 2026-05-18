# Assessment 状态简化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 assessment 阶段的三个中间态（PROBING_COVER / PROCESSING_COVER / PROBING_VIDEO）合并为单一 ASSESSING 状态，并减少 save_all_progress 调用至仅在终态保存。

**Architecture:** 修改 model.py 状态定义和 RESUME_RESET 映射，简化 assessment_worker 的状态流转和持久化逻辑，更新集成测试以匹配新行为。CancelledError 处理对齐其他 worker：不改状态、不保存、直接 raise。

**Tech Stack:** Python, pytest, asyncio

---

### Task 1: 修改 model.py — 合并状态 + 更新 RESUME_RESET

**Files:**
- Modify: `yt_pipeline/model.py:6-16` (States class)
- Modify: `yt_pipeline/model.py:30-36` (RESUME_RESET)

- [ ] **Step 1: 修改 States 类**

将 `yt_pipeline/model.py` 中 States 类的三个旧状态替换为 ASSESSING：

```python
class States:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ASSESSING = "assessing"
    PROCESSING_VIDEO = "processing_video"
    DONE = "done"
    FAILED = "failed"
```

- [ ] **Step 2: 修改 RESUME_RESET 映射**

将三行旧映射替换为一行：

```python
RESUME_RESET: dict[str, str] = {
    States.DOWNLOADING: States.PENDING,
    States.ASSESSING: States.DOWNLOADED,
    States.FAILED: States.PENDING,
}
```

- [ ] **Step 3: 运行相关测试确认当前失败**

Run: `pytest tests/unit/test_strategy.py -v`
Expected: PASS（strategy 测试不涉及状态）

Run: `pytest tests/integration/test_pipeline_integration.py -v`
Expected: 多个 FAIL（测试代码引用了已删除的状态常量或依赖旧行为）

- [ ] **Step 4: Commit**

```bash
git add yt_pipeline/model.py
git commit -m "refactor: merge PROBING_COVER/PROCESSING_COVER/PROBING_VIDEO into ASSESSING state"
```

---

### Task 2: 简化 assessment_worker 状态流转和持久化

**Files:**
- Modify: `yt_pipeline/assessment_worker.py:197-244` (assessment_worker 函数)

- [ ] **Step 1: 重写 assessment_worker 主体逻辑**

将 `yt_pipeline/assessment_worker.py` 中的 `assessment_worker` 函数（行 197-244）替换为：

```python
async def assessment_worker(
    assessment_queue: asyncio.Queue[Task],
    transcode_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: ShutdownManager,
    state_file: Path,
) -> None:
    """串行 assessment worker：探测封面/视频尺寸并决策是否需要转码。"""
    while True:
        if shutdown.is_set:
            break

        try:
            task = await asyncio.wait_for(assessment_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != States.DOWNLOADED:
            assessment_queue.task_done()
            continue

        try:
            video_path = Path(task.video_path) if task.video_path else None
            if video_path is None:
                raise RuntimeError("video_path 未设置")

            task.state = States.ASSESSING
            if task.thumbnail_path:
                thumb_spec, video_spec = await asyncio.gather(
                    probe(Path(task.thumbnail_path)),
                    probe(video_path),
                )
            else:
                thumb_spec = None
                video_spec = await probe(video_path)

            if thumb_spec is not None and thumb_spec.height < C.THUMBNAIL_MIN_HEIGHT:
                try:
                    await process_thumbnail(Path(task.thumbnail_path))
                except Exception as e:
                    logger.warning("[%s] Cover processing skipped: %s", task.url, e)

            strategy, reason = decide_video_strategy(video_spec)

            if strategy == C.STRATEGY_SKIP:
                task.state = States.DONE
                save_all_progress(tasks, state_file)
                logger.info("[%s] Skipped: %s", task.url, reason)
            else:
                cmd, _ = build_ffmpeg_command(video_path, strategy)
                task.ffmpeg_command = cmd
                task.state = States.PROCESSING_VIDEO
                save_all_progress(tasks, state_file)
                await transcode_queue.put(task)
        except asyncio.CancelledError:
            logger.warning("[%s] Assessment cancelled", task.url)
            raise
        except Exception as e:
            handle_worker_error(task, e, tasks, state_file)
        finally:
            assessment_queue.task_done()
```

关键变更点：
- 进入时只设一次 `task.state = States.ASSESSING`
- 删除中间的 `save_all_progress` 调用（原行 215 的 PROCESSING_COVER 前保存）
- 只在 DONE 和 PROCESSING_VIDEO 两个终态保存
- CancelledError：只 log + raise，不改状态、不保存（与 download_worker/transcode_worker 一致）

- [ ] **Step 2: 运行 strategy 单元测试确认纯函数未受影响**

Run: `pytest tests/unit/test_strategy.py -v`
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/assessment_worker.py
git commit -m "refactor: simplify assessment_worker — single ASSESSING state, save only at terminal states"
```

---

### Task 3: 更新集成测试

**Files:**
- Modify: `tests/integration/test_pipeline_integration.py:81-110` (test_shutdown_during_assessment)

- [ ] **Step 1: 更新 test_shutdown_during_assessment 的断言**

当前测试断言 `task.state == States.DOWNLOADED`（因为旧行为在 CancelledError 时重置为 DOWNLOADED）。新行为下 CancelledError 不改状态，任务保留在 ASSESSING。

将 `tests/integration/test_pipeline_integration.py` 中 `test_shutdown_during_assessment` 方法的 docstring 和断言更新：

```python
    async def test_shutdown_during_assessment(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """assessment 阶段触发 shutdown：任务保留 ASSESSING 状态。"""
        call_count = 0

        async def _gated_run_command(cmd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                gate.set()
                await shutdown.event.wait()
                raise asyncio.CancelledError("Shutdown during assessment")
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

        assert task.state == States.ASSESSING
```

变更点：
- docstring 从"回退到 DOWNLOADED"改为"保留 ASSESSING 状态"
- 断言从 `States.DOWNLOADED` 改为 `States.ASSESSING`

- [ ] **Step 2: 运行全量集成测试**

Run: `pytest tests/integration/test_pipeline_integration.py -v`
Expected: 全部 PASS

- [ ] **Step 3: 运行全量测试确认无回归**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_pipeline_integration.py
git commit -m "test: update shutdown_during_assessment for ASSESSING state behavior"
```

---

### Task 4: 更新 tests/README.md 中的状态机描述

**Files:**
- Modify: `tests/README.md:81,89`

- [ ] **Step 1: 更新状态机描述**

读取 `tests/README.md`，将行 81 和 89 中对 PROBING_COVER / PROCESSING_COVER 的引用替换为 ASSESSING。

- [ ] **Step 2: Commit**

```bash
git add tests/README.md
git commit -m "docs: update test README for ASSESSING state"
```

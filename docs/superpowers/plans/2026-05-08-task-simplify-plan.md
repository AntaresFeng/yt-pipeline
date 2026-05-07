# Task 简化 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 dataclass Task 从 11 个字段精简到 7 个，删除只写不读的死字段 title/credits_path/strategy/output_path。

**Architecture:** 纯数据模型清理 —— 移除 4 个字段，更新读写这些字段的 6 个文件，保持 generate_credits() 副作用逻辑不变。无新模块。

**Tech Stack:** Python 3.12 dataclass, pytest

---

### Task 1: 简化 model.py —— 删除 4 个字段定义

**Files:**
- Modify: `yt_pipeline/model.py:23-31`

- [ ] **Step 1: 删除字段定义**

将第 18-32 行的 `Task` dataclass 简化为：

```python
@dataclass
class Task:
    url: str
    state: str = States.PENDING
    error: str | None = None
    video_id: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    ffmpeg_command: list[str] | None = None
```

即删除注释行 `# 下载阶段填充` 和 `# assessment 阶段填充`，以及 `title`、`credits_path`、`strategy`、`output_path` 四个字段。

- [ ] **Step 2: 验证 syntax**

```bash
python -c "from yt_pipeline.model import Task; print(Task(url='x'))"
```

Expected: `Task(url='x', state='pending', ...)` 无报错。

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/model.py
git commit -m "refactor: remove 4 dead fields from Task (title, credits_path, strategy, output_path)"
```

---

### Task 2: 更新 persistence.py —— 删除序列化字段

**Files:**
- Modify: `yt_pipeline/persistence.py:11-22`

- [ ] **Step 1: 从 _SERIALIZED_FIELDS 删除 3 项**

`title` 本就不在列表中，只需删除 `credits_path`、`strategy`、`output_path`：

```python
_SERIALIZED_FIELDS = [
    "url",
    "state",
    "error",
    "video_id",
    "video_path",
    "thumbnail_path",
    "ffmpeg_command",
]
```

- [ ] **Step 2: 验证序列化兼容性 —— 旧格式 progress.json 反序列化不会崩溃**

```python
import json
from pathlib import Path
from yt_pipeline.persistence import load_progress

# 模拟旧格式（包含已删除字段）
old_data = {
    "tasks": [{
        "url": "x", "state": "pending", "error": None,
        "video_id": None, "video_path": None, "thumbnail_path": None,
        "credits_path": None, "strategy": None, "output_path": None,
        "ffmpeg_command": None
    }]
}
p = Path("test_old_progress.json")
p.write_text(json.dumps(old_data))
tasks = load_progress(p)
p.unlink()
print(f"Loaded: {tasks[0]}")
```

Expected: `Task(url='x', state='pending', ...)` 正常加载（`Task(**kwargs)` 忽略多余键）。

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/persistence.py
git commit -m "refactor: remove dead fields from progress serialization"
```

---

### Task 3: 更新 download_worker.py —— 移除 title 和 credits_path 写入

**Files:**
- Modify: `yt_pipeline/download_worker.py:106,122,142,151-152`

- [ ] **Step 1: generate_credits() 改为无返回值**

将函数签名从 `-> Path` 改为 `-> None`，删除 `return out_path`（第 122 行）：

```python
def generate_credits(info: dict, source_url: str, video_path: Path) -> None:
    """从 yt-dlp info dict 生成来源文案 .description 文件。"""
    channel = info.get("channel") or "未知"
    title = info.get("title") or "未知"
    description = info.get("description") or ""

    out_path = video_path.with_suffix(".description")
    text = (
        f"{source_url}\n"
        f"原作者：{channel}\n"
        f"原标题：{title}\n"
        "转载经原作者允许\n"
        "请各位观众在条件允许的情况下访问视频原始发布地址以支持原作者\n\n\n"
        f"{description}"
    )
    out_path.write_text(text, encoding="utf-8")
```

- [ ] **Step 2: 删除 download_video() 中的 title 和 credits_path 赋值**

删除第 142 行 `task.title = info.get("title")` 和第 151-152 行的两行，改为直接调用：

```python
    task.video_id = video_id
    task.video_path = str(video_path)

    for ext in IMAGE_EXTS:
        candidate = video_path.with_suffix(ext)
        if candidate.exists():
            task.thumbnail_path = str(candidate)
            break

    generate_credits(info, task.url, video_path)
```

- [ ] **Step 3: 验证 download_worker 模块导入无语法错误**

```bash
python -c "from yt_pipeline.download_worker import download_video, generate_credits, find_thumbnail; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add yt_pipeline/download_worker.py
git commit -m "refactor: remove title/credits_path writes from download_worker"
```

---

### Task 4: 更新 assessment_worker.py —— 移除 strategy 和 output_path 写入

**Files:**
- Modify: `yt_pipeline/assessment_worker.py:250-252`

- [ ] **Step 1: 删除 strategy 和 output_path 赋值**

将第 249-253 行从：

```python
            else:
                cmd, output = build_ffmpeg_command(video_path, strategy)
                task.strategy = strategy
                task.output_path = str(output)
                task.ffmpeg_command = cmd
```

改为：

```python
            else:
                cmd, _ = build_ffmpeg_command(video_path, strategy)
                task.ffmpeg_command = cmd
```

- [ ] **Step 2: 验证 assessment_worker 模块导入**

```bash
python -c "from yt_pipeline.assessment_worker import assessment_worker; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/assessment_worker.py
git commit -m "refactor: remove strategy/output_path writes from assessment_worker"
```

---

### Task 5: 更新 conftest.py —— 移除 mock 中的 title 和 credits_path

**Files:**
- Modify: `tests/conftest.py:64,69-70`

- [ ] **Step 1: 从 mock_download 删除 title 和 credits_path 赋值**

删除第 64 行 `task.title = "Test Video"` 和第 69-70 行：

```python
    async def mock_download(task, _shutdown):
        task.state = States.DOWNLOADING
        task.video_id = "test123"
        task.video_path = str(tmp_path / "test123.mp4")
        Path(task.video_path).touch()
        task.thumbnail_path = str(tmp_path / "test123.png")
        Path(task.thumbnail_path).touch()
        dl_started.set()
        await dl_proceed.wait()
        if _shutdown.is_set:
            raise asyncio.CancelledError("Download cancelled by shutdown")
        task.state = States.DOWNLOADED
```

注意：`credits_path` 相关的文件写入（`Path(task.credits_path).write_text("credits", encoding="utf-8")`）也要一并删除。

- [ ] **Step 2: 运行 pipeline 测试确认 mock 未破坏**

```bash
pytest tests/test_pipeline.py -v
```

Expected: 全部 6 个测试通过。

- [ ] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: remove title/credits_path from mock_download fixture"
```

---

### Task 6: 更新 test_pipeline.py —— 移除测试数据中的 strategy 引用

**Files:**
- Modify: `tests/test_pipeline.py:46,195`

- [ ] **Step 1: 从 _pv() helper 删除 strategy**

第 41-50 行，删除 `"strategy": "upscale_4k"` 这一行：

```python
def _pv(n: int) -> list[dict]:
    """构造 processing_video 状态。"""
    return [
        {
            "url": _URL.format(i + 1),
            "state": States.PROCESSING_VIDEO,
            "error": None,
            "video_path": f"/tmp/example.com_video{i + 1}.mp4",
        }
        for i in range(n)
    ]
```

- [ ] **Step 2: 从 test_resume_after_ffmpeg_interrupt 的 Task 构造删除 strategy**

第 191-198 行，删除 `strategy="upscale_4k"` 参数：

```python
    tasks = [
        Task(
            url="https://example.com/video1",
            state=States.PROCESSING_VIDEO,
            video_path="/tmp/example.com_video1.mp4",
        ),
    ]
```

- [ ] **Step 3: 运行全量测试**

```bash
pytest tests/test_pipeline.py tests/unit/ -v
```

Expected: 全部测试通过。

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline.py
git commit -m "test: remove strategy references from pipeline tests"
```

---

### Task 7: 最终验证 —— 全量测试 + lint

**Files:**
- None (verify only)

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/ -v
```

Expected: 全部通过，0 失败。

- [ ] **Step 2: 运行 lint**

```bash
ruff check .
```

Expected: 0 错误。

# url_collector + CLI 单元测试实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `url_collector.py` 和 `cli.py` 编写完整的单元测试，覆盖 URL 收集/过滤、交互输入、参数解析、任务准备和主流程调度。

**Architecture:** 方案 B — 共享 fixture + monkeypatch 混合。在 `tests/unit/conftest.py` 中新增 3 个可配置 fixture（`state_file`、`mock_load_progress`、`mock_collect_urls`），测试函数通过 fixture setter 注入预设值，个别测试额外 monkeypatch `input`/`_ClipboardMonitor` 等交互边界。

**Tech Stack:** pytest, pytest-asyncio（`asyncio_mode = "auto"` 已配置）, monkeypatch, capsys

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `tests/unit/conftest.py` | 修改 | 新增 `state_file`、`mock_load_progress`、`mock_collect_urls` fixture |
| `tests/unit/test_url_collector.py` | 创建 | url_collector 的 7 个测试 |
| `tests/unit/test_cli.py` | 创建 | cli 的 11 个测试 |

---

### Task 1: 更新 conftest.py — 新增共享 fixture

**Files:**
- Modify: `tests/unit/conftest.py`

- [ ] **Step 1: 在 conftest.py 末尾添加 3 个 fixture**

```python
@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """替换 cli 中的 STATE_FILE 到 tmp_path。"""
    sf = tmp_path / "progress.json"
    monkeypatch.setattr("yt_pipeline.cli.STATE_FILE", sf)
    return sf


@pytest.fixture
def mock_load_progress(monkeypatch):
    """替换 load_progress，返回可配置的预设值。用法：mock_load_progress(tasks_list)"""
    _return = [None]

    def _set(tasks):
        _return[0] = tasks

    monkeypatch.setattr("yt_pipeline.cli.load_progress", lambda _: _return[0])
    return _set


@pytest.fixture
def mock_collect_urls(monkeypatch):
    """替换 collect_urls，返回可配置的预设值。用法：mock_collect_urls(["url1"])"""
    _return = [[]]

    def _set(urls):
        _return[0] = urls

    monkeypatch.setattr("yt_pipeline.cli.collect_urls", lambda *a: _return[0])
    return _set
```

- [ ] **Step 2: 验证 fixture 可导入**

Run: `python -c "from tests.unit.conftest import state_file, mock_load_progress, mock_collect_urls; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/unit/conftest.py
git commit -m "test: add shared fixtures for cli unit tests (state_file, mock_load_progress, mock_collect_urls)"
```

---

### Task 2: test_url_collector.py — 纯函数测试（无需 mock）

**Files:**
- Create: `tests/unit/test_url_collector.py`

- [ ] **Step 1: 创建测试文件，写入 4 个纯函数测试**

```python
"""url_collector 单元测试：URL 收集、过滤、文件读取。"""

from pathlib import Path

from yt_pipeline.url_collector import collect_urls, _filter


class TestCollectUrlsFromFile:
    def test_collect_urls_from_file(self, tmp_path: Path):
        path = tmp_path / "urls.txt"
        path.write_text(
            "https://youtube.com/watch?v=abc123\n"
            "AbCdEfGhIjK\n"
            "\n",
            encoding="utf-8",
        )
        result = collect_urls(file_path=str(path))
        assert len(result) == 2
        assert result[0] == "https://youtube.com/watch?v=abc123"
        assert result[1] == "AbCdEfGhIjK"

    def test_collect_urls_from_file_empty(self, tmp_path: Path, capsys):
        path = tmp_path / "urls.txt"
        path.write_text("\nnot a url\n  \n", encoding="utf-8")
        result = collect_urls(file_path=str(path))
        assert result == []
        assert "No valid links were found in the file." in capsys.readouterr().out


class TestCollectUrlsFromList:
    def test_collect_urls_from_list(self):
        result = collect_urls(
            urls=["https://a.com", "https://b.com", "https://a.com"]
        )
        assert result == ["https://a.com", "https://b.com"]


class TestFilterIsUrlVariants:
    def test_filter_is_url_variants(self):
        result = _filter(
            [
                "https://youtube.com/watch?v=x",
                "AbCdEfGhIjK",
                "ftp://example.com",
                "short",
                "",
            ]
        )
        assert result == ["https://youtube.com/watch?v=x", "AbCdEfGhIjK"]
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/unit/test_url_collector.py -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_url_collector.py
git commit -m "test: add pure-function url_collector tests (file, list, filter)"
```

---

### Task 3: test_url_collector.py — 交互测试（需要 mock）

**Files:**
- Modify: `tests/unit/test_url_collector.py`

- [ ] **Step 1: 在文件末尾追加辅助函数和 3 个交互测试**

```python
import pytest


def make_input_sequence(responses: list[str]):
    """返回一个 input() 替身，依次返回 responses，用完抛 EOFError。"""
    it = iter(responses)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return _input


class TestFromInput:
    def test_from_input_typed_and_clipboard(self, monkeypatch):
        class FakeMonitor:
            def start(self): ...
            def stop(self):
                return ["https://clip.com"]

        monkeypatch.setattr(
            "yt_pipeline.url_collector._ClipboardMonitor", FakeMonitor
        )
        monkeypatch.setattr(
            "builtins.input", make_input_sequence(["https://typed.com", "y"])
        )
        result = collect_urls()
        assert "https://typed.com" in result
        assert "https://clip.com" in result

    def test_from_input_cancel_eof(self, monkeypatch):
        class FakeMonitor:
            def __init__(self):
                self.stopped = False

            def start(self): ...

            def stop(self):
                self.stopped = True
                return []

        fake = FakeMonitor()
        monkeypatch.setattr(
            "yt_pipeline.url_collector._ClipboardMonitor",
            lambda: fake,
        )
        monkeypatch.setattr("builtins.input", make_input_sequence([]))
        result = collect_urls()
        assert result == []
        assert fake.stopped

    def test_clipboard_monitor_no_pyperclip(self, monkeypatch):
        monkeypatch.setattr("yt_pipeline.url_collector.pyperclip", None)
        from yt_pipeline.url_collector import _ClipboardMonitor

        monitor = _ClipboardMonitor()
        monitor.start()
        result = monitor.stop()
        assert monitor._thread is None
        assert result == []
```

- [ ] **Step 2: 运行全部 url_collector 测试验证通过**

Run: `pytest tests/unit/test_url_collector.py -v`
Expected: 7 passed

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_url_collector.py
git commit -m "test: add interactive url_collector tests (input, clipboard, eof)"
```

---

### Task 4: test_cli.py — parse_args 测试（无需 mock）

**Files:**
- Create: `tests/unit/test_cli.py`

- [ ] **Step 1: 创建测试文件，写入 4 个 parse_args 测试**

```python
"""cli 单元测试：参数解析、任务准备、主流程调度。"""

import argparse

import pytest

from yt_pipeline.cli import parse_args, prepare_tasks
from yt_pipeline.model import Task, States, RESUME_RESET


class TestParseArgs:
    def test_parse_args_defaults(self):
        args = parse_args([])
        assert args.resume is False
        assert args.fresh is False
        assert args.file is None
        assert args.urls == []

    def test_parse_args_resume_and_urls(self):
        args = parse_args(["--resume", "https://a.com"])
        assert args.resume is True
        assert args.urls == ["https://a.com"]

    def test_parse_args_fresh_and_file(self):
        args = parse_args(["--fresh", "--file", "urls.txt"])
        assert args.fresh is True
        assert args.file == "urls.txt"

    def test_parse_args_resume_fresh_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(["--resume", "--fresh"])
```

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/unit/test_cli.py::TestParseArgs -v`
Expected: 4 passed

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add parse_args cli tests (defaults, flags, mutual exclusion)"
```

---

### Task 5: test_cli.py — prepare_tasks 测试（需要 fixture + mock）

**Files:**
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: 在文件末尾追加 prepare_tasks 测试类**

```python
class TestPrepareTasks:
    def test_prepare_tasks_fresh(
        self, state_file, mock_load_progress, mock_collect_urls
    ):
        mock_load_progress([Task(url="https://old.com", state=States.DOWNLOADING)])
        mock_collect_urls(["https://a.com"])
        state_file.write_text("{}", encoding="utf-8")  # create the file

        args = argparse.Namespace(resume=False, fresh=True, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert not state_file.exists()
        assert len(tasks) == 1
        assert tasks[0].url == "https://a.com"
        assert tasks[0].state == States.PENDING

    def test_prepare_tasks_resume(self, state_file, mock_load_progress):
        saved = [Task(url="https://old.com", state=States.DOWNLOADING)]
        mock_load_progress(saved)

        args = argparse.Namespace(resume=True, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert len(tasks) == 1
        assert tasks[0].state == States.PENDING  # DOWNLOADING → PENDING via RESUME_RESET

    def test_prepare_tasks_prompt_yes(self, state_file, mock_load_progress, monkeypatch):
        saved = [Task(url="https://old.com", state=States.DOWNLOADING)]
        mock_load_progress(saved)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        args = argparse.Namespace(resume=False, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert tasks[0].state == States.PENDING

    def test_prepare_tasks_prompt_no(
        self, state_file, mock_load_progress, mock_collect_urls, monkeypatch
    ):
        saved = [Task(url="https://old.com", state=States.DOWNLOADING)]
        mock_load_progress(saved)
        mock_collect_urls(["https://new.com"])
        state_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        args = argparse.Namespace(resume=False, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert not state_file.exists()
        assert len(tasks) == 1
        assert tasks[0].url == "https://new.com"

    def test_prepare_tasks_no_urls(self, mock_load_progress, mock_collect_urls):
        mock_load_progress(None)
        mock_collect_urls([])

        args = argparse.Namespace(resume=False, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert tasks == []
```

- [ ] **Step 2: 运行 prepare_tasks 测试验证通过**

Run: `pytest tests/unit/test_cli.py::TestPrepareTasks -v`
Expected: 5 passed

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add prepare_tasks cli tests (fresh, resume, prompt, no_urls)"
```

---

### Task 6: test_cli.py — main() 测试（需要 mock asyncio + logging）

**Files:**
- Modify: `tests/unit/test_cli.py`

- [ ] **Step 1: 在文件末尾追加 main() 测试类**

```python
from unittest.mock import MagicMock


class TestMain:
    def test_main_no_tasks(self, monkeypatch):
        monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.prepare_tasks", lambda args: [])
        mock_run = MagicMock()
        monkeypatch.setattr("asyncio.run", mock_run)

        from yt_pipeline.cli import main

        main()
        mock_run.assert_not_called()

    def test_main_with_tasks(self, monkeypatch):
        monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)
        monkeypatch.setattr(
            "yt_pipeline.cli.prepare_tasks",
            lambda args: [Task(url="https://a.com")],
        )
        mock_run = MagicMock()
        monkeypatch.setattr("asyncio.run", mock_run)

        from yt_pipeline.cli import main

        main()
        mock_run.assert_called_once()
```

- [ ] **Step 2: 运行全部 cli 测试验证通过**

Run: `pytest tests/unit/test_cli.py -v`
Expected: 11 passed

- [ ] **Step 3: 运行全部单元测试确认无回归**

Run: `pytest tests/unit/ -v`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_cli.py
git commit -m "test: add main() cli tests (no_tasks, with_tasks)"
```

---

### Task 7: 最终验证

- [ ] **Step 1: 运行全部测试确认无回归**

Run: `pytest tests/unit/ -v`
Expected: 全部通过，url_collector 7 个 + cli 11 个 + 原有 models/download/strategy/thumbnail 测试

- [ ] **Step 2: 运行 ruff 检查测试文件**

Run: `ruff check tests/unit/test_url_collector.py tests/unit/test_cli.py`
Expected: 无错误

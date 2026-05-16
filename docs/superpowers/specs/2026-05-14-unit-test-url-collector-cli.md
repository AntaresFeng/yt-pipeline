# 单元测试设计：url_collector + CLI

## 目标

覆盖 `url_collector.py` 的 URL 收集/过滤逻辑和 `cli.py` 的参数解析/任务准备流程。纯函数逻辑直接断言，交互分支用 `monkeypatch` 模拟 `input` 和 `pyperclip`，不启动事件循环、不调用外部进程。

## 范围

### 在范围内

- `collect_urls` 三条分支（file / urls / 交互输入）
- `_filter` 去重 + `_is_url` 合法性判断
- `_from_input` 的交互流程（typed 输入 + clipboard 合并）
- `_ClipboardMonitor` 在无 `pyperclip` 时的容错
- `parse_args` 各种 argv 组合
- `prepare_tasks` 的 resume / fresh / prompt 分支 + RESUME_RESET 回退
- `main()` 的基本调度路径

### 不在范围内

- 真实剪贴板读写
- 真实信号处理 / asyncio.run
- pipeline worker 编排（由集成测试覆盖）
- `_confirm` 的独立测试（由 `_from_input` 测试间接覆盖）

## 测试文件结构

```
tests/unit/
  conftest.py           # 新增：state_file, mock_load_progress, mock_collect_urls
  test_url_collector.py # 7 个测试
  test_cli.py           # 11 个测试
  test_models.py        # 保持不变
  test_download.py      # 保持不变
  test_strategy.py      # 保持不变
  test_thumbnail.py     # 保持不变
```

---

## 共享 Fixture（`tests/unit/conftest.py`）

在现有 `chdir` fixture 基础上新增：

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

---

## test_url_collector.py

### Mock 策略

| Mock 点 | 方式 | 说明 |
|---------|------|------|
| `pyperclip` | `monkeypatch.setattr("yt_pipeline.url_collector.pyperclip", ...)` | 注入 fake 或 None |
| `builtins.input` | `monkeypatch.setattr("builtins.input", ...)` | 传入预设输入序列 |
| `_ClipboardMonitor` | `monkeypatch.setattr("yt_pipeline.url_collector._ClipboardMonitor", FakeMonitor)` | 避免真实线程 |

### 辅助函数

```python
def make_input_sequence(responses: list[str]):
    """返回一个 input() 替身，依次返回 responses，用完抛 EOFError。"""
    it = iter(responses)
    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError
    return _input
```

### 测试用例

#### test_collect_urls_from_file

- 输入：`tmp_path / "urls.txt"` 写入 3 行（1 个有效 https URL、1 个 11 字符 ID、1 个空行）
- 调用：`collect_urls(file_path=str(path))`
- 断言：返回 2 个 URL（https 前缀保留，短 ID 保留）

#### test_collect_urls_from_file_empty

- 输入：文件只含空行和无效文本
- 断言：返回 `[]`，stdout 含 `"No valid links were found in the file."`

#### test_collect_urls_from_list

- 输入：`collect_urls(urls=["https://a.com", "https://b.com", "https://a.com"])`
- 断言：去重后返回 2 个

#### test_filter_is_url_variants

- 直接调用 `_filter`，传入混合列表：
  - `"https://youtube.com/watch?v=x"` → 保留
  - `"AbCdEfGhIjK"` (11 字符 ID) → 保留
  - `"ftp://example.com"` → 过滤（非 http/https）
  - `"short"` → 过滤（非 11 字符）
  - `""` → 过滤
- 断言：仅保留前两项

#### test_from_input_typed_and_clipboard

- Mock：`input` → 先返回 typed URL，再返回 `"y"`（confirm）
- Mock：`_ClipboardMonitor` 替换为 `FakeMonitor`，`stop()` 返回 `["https://clip.com"]`
- 调用：`collect_urls()`（无 urls、无 file_path）
- 断言：返回含 typed + clipboard 的列表

#### test_from_input_cancel_eof

- Mock：`input` → 抛 `EOFError`
- 断言：返回 `[]`，`FakeMonitor.stop()` 被调用

#### test_clipboard_monitor_no_pyperclip

- Mock：`monkeypatch.setattr("yt_pipeline.url_collector.pyperclip", None)`
- 调用：创建 `_ClipboardMonitor()`，调用 `start()` + `stop()`
- 断言：`start()` 不启动线程（`_thread is None`），`stop()` 返回 `[]`

---

## test_cli.py

### Mock 策略

| Mock 点 | 方式 | 说明 |
|---------|------|------|
| `load_progress` | `mock_load_progress` fixture | 返回预设 tasks 或 None |
| `collect_urls` | `mock_collect_urls` fixture | 返回预设 URL 列表 |
| `STATE_FILE` | `state_file` fixture | 避免写真实文件 |
| `builtins.input` | `monkeypatch.setattr("builtins.input", ...)` | 模拟用户选择 |
| `prepare_tasks` | `monkeypatch.setattr("yt_pipeline.cli.prepare_tasks", ...)` | main() 测试中直接控制返回值 |
| `_setup_logging` | `monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)` | main() 测试中避免副作用全局 logging |
| `asyncio.run` | `monkeypatch.setattr("asyncio.run", lambda coro: None)` | 阻止真实事件循环 |

### 测试用例

#### test_parse_args_defaults

- 输入：`parse_args([])`
- 断言：`resume=False, fresh=False, file=None, urls=[]`

#### test_parse_args_resume_and_urls

- 输入：`parse_args(["--resume", "https://a.com"])`
- 断言：`resume=True, urls=["https://a.com"]`

#### test_parse_args_fresh_and_file

- 输入：`parse_args(["--fresh", "--file", "urls.txt"])`
- 断言：`fresh=True, file="urls.txt"`

#### test_parse_args_resume_fresh_exclusive

- 输入：`parse_args(["--resume", "--fresh"])`
- 断言：`raises SystemExit`（互斥组冲突）

#### test_prepare_tasks_fresh

- 预设：`mock_load_progress` 设置含 1 个 DOWNLOADING task 的列表；`mock_collect_urls` 设置 `["https://a.com"]`；`state_file` 已创建
- 输入：`args.fresh=True`
- 断言：`state_file` 不存在（被删除），返回新 task 列表（url="https://a.com"）

#### test_prepare_tasks_resume

- 预设：`mock_load_progress` 设置含 1 个 DOWNLOADING task 的列表
- 输入：`args.resume=True`
- 断言：task 的 state 被回退为 PENDING（`RESUME_RESET` 映射），`collect_urls` 未被调用

#### test_prepare_tasks_prompt_yes

- 预设：`mock_load_progress` 设置含 tasks 的列表；`input` 返回 `"y"`
- 断言：同 resume 路径，task 状态被回退

#### test_prepare_tasks_prompt_no

- 预设：`mock_load_progress` 设置含 tasks 的列表；`input` 返回 `"n"`
- 断言：`state_file` 被删除，`collect_urls` 被调用

#### test_prepare_tasks_no_urls

- 预设：`mock_load_progress` 返回 None；`mock_collect_urls` 返回 `[]`
- 断言：返回空列表

#### test_main_no_tasks

- Mock：`prepare_tasks` 返回 `[]`；`_setup_logging` 替身为 no-op
- 调用：`main()`
- 断言：`asyncio.run` 未被调用

#### test_main_with_tasks

- Mock：`prepare_tasks` 返回含 1 个 task 的列表；`_setup_logging` 替身为 no-op；`asyncio.run` 替身为 no-op
- 调用：`main()`
- 断言：`asyncio.run` 被调用一次

## 实现约束

- 不修改生产代码来适应测试
- 交互测试全部用 `monkeypatch` 替换 `input`，不依赖终端
- `STATE_FILE` 必须替换到 `tmp_path`，避免写真实项目目录
- `_ClipboardMonitor` 测试中不启动真实线程

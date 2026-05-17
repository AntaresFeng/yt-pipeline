# Resume 终态处理改进设计

**目标**：改进 resume 时 DONE/FAILED 任务的处理——DONE 过滤移除、FAILED 可重试、错误历史可追溯、progress.json 有 FAILED 时不删除。

## 问题

1. **DONE/FAILED 在 resume 时无明确处理**：`RESUME_RESET` 不含这两个终态，`prepare_tasks` 不过滤，`run_pipeline` 不入队——任务静默跳过，无日志。
2. **FAILED 任务无法重试**：全部终态时 progress.json 被删除，错误信息随之消失，用户无重试机会。
3. **error 字段只记录最近一次错误**：重试场景下无法追溯历史。

## 方案：error → errors 统一错误历史

### 模型层（model.py）

- `Task.error: str | None = None` → `Task.errors: list[str] = field(default_factory=list)`
- `RESUME_RESET` 新增：`States.FAILED: States.PENDING`

### 持久化层（persistence.py）

- `load_progress` 增加旧格式兼容：JSON 中 task 有 `error` 字段且非 null → `errors=[error]`；`error` 为 null 或不存在且 `errors` 也不存在 → `errors=[]`

### 错误处理（utils.py）

- `handle_worker_error`：`task.error = str(error)` → `task.errors.append(str(error))`
- 日志：`logger.error("[%s] failed (attempt %d): %s", task.url, len(task.errors), error)`

### Resume 逻辑（cli.py）

- `prepare_tasks`：DONE 任务从列表移除；FAILED 任务经 RESUME_RESET 回退到 PENDING，errors 保留
- 对 FAILED 任务打印日志：`"Retrying failed task: %s (previous errors: %d)"`

### Pipeline 删除条件（pipeline.py）

- 删除 progress.json 条件从 `all(t.state in TERMINAL_STATES)` 改为 `all(t.state == States.DONE)`
- 有 FAILED 任务时保留文件，日志：`"Pipeline stopped, %d tasks failed. Resume to retry."`

### 测试改动

- `test_pipeline_integration.py`：`task.error` → `task.errors[-1]`（两处断言）
- 新增测试：
  - resume 时 DONE 任务被过滤
  - resume 时 FAILED→PENDING 重试
  - 混合 DONE+FAILED 场景 progress.json 保留

### 影响范围

| 文件 | 改动 |
|------|------|
| `model.py` | Task.error→errors，RESUME_RESET 新增 FAILED |
| `persistence.py` | load_progress 旧格式兼容 |
| `utils.py` | handle_worker_error 改 append + 日志改 attempt |
| `cli.py` | prepare_tasks 过滤 DONE + FAILED 重试日志 |
| `pipeline.py` | 删除条件改为全 DONE |
| `test_pipeline_integration.py` | error→errors[-1] + 3 个新测试 |

不涉及 worker 内部逻辑、config、url_collector。

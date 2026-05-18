# Assessment 状态简化 + 持久化精简设计

## 背景

assessment 阶段包含封面探测、封面处理、视频探测三个快速步骤（秒级完成，幂等，无不可逆副作用）。当前用三个中间态 `PROBING_COVER` / `PROCESSING_COVER` / `PROBING_VIDEO` 跟踪，且每步都调用 `save_all_progress`，造成不必要的持久化开销和状态复杂度。

## 变更

### 状态机

Before:
```
DOWNLOADED → PROBING_COVER → PROCESSING_COVER → PROBING_VIDEO → PROCESSING_VIDEO / DONE
```

After:
```
DOWNLOADED → ASSESSING → PROCESSING_VIDEO / DONE
```

- 删除 `PROBING_COVER`、`PROCESSING_COVER`、`PROBING_VIDEO`
- 新增 `ASSESSING`（值为 `"assessing"`）
- `RESUME_RESET` 删除三行旧映射，新增 `ASSESSING: DOWNLOADED`

### assessment_worker

- 进入时设 `task.state = States.ASSESSING`，只设一次
- 持久化只在两个终态：`DONE` 或进入 `PROCESSING_VIDEO` 时
- CancelledError：回退到 `DOWNLOADED`，**不保存**（与 download_worker/transcode_worker 一致）
- 异常处理：走 `handle_worker_error`（标记 FAILED + 保存），不变

简化后逻辑流：
```python
task.state = States.ASSESSING
# probe + process_thumbnail + decide + build_command（全在 ASSESSING 下完成）
if strategy == C.STRATEGY_SKIP:
    task.state = States.DONE
    save_all_progress(tasks, state_file)
else:
    task.ffmpeg_command = cmd
    task.state = States.PROCESSING_VIDEO
    save_all_progress(tasks, state_file)
    await transcode_queue.put(task)
```

### 其他文件

| 文件 | 变更 |
|------|------|
| `model.py` | States 删三加一，RESUME_RESET 删三加一 |
| `pipeline.py` | 无变更（ASSESSING 经 RESUME_RESET 变 DOWNLOADED，无需额外分发逻辑） |
| `download_worker.py` | 无变更 |
| `transcode_worker.py` | 无变更 |
| `utils.py` | 无变更 |
| `persistence.py` | 无变更 |

### 测试

| 文件 | 变更 |
|------|------|
| `test_pipeline_integration.py` | shutdown_during_assessment 测试：任务状态从 PROBING_COVER 等变为 ASSESSING，CancelledError 回退到 DOWNLOADED，不保存 |
| `test_strategy.py` | 无变更 |
| `test_persistence.py` | 无变更 |

## 风险

- ASSESSING 状态中断后重做整个 assessment：可接受，因为 assessment 幂等且快速
- 封面处理已有文件副作用（生成 `_169_2x` 文件），重做时会被覆盖，无问题

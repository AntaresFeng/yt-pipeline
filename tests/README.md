# Tests

## 目录结构

```
tests/
  unit/                         # 单元测试：隔离函数/类级别
    conftest.py                 # 共享 fixture（chdir, state_file, mock_load_progress, mock_collect_urls）
    test_download.py            # download_worker 纯函数
    test_deps.py                # 外部依赖检测
    test_thumbnail.py           # find_thumbnail
    test_models.py              # StreamSpec 属性
    test_strategy.py            # 策略决策 + 转码命令构建
    test_cli.py                 # CLI 参数解析、任务准备、主流程
    test_url_collector.py       # URL 收集、过滤、剪贴板监控
  integration/                  # 集成测试：验证 worker 间编排逻辑
    conftest.py                 # 共享 fixture（mock_download, mock_subprocess, mock_transcode, pipeline_env, gate）
    test_pipeline_integration.py  # 12 个端到端场景
```

## 运行方式

```bash
# 日常开发：跑改动的模块
pytest tests/unit/test_download.py -v
pytest tests/integration/test_pipeline_integration.py::TestShutdown -v

# 重构/大修后：全量测试
pytest tests/ -v

# 代码检查
ruff check tests/
```

## 单元测试（63 个）

| 测试文件 | 测试数 | 覆盖函数 |
|----------|--------|----------|
| `test_models.py` | 3 | `StreamSpec` 属性（short_edge, long_edge, ratio） |
| `test_download.py` | 9 | `generate_credits`（正常 + 缺字段），`resolve_video_path`，`WorkerLogger` |
| `test_deps.py` | 14 | 依赖路径解析、可执行性验证、ffmpeg/ffprobe/NVEncC 检测 |
| `test_thumbnail.py` | 3 | `find_thumbnail`（扩展名匹配 / video_id glob / 无封面） |
| `test_strategy.py` | 13 | `decide_video_strategy`，`build_transcode_command`（NVEncC / ffmpeg / 非法策略 / 非法后端 / 幂等输出路径） |
| `test_cli.py` | 14 | `parse_args`，`prepare_tasks`，`main` |
| `test_url_collector.py` | 7 | `collect_urls`（文件/列表/交互式输入），`_filter`（URL 变体过滤），`_ClipboardMonitor`（正常/无 pyperclip） |

## 集成测试（12 个）

Mock 最低外部边界（`_do_download`、`run_command`、`run_transcode`），业务逻辑全真实执行。使用 `asyncio.Event`（gate）控制 shutdown 时序。

| 场景类 | 测试数 | 验证内容 |
|--------|--------|----------|
| `TestFullPipeline` | 2 | upscale_4k（1920x1081→NVEncC output-res 3840x2160）、pad_1600（3840x1081→NVEncC pad 0,260,0,260）全链路 pending→done |
| `TestSkipStrategy` | 1 | 1920x1080 skip：不经 processing_video，run_transcode 未被调用 |
| `TestShutdown` | 3 | download/assessment/transcode 阶段触发 shutdown，任务分别保留 DOWNLOADING / DOWNLOADED / PROCESSING_VIDEO 状态 |
| `TestResume` | 1 | DOWNLOADING 中断恢复：RESUME_RESET 回退到 PENDING→重新走完全链路 |
| `TestFailure` | 2 | ffprobe 异常退出→FAILED + error 含 "ffprobe"；transcode 异常退出→FAILED + error 含 "transcode" |
| `TestResumeTerminalStates` | 3 | DONE 过滤、FAILED 重试、混合 DONE+FAILED 进度保留 |

## 覆盖全景

### 按源码模块

| 源码模块 | 单元测试 | 集成测试间接覆盖 | 未覆盖 |
|----------|---------|-----------------|--------|
| `model.py` | `StreamSpec` 属性 | `Task`、`States`、`RESUME_RESET` | — |
| `config.py` | — | 常量被策略/命令构建测试引用 | — |
| `download_worker.py` | `generate_credits`、`resolve_video_path`、`find_thumbnail` | `download_video`、`download_worker` | `find_media_file` |
| `assessment_worker.py` | `decide_video_strategy`、`build_transcode_command` | `assessment_worker` | `probe`、`process_thumbnail`、`run_command` |
| `transcode_worker.py` | — | `transcode_worker`（mock 替换） | `run_transcode`（stdin `q` 指令、进程组隔离） |
| `deps.py` | `_resolve_tool_path`、`_verify_executable`、`check_dependencies` | — | — |
| `persistence.py` | — | `save_all_progress` / `load_progress`（resume 测试） | 原子写入 .tmp→replace 逻辑、损坏 JSON 处理 |
| `utils.py` | — | `handle_worker_error`（failure 测试） | — |
| `pipeline.py` | — | `run_pipeline`（9 个场景全覆盖） | `ShutdownManager.attach`、`_drain_queue`、`_join_or_shutdown` |
| `cli.py` | 全覆盖 | — | — |
| `url_collector.py` | 全覆盖 | — | — |

### 按测试层级

| 层级 | 状态 |
|------|------|
| 纯函数 / 数据类 | 覆盖充分 |
| async worker 协程 | 仅集成测试间接覆盖，无隔离单元测试 |
| 外部边界（yt-dlp / ffmpeg / ffprobe / NVEncC） | 全部 mock，不依赖真实环境 |
| 状态机流转 | 主路径覆盖，ASSESSING 中间态已通过 shutdown 测试覆盖 |
| 优雅退出 | 3 个阶段均有测试，`run_transcode` 内部 stdin `q` 指令未验证 |

### 建议补充方向

1. **`persistence.py` 单元测试**：原子写入、损坏 JSON 处理、空文件回退
2. **`assessment_worker.probe` 单元测试**：ffprobe 输出解析、异常返回码
3. **`transcode_worker.run_transcode` 单元测试**：stdin `q` 指令发送、进程组隔离、超时处理
4. **状态机边界态测试**：ASSESSING 的 shutdown 和 resume 行为

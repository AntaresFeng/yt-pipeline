# AGENTS.md

## 沟通约定

使用中文与用户沟通。

## 项目架构

视频批处理流水线 —— Python asyncio：yt-dlp 下载 → ffprobe 探测 → 策略决策 → NVEncC/ffmpeg 转码。

| 文件 | 职责 |
|------|------|
| `pipeline.py` | ShutdownManager、run_pipeline 编排器 |
| `download_worker.py` | yt-dlp 下载 + 封面查找 + credits 生成 |
| `assessment_worker.py` | ffprobe 探测、策略决策、封面处理、转码命令构建 |
| `transcode_worker.py` | 转码命令执行 + 优雅退出（独立进程组） |
| `model.py` | Task、States、StreamSpec、RESUME_RESET |
| `config.py` | 配置参数和业务常量 |
| `persistence.py` | progress.json 读写（原子写入 .tmp → replace） |
| `utils.py` | handle_worker_error |
| `deps.py` | 外部依赖检测（yt-dlp / ffmpeg / ffprobe / NVEncC） |
| `cli.py` | CLI 入口 |
| `url_collector.py` | URL 收集 |

## 命令

```bash
python main.py                                # 运行流水线
pytest tests/unit/test_xxx.py -v              # 模块测试（日常修改后）
pytest tests/unit/test_xxx.py::name -v        # 单函数测试
pytest tests/ -v                              # 全量测试（重构/大修后）
ruff check                                    # 代码检查
ruff format                                   # 代码格式化
```

## 处理策略

| 视频尺寸 | 策略 |
|----------|------|
| 竖屏 / 短边 ≤ 1080 / 短边 ≥ 1600 | 跳过 |
| 横向 1081–1599，比例 < 2.0 | 4K 超分 (3840×2160) |
| 横向 1081–1599，比例 ≥ 2.0 | 黑边填充到高 1600 |

默认转码后端：NVEncC（`PIPELINE_TRANSCODE_BACKEND=nvencc`）。

默认编码：HEVC, QVBR 23, Quality preset, 8-bit, AAC 192k。ffmpeg 后端使用 libsvtav1, preset 6, CRF 29, GOP 300, 10-bit, tune=0, 音频 copy, mkv 容器。

## 状态机

`pending → downloading → downloaded → assessing → processing_video → done`

任一步可进入 `failed`。中断恢复时按 `RESUME_RESET` 回退中间态到安全起点（`processing_video` 除外——直接恢复转码）。

## 关键机制

- **优雅退出**：ShutdownManager 监听 SIGINT/SIGBREAK → `asyncio.Event`；转码进程通过 stdin 发 `q` 优雅退出（`CREATE_NEW_PROCESS_GROUP` 隔离）
- **测试 mock**：pytest + monkeypatch 替换 worker 函数，`asyncio.Event` 控制执行时序，`shutdown.event.set()` 模拟 Ctrl+C

## 环境与工具

- **全局 Python**：始终使用系统全局 Python 环境，不要创建 venv
- **可用工具**：`rg`、`jq`、`fd`、`ruff` 可直接使用
- **安装依赖**：装新包前必须先告知用户并等待确认，不得擅自 `pip install`

## 编码规范

- **ffmpeg/ffprobe/NVEncC 命令列表**：必须用 `# fmt: off` / `# fmt: on` 包裹，语义连续的参数放同行
- **测试策略**：小改跑相关模块测试，重构/大修才跑全量，无需每次全局 `pytest tests/ -v`

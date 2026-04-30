# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 沟通约定

使用中文与用户沟通。

## 项目简介

视频批处理流水线 —— Python asyncio 实现：yt-dlp 下载、ffprobe 探测、策略决策（4K 超分/黑边填充）、ffmpeg 转码、优雅退出、断点续跑。

## 常用命令

```bash
# 运行流水线
python main.py --fresh https://youtube.com/watch?v=...  # 全新开始
python main.py --resume                                   # 从上次中断恢复
python main.py --dry-run                                  # 调试模式（无需网络，生成测试视频）
python main.py -f urls.txt                                # 从文件读取 URL

# 运行测试
pytest tests/ -v

# Windows Ctrl+C 信号机制验证
pytest tests/test_signals.py -v
```

## 包结构

```
main.py                          # 薄入口
yt_pipeline/
├── config.py      # PipelineConfig — download_concurrency / state_file / dry_run / mock_transcode
├── constants.py   # 业务常量：处理阈值、输出尺寸、编码参数
├── models.py      # ImageSpec / VideoSpec 数据类
├── task.py        # Task 模型 + States 常量 + RESUME_RESET 映射
├── shutdown.py    # ShutdownManager — asyncio.Event + 信号处理
├── process.py     # 通用异步子进程运行器：run_command / run_transcode
├── download.py    # 异步 yt-dlp 下载 + credits 生成
├── probe.py       # 异步 ffprobe 尺寸探测
├── thumbnail.py   # 封面查找 + 16:9 裁剪 / 2x 超分
├── strategy.py    # 策略引擎：skip / upscale_4k / pad_1600
├── transcoder.py  # 转码入口（调用 process.run_transcode）
├── workers.py     # download_worker / assessment_worker / transcode_worker
├── pipeline.py    # run_pipeline() 编排器（三队列：pending → assessment → transcode）
├── persistence.py # progress.json 原子读写
├── cli.py         # argparse CLI
└── url_collector.py  # URL 收集：文件 / CLI / 交互 / 剪贴板
scripts/
├── mock_ffmpeg.py          # 独立 ffmpeg mock 子进程（测试用）
└── generate_test_media.py  # ffmpeg lavfi 生成测试图片/视频
tests/
├── conftest.py            # PipelineProcess + fixtures + make_test_image/video
├── test_signals.py        # CTRL_BREAK_EVENT → asyncio.Event 链路验证
├── test_pipeline.py       # 7 个中断/恢复集成测试（--dry-run 模式）
├── test_models.py         # ImageSpec / VideoSpec 属性测试
├── test_strategy.py       # 策略决策 + 命令构建
├── test_process.py        # 异步子进程运行器
├── test_probe.py          # ffprobe 探测
├── test_thumbnail.py      # 封面查找与处理
├── test_download.py       # credits 生成 + 路径解析
└── test_transcoder.py     # 转码薄层 + shutdown
```

## 配置系统

`PipelineConfig`（frozen dataclass）仅保留运行时可变参数：

- `download_concurrency` (默认 4) — 并发下载数
- `state_file` (默认 progress.json) — 进度持久化路径
- `dry_run` (默认 False) — 调试模式，跳过网络下载，用 ffmpeg lavfi 生成测试视频
- `mock_transcode` (默认 False) — 测试用，用 mock_ffmpeg.py 替代真实 ffmpeg

固定业务规则在 `constants.py`（阈值、尺寸、编码参数）。

关键环境变量：`PIPELINE_DOWNLOAD_CONCURRENCY`、`PIPELINE_STATE_FILE`、`PIPELINE_DRY_RUN`、`PIPELINE_MOCK_TRANSCODE`

## 核心机制

- **优雅退出**：`ShutdownManager` 在 Windows 上注册 `SIGINT`（Ctrl+C）+ `SIGBREAK`（`CTRL_BREAK_EVENT`），通过 `call_soon_threadsafe` 设置 `asyncio.Event`
- **ffmpeg 隔离**：`process.run_transcode` 将子进程放入独立进程组 (`CREATE_NEW_PROCESS_GROUP`)，Ctrl+C 时通过 stdin 发 `q` 优雅退出
- **断点续跑**：`progress.json` 原子写入（`.tmp` → `replace`），恢复时 `RESUME_RESET` 映射将中间态回退到安全起点；ffmpeg_command 不持久化（恢复时由 assessment 重新生成）
- **测试框架**：pytest + `PipelineProcess` 封装子进程生命周期，`CTRL_BREAK_EVENT` 模拟用户中断；集成测试使用 `--dry-run` + `mock_transcode` 避免网络依赖

## 任务状态机

`pending` → `downloading` → `downloaded` → `probing_cover` → `processing_cover` → `probing_video` → `processing_video` → `done`

任何阶段都可能进入 `failed`。中断恢复时：`downloading` → `pending`，中间转码态 → `downloaded`（`processing_video` 除外——该状态原样保留，恢复时直接进入转码阶段）。

## 处理规则

| 视频尺寸 | 处理策略 |
|----------|----------|
| 竖屏 | 跳过 |
| 短边 ≤ 1080px | 跳过 |
| 短边 ≥ 1600px | 跳过 |
| 横向 1081-1599px，比例 < 2.0 | 升频到 4K (3840×2160) |
| 横向 1081-1599px，比例 ≥ 2.0 | 上下黑边到高 1600px |

编码：H.264 CRF 18, Slow 预设, AAC 192k

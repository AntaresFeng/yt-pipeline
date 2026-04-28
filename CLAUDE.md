# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 沟通约定

使用中文与用户沟通。

## 项目简介

视频批处理流水线 —— Python asyncio 实现，演示：优雅退出、断点续跑、并发下载 + 顺序转码。**此为异步流水线演示脚本，仅展示框架**

## 常用命令

```bash
# 运行流水线
python main.py --fresh                # 全新开始
python main.py --resume               # 从上次中断恢复
python main.py --fresh --fast         # 快速模式（测试用）
python -m yt_pipeline --fresh --fast  # 等价于上一条

# 运行测试
pytest tests/ -v

# Windows Ctrl+C 信号机制验证
pytest tests/test_signals.py -v
```

## 包结构

```
main.py                          # 薄入口
yt_pipeline/
├── config.py      # PipelineConfig — 集中化配置，from_env() / fast() / to_env()
├── task.py        # Task 模型 + States 常量 + RESUME_RESET 映射
├── shutdown.py    # ShutdownManager — 封装 asyncio.Event + 信号处理
├── persistence.py # progress.json 原子读写
├── mocks.py       # mock_download / mock_probe / mock_cover_process / mock_video_process
├── workers.py     # download_worker / assessment_worker / transcode_worker
├── pipeline.py    # run_pipeline() 编排器（三队列：pending → assessment → transcode）
└── cli.py         # argparse CLI
scripts/
└── mock_ffmpeg.py # 独立 ffmpeg mock 子进程
tests/
├── conftest.py        # PipelineProcess + fixtures
├── test_signals.py    # CTRL_BREAK_EVENT → asyncio.Event 链路验证
└── test_pipeline.py   # 10 个中断/恢复集成测试
```

## 配置系统

所有可配置项集中在 `PipelineConfig`（frozen dataclass）：

- `PipelineConfig.from_env(**overrides)` — 从环境变量加载，可精确覆盖
- `PipelineConfig.fast()` — 快速模式预设（延时缩短，3 帧 ffmpeg）
- `config.to_env()` — 序列化为环境变量 dict，用于传递给子进程（测试框架无需硬编码变量名）

关键环境变量：`PIPELINE_DOWNLOAD_DELAY`、`PIPELINE_PROBE_DELAY`、`PIPELINE_COVER_DELAY`、`MOCK_FFMPEG_FRAMES`、`MOCK_FFMPEG_FRAME_DELAY`、`PIPELINE_STATE_FILE`

## 核心机制

- **优雅退出**：`ShutdownManager` 在 Windows 上注册 `SIGINT`（键盘 Ctrl+C）+ `SIGBREAK`（程序化 `CTRL_BREAK_EVENT`），通过 `call_soon_threadsafe` 设置 `asyncio.Event`
- **ffmpeg 隔离**：`mock_video_process` 将子进程放入独立进程组 (`CREATE_NEW_PROCESS_GROUP`)，Ctrl+C 时通过 stdin 发 `q` 优雅退出
- **断点续跑**：`progress.json` 原子写入（`.tmp` → `replace`），恢复时 `RESUME_RESET` 映射将中间态回退到安全起点
- **测试框架**：pytest + `PipelineProcess` 封装子进程生命周期，`CTRL_BREAK_EVENT` 模拟用户中断，输出驱动触发 + 自动验证

## 任务状态机

`pending` → `downloading` → `downloaded` → `probing_cover` → `processing_cover` → `probing_video` → `processing_video` → `done`

任何阶段都可能进入 `failed`。中断恢复时：`downloading` → `pending`，中间转码态 → `downloaded`（`processing_video` 除外——该状态原样保留，恢复时直接进入转码阶段）。

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 沟通约定

使用中文与用户沟通。

## 项目简介

视频批处理流水线 —— Python asyncio 实现：yt-dlp 下载、ffprobe 探测、策略决策（4K 超分/黑边填充）、ffmpeg 转码、优雅退出、断点续跑。

## 常用命令

```bash
# 运行流水线(详见help)
python main.py

# 运行测试
pytest tests/ -v
```

## 核心机制

- **优雅退出**：`ShutdownManager` 在 Windows 上注册 `SIGINT`（Ctrl+C）+ `SIGBREAK`（`CTRL_BREAK_EVENT`），通过 `call_soon_threadsafe` 设置 `asyncio.Event`
- **ffmpeg 隔离**：`process.run_transcode` 将子进程放入独立进程组 (`CREATE_NEW_PROCESS_GROUP`)，Ctrl+C 时通过 stdin 发 `q` 优雅退出
- **断点续跑**：`progress.json` 原子写入（`.tmp` → `replace`），恢复时 `RESUME_RESET` 映射将中间态回退到安全起点
- **测试框架**：pytest + monkeypatch 替换业务函数（download_video / transcode_video / probe_dimensions），`asyncio.Event` 控制执行时序，`shutdown.event.set()` 模拟 Ctrl+C

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

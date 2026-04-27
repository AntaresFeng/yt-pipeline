# yt-pipeline

视频批处理流水线 —— 演示 Python asyncio 的优雅退出、断点续跑、并发下载 + 顺序转码模式。

## 快速开始

```bash
# 全新运行
python main.py --fresh

# 从上次中断恢复
python main.py --resume

# 快速模式（短延时，适合测试）
python main.py --fresh --fast

# 通过模块运行
python -m yt_pipeline --fresh --fast
```

## 配置

所有参数通过 `PipelineConfig` 统一管理（见 `yt_pipeline/config.py`）。可通过环境变量覆盖默认值：

| 变量 | 默认值 | 说明 |
|----------|---------|-------------|
| `PIPELINE_DOWNLOAD_CONCURRENCY` | 4 | 并行下载 worker 数 |
| `PIPELINE_DOWNLOAD_DELAY` | 2.0 | 模拟下载耗时（秒） |
| `PIPELINE_PROBE_DELAY` | 0.5 | 模拟探测耗时 |
| `PIPELINE_COVER_DELAY` | 1.0 | 模拟封面处理耗时 |
| `MOCK_FFMPEG_FRAMES` | 10 | mock ffmpeg 处理的帧数 |
| `MOCK_FFMPEG_FRAME_DELAY` | 1.0 | mock ffmpeg 每帧延时 |
| `PIPELINE_STATE_FILE` | progress.json | 断点续跑文件路径 |

使用 `--fast` 标志可应用预设的短延时（等价于测试配置）。

## CLI

```
usage: yt-pipeline [-h] [--resume | --fresh] [--fast] [--urls [URLS ...]]

options:
  -y, --resume    从保存的进度自动恢复
  -n, --fresh     丢弃保存的进度，全新开始
  --fast          使用缩短的延时（测试用）
  --urls [URLS]   自定义视频 URL 列表（默认：5 个示例 URL）
```

## 测试

```bash
pytest tests/ -v
```

测试套件覆盖：
- 下载阶段按 Ctrl+C
- ffmpeg 转码阶段按 Ctrl+C
- 探测阶段按 Ctrl+C
- 连续按两次 Ctrl+C（快速连续中断）
- 启动时立即按 Ctrl+C
- 下载中断后恢复
- ffmpeg 中断后恢复
- `-n` 标志自动丢弃旧进度
- 正常走完流程（无中断）

测试通过子进程启动流水线，在 Windows 上发送真实的 `CTRL_BREAK_EVENT` 信号来模拟用户键盘中断。

## 架构

详见 `CLAUDE.md`（中文）。

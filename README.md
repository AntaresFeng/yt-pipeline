# yt-pipeline

视频批处理流水线 —— Python asyncio 实现：yt-dlp 下载、ffprobe 探测、策略决策（4K 超分/黑边填充）、ffmpeg 转码、优雅退出、断点续跑。

## 快速开始

```bash
# 全新运行
python main.py --fresh https://youtube.com/watch?v=...

# 从上次中断恢复
python main.py --resume

# 从文件读取 URL
python main.py -f urls.txt

# 通过模块运行
python -m yt_pipeline --fresh https://youtube.com/watch?v=...
```

## 配置

所有常量与运行时配置集中在 `yt_pipeline/constants.py`。可通过环境变量覆盖运行时配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PIPELINE_DOWNLOAD_CONCURRENCY` | 4 | 并行下载 worker 数 |
| `PIPELINE_STATE_FILE` | progress.json | 断点续跑文件路径 |

## 测试

```bash
pytest tests/ -v
```

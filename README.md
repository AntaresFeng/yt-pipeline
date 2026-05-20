# yt-pipeline

视频批处理流水线 —— Python asyncio 实现：yt-dlp 下载、ffprobe 探测、策略决策（4K 超分/黑边填充）、ffmpeg 转码、优雅退出、断点续跑。

## 环境依赖

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 视频下载 | `pip install yt-dlp` |
| [ffmpeg](https://ffmpeg.org/) | 视频转码、封面处理 | 系统包管理器或官网下载 |
| [ffprobe](https://ffmpeg.org/) | 媒体流信息探测 | 随 ffmpeg 一同安装 |

程序启动时会自动检测以上依赖，缺失时会提示安装方法。

可通过 `config.py` 指定 ffmpeg/ffprobe 路径

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

所有常量与运行时配置集中在 `yt_pipeline/config.py`。可通过环境变量覆盖运行时配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `PIPELINE_DOWNLOAD_CONCURRENCY` | 4 | 并行下载 worker 数 |
| `PIPELINE_STATE_FILE` | progress.json | 断点续跑文件路径 |

## 测试

```bash
pytest tests/ -v
```

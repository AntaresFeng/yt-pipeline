# yt-pipeline

视频批处理流水线 —— Python asyncio 实现：yt-dlp 下载、ffprobe 探测、策略决策（4K 超分/黑边填充）、NVEncC/ffmpeg 转码、优雅退出、断点续跑。

## 环境依赖

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 视频下载 | `pip install yt-dlp` |
| [ffmpeg](https://ffmpeg.org/) | 封面处理；可选视频转码后端 | 系统包管理器或官网下载 |
| [ffprobe](https://ffmpeg.org/) | 媒体流信息探测 | 随 ffmpeg 一同安装 |
| [NVEncC](https://github.com/rigaya/NVEnc) | 默认视频转码后端 | 下载 NVEnc release，并配置路径或加入 PATH |

程序启动时会自动检测以上依赖，缺失时会提示安装方法。

默认视频转码后端是 `nvencc`。如果 NVEncC 不在 PATH，可设置：

```powershell
$env:PIPELINE_NVENCC_PATH = "E:\Software\NegativeEncoder\Libs\NVEncC64.exe"
```

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
| `PIPELINE_DOWNLOAD_CONCURRENCY` | `2` | 并行下载 worker 数 |
| `PIPELINE_STATE_FILE` | `progress.json` | 断点续跑文件路径 |
| `PIPELINE_TRANSCODE_BACKEND` | `nvencc` | 视频转码后端，支持 `nvencc` / `ffmpeg` |
| `PIPELINE_NVENCC_PATH` | 空 | NVEncC 可执行文件路径 |
| `PIPELINE_FFMPEG_PATH` | 空 | ffmpeg 可执行文件路径 |
| `PIPELINE_FFPROBE_PATH` | 空 | ffprobe 可执行文件路径 |

## 测试

```bash
pytest tests/ -v
```

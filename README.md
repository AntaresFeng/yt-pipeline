# yt-pipeline

视频批处理流水线 —— Python asyncio 实现：yt-dlp 下载、ffprobe 探测、策略决策（4K 超分/黑边填充）、ffmpeg（NVENC/libsvtav1）转码、优雅退出、断点续跑。

## 环境依赖

| 工具 | 用途 | 安装方式 |
|------|------|----------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 视频下载 | `pip install yt-dlp` |
| [ffmpeg](https://ffmpeg.org/) | 封面处理；视频转码（需含 NVENC 支持） | 系统包管理器或官网下载 |
| [ffprobe](https://ffmpeg.org/) | 媒体流信息探测 | 随 ffmpeg 一同安装 |

程序启动时会自动检测以上依赖，缺失时会提示安装方法。

默认编码器是 `nvenc`（HEVC/NVENC）：ffmpeg 用 NVDEC 硬解 + CPU Lanczos 超分 + `hevc_nvenc` 编码。若 ffmpeg 不在 PATH，可设置：

```powershell
$env:PIPELINE_FFMPEG_PATH = "E:\GreenSoftware\ffmpeg\bin\ffmpeg.exe"
```

没有 NVIDIA 显卡时，切换到软件编码器：

```powershell
$env:PIPELINE_ENCODER = "svtav1"   # libsvtav1，CPU 编码
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
| `PIPELINE_ENCODER` | `nvenc` | 视频编码器，支持 `nvenc` / `svtav1` |
| `PIPELINE_NVENC_HW_DECODE` | `1` | 是否用 NVDEC 硬解（`0` 关闭，全部软解） |
| `PIPELINE_FFMPEG_PATH` | 空 | ffmpeg 可执行文件路径 |
| `PIPELINE_FFPROBE_PATH` | 空 | ffprobe 可执行文件路径 |

## 测试

```bash
pytest tests/ -v
```

"""视频处理业务常量与运行时配置。"""

import os
from pathlib import Path

# ---- 运行时配置（可通过环境变量覆盖）----
DOWNLOAD_CONCURRENCY: int = int(os.environ.get("PIPELINE_DOWNLOAD_CONCURRENCY", "4"))
STATE_FILE: Path = Path(os.environ.get("PIPELINE_STATE_FILE", "progress.json"))

# ---- 处理策略 ----
STRATEGY_SKIP = "skip"
STRATEGY_UPSCALE_4K = "upscale_4k"
STRATEGY_PAD_1600 = "pad_1600"

# ---- 视频处理阈值 ----
MIN_SHORT_EDGE = 1080
MAX_SHORT_EDGE = 1600
RATIO_THRESHOLD = 2.0

# ---- 输出尺寸 ----
TARGET_4K_WIDTH = 3840
TARGET_4K_HEIGHT = 2160
TARGET_PAD_HEIGHT = 1600
TARGET_ASPECT_RATIO = 16 / 9

# ---- 封面处理 ----
THUMBNAIL_MIN_HEIGHT = 720

# ---- 编码参数 ----
FFMPEG_CRF = 18
FFMPEG_PRESET = "slow"
FFMPEG_AUDIO_BITRATE = "192k"

# ---- 下载 ----
MAX_TITLE_LENGTH = 180
VIDEO_EXTS: set[str] = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv", ".avi"}
IMAGE_EXTS: set[str] = {".png", ".jpg", ".jpeg", ".webp"}

# ---- 外部工具路径 ----
FFMPEG_PATH: str | None = None
FFPROBE_PATH: str | None = None

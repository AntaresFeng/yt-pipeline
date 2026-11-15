"""视频处理业务常量与运行时配置。"""

import os
from pathlib import Path

# ---- 运行时配置（可通过环境变量覆盖）----
DOWNLOAD_CONCURRENCY: int = int(os.environ.get("PIPELINE_DOWNLOAD_CONCURRENCY", "2"))
OUTPUT_DIR: Path = Path(os.environ.get("PIPELINE_OUTPUT_DIR", "."))
STATE_FILE: Path = Path(
    os.environ.get("PIPELINE_STATE_FILE", str(OUTPUT_DIR / "progress.json"))
)

# ---- 外部工具路径 ----
FFMPEG_PATH: str | None = os.environ.get("PIPELINE_FFMPEG_PATH") or None
FFPROBE_PATH: str | None = os.environ.get("PIPELINE_FFPROBE_PATH") or None
SKIP_CHECK_DEPENDENCIES: bool = True

# ---- 转码编码器 ----
ENCODER_NVENC: str = "nvenc"  # hevc_nvenc：GPU 编码（NVDEC 硬解 + CPU Lanczos）
ENCODER_SVTAV1: str = "svtav1"  # libsvtav1：CPU 编码
ENCODERS: frozenset[str] = frozenset({ENCODER_NVENC, ENCODER_SVTAV1})
TRANSCODE_ENCODER: str = os.environ.get("PIPELINE_ENCODER", ENCODER_NVENC)

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

# ---- 编码参数：SVT-AV1（libsvtav1）----
FFMPEG_PRESET: int = 6       # SVT-AV1 preset，-2~13；6 = 平衡档（VOD 最佳点）
FFMPEG_CRF: int = 29         # SVT-AV1 CRF，0~63；29 = 平衡档
FFMPEG_GOP: int = 300        # GOP，10×帧率且 ≤300；300 = YouTube 通用安全上限
FFMPEG_SVTAV1_PARAMS: str = "tune=0"  # svtav1-params，tune=0 = VQ 视觉质量

# ---- 编码参数：NVENC（hevc_nvenc）----
NVENC_PRESET: str = "p4"
NVENC_TUNE: str = "hq"
NVENC_RC: str = "vbr"
NVENC_CQ: int = 24
NVENC_SPATIAL_AQ: int = 1  # 仅 Spatial AQ；与 Temporal AQ 不同时开启
NVENC_PROFILE: str = "main"
NVENC_AUDIO_BITRATE: int = 256  # kbps
NVENC_HW_DECODE: bool = os.environ.get("PIPELINE_NVENC_HW_DECODE", "1") != "0"
NVDEC_CODECS: frozenset[str] = frozenset(
    {"h264", "hevc", "vp9", "vp8", "vc1", "mpeg2video"}
)

# ---- 下载 ----
VIDEO_EXTS: set[str] = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv", ".avi"}
IMAGE_EXTS: set[str] = {".png", ".jpg", ".jpeg", ".webp"}
YDL_OPTS = {
    "retries": 10,  # 重试 10 次，和 CLI 默认一致
    "fragment_retries": 10,
    "noplaylist": True,
    "writethumbnail": True,
    "writesubtitles": True,
    "subtitlesformat": "srt",
    "paths": {"home": str(OUTPUT_DIR)},
    "postprocessors": [
        {
            "key": "FFmpegThumbnailsConvertor",
            "format": "png",
            "when": "before_dl",
        }
    ],
}

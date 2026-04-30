"""策略引擎：视频处理决策与 ffmpeg 命令构建。"""

from pathlib import Path

from yt_pipeline.constants import (
    MAX_SHORT_EDGE,
    MIN_SHORT_EDGE,
    RATIO_THRESHOLD,
    STRATEGY_PAD_1600,
    STRATEGY_SKIP,
    STRATEGY_UPSCALE_4K,
    TARGET_4K_HEIGHT,
    TARGET_4K_WIDTH,
    TARGET_PAD_HEIGHT,
    FFMPEG_CRF,
    FFMPEG_PRESET,
    FFMPEG_AUDIO_BITRATE,
)
from yt_pipeline.models import VideoSpec


def decide_video_strategy(spec: VideoSpec) -> tuple[str, str | None]:
    """根据视频尺寸决定处理策略。

    Returns:
        (strategy, reason) — strategy 为 "skip" | "upscale_4k" | "pad_1600"，
        非 skip 时 reason 为 None。
    """
    if not spec.is_horizontal:
        return STRATEGY_SKIP, "竖屏视频，按规则跳过"

    short_edge = spec.short_edge
    if short_edge <= MIN_SHORT_EDGE:
        return STRATEGY_SKIP, f"短边 {short_edge} <= {MIN_SHORT_EDGE}，按规则跳过"
    if short_edge >= MAX_SHORT_EDGE:
        return STRATEGY_SKIP, f"短边 {short_edge} >= {MAX_SHORT_EDGE}，按规则跳过"

    if spec.ratio < RATIO_THRESHOLD:
        return STRATEGY_UPSCALE_4K, None
    return STRATEGY_PAD_1600, None


def build_ffmpeg_command(video_path: Path, strategy: str) -> tuple[list[str], Path]:
    """根据策略构建 ffmpeg 命令和输出路径。

    Returns:
        (command, output_path)
    """
    if strategy == STRATEGY_UPSCALE_4K:
        output = _next_available_path(
            video_path.with_name(f"{video_path.stem}_processed_4k.mp4")
        )
        vf = f"scale={TARGET_4K_WIDTH}:{TARGET_4K_HEIGHT}:flags=lanczos"
    elif strategy == STRATEGY_PAD_1600:
        output = _next_available_path(
            video_path.with_name(f"{video_path.stem}_processed_pad1600.mp4")
        )
        vf = (
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            f"pad=iw:{TARGET_PAD_HEIGHT}:0:({TARGET_PAD_HEIGHT}-ih)/2:black"
        )
    else:
        raise ValueError(f"未知策略: {strategy}")

    # fmt: off
    command = [
        "ffmpeg", "-hide_banner", "-n",
        "-i", str(video_path),
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-crf", str(FFMPEG_CRF),
        "-preset", FFMPEG_PRESET,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", FFMPEG_AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(output),
    ]
    # fmt: on

    return command, output


def _next_available_path(path: Path) -> Path:
    """若路径已存在，追加时间戳。"""
    if not path.exists():
        return path
    import time
    ts = int(time.time() * 1000)
    return path.with_name(f"{path.stem}_{ts}{path.suffix}")

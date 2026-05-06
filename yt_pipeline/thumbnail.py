"""封面查找与处理。"""

from __future__ import annotations

import logging
from pathlib import Path

from yt_pipeline.constants import IMAGE_EXTS, TARGET_ASPECT_RATIO, THUMBNAIL_MIN_HEIGHT
from yt_pipeline.process import run_command

logger = logging.getLogger("pipeline.thumbnail")


async def process_thumbnail(thumbnail_path: Path) -> list[Path]:
    """如果封面高度 < THUMBNAIL_MIN_HEIGHT，裁剪 16:9 后 2x 超分。

    返回生成的文件列表。跳过时返回空列表。
    """
    from yt_pipeline.process import probe_dimensions

    spec = await probe_dimensions(thumbnail_path)
    if spec.height >= THUMBNAIL_MIN_HEIGHT:
        logger.info(
            "封面高度 %dpx >= %d，跳过封面处理。",
            spec.height,
            THUMBNAIL_MIN_HEIGHT,
        )
        return []

    # Python 端计算 16:9 裁剪尺寸，避免 ffmpeg if() 表达式在 Windows 下解析异常
    if spec.width / spec.height >= TARGET_ASPECT_RATIO:
        crop_w = spec.height * 16 // 9
        crop_h = spec.height
    else:
        crop_w = spec.width
        crop_h = spec.width * 9 // 16

    cropped = thumbnail_path.with_name(
        f"{thumbnail_path.stem}_169{thumbnail_path.suffix}"
    )
    upscaled = thumbnail_path.with_name(
        f"{thumbnail_path.stem}_169_2x{thumbnail_path.suffix}"
    )

    # fmt: off
    rc, _, stderr = await run_command([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(thumbnail_path),
        "-vf", f"crop={crop_w}:{crop_h}",
        str(cropped),
    ])
    # fmt: on
    if rc != 0:
        raise RuntimeError(f"封面裁剪失败: {stderr[:200]}")

    # fmt: off
    rc2, _, stderr2 = await run_command([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(cropped),
        "-vf", "scale=iw*2:ih*2:flags=lanczos",
        str(upscaled),
    ])
    # fmt: on
    if rc2 != 0:
        raise RuntimeError(f"封面超分失败: {stderr2[:200]}")

    cropped.unlink(missing_ok=True)
    logger.info("已生成封面文件: %s", upscaled.name)
    return [upscaled]

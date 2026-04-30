"""异步 ffprobe 尺寸探测。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from yt_pipeline.models import ImageSpec, VideoSpec
from yt_pipeline.process import run_command

logger = logging.getLogger("pipeline.probe")


async def probe_dimensions(file_path: Path) -> ImageSpec:
    """ffprobe 获取图片/视频尺寸。

    Raises:
        RuntimeError: 无法读取尺寸
    """
    # 先尝试 stream 级探测
    rc, stdout, stderr = await run_command([
        "ffprobe", "-hide_banner",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(file_path),
    ])

    if rc != 0:
        raise RuntimeError(f"ffprobe 失败: {stderr[:200]}")

    data = json.loads(stdout)
    streams = data.get("streams") or []

    if streams:
        stream = streams[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    else:
        # 图片无视频 stream，fallback 到 format 级探测
        rc2, stdout2, stderr2 = await run_command([
            "ffprobe", "-hide_banner",
            "-v", "error",
            "-show_entries", "format=width,height",
            "-of", "json",
            str(file_path),
        ])
        if rc2 != 0:
            raise RuntimeError(f"ffprobe format 探测失败: {stderr2[:200]}")
        data2 = json.loads(stdout2)
        fmt = data2.get("format") or {}
        width = int(fmt.get("width") or 0)
        height = int(fmt.get("height") or 0)

    if width <= 0 or height <= 0:
        raise RuntimeError(f"无法读取尺寸: {file_path}")
    return ImageSpec(width=width, height=height)


async def ffprobe_dimensions(file_path: Path) -> VideoSpec:
    """ffprobe 获取视频尺寸，返回 VideoSpec。"""
    spec = await probe_dimensions(file_path)
    return VideoSpec(width=spec.width, height=spec.height)

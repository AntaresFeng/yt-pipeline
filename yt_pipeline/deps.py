"""外部依赖检测：yt-dlp / ffmpeg / ffprobe。"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Sequence

from yt_pipeline import config

logger = logging.getLogger("pipeline.deps")


class DependencyError(Exception):
    """外部依赖缺失或不可用。"""

    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(message)


def _resolve_tool_path(
    name: str,
    env_path: str | None,
    *,
    candidates: Sequence[str] | None = None,
) -> str:
    """解析工具路径：优先使用用户指定路径，否则从 PATH 查找。"""
    if env_path:
        return env_path
    for candidate in candidates or (name,):
        found = shutil.which(candidate)
        if found is not None:
            return found

    hint = f"请安装后确保在 PATH 中，或设置环境变量 PIPELINE_{name.upper()}_PATH"
    raise DependencyError(name, f"未找到 {name}，{hint}")


def _verify_executable(path: str, name: str, *, version_arg: str = "-version") -> None:
    """验证工具可执行性。"""
    try:
        result = subprocess.run(
            [path, version_arg],
            capture_output=True,
            check=False,
            timeout=10,
        )
    except FileNotFoundError:
        raise DependencyError(name, f"{name} 不可执行: {path}，请检查文件路径是否正确")
    except OSError as e:
        raise DependencyError(name, f"{name} 执行失败: {e}")

    if result.returncode != 0:
        raise DependencyError(
            name,
            f"{name} 不可执行: {path}，请检查文件权限或路径是否正确",
        )


def resolve_dependency_paths() -> None:
    """Resolve configured tool paths without launching external processes."""
    config.FFMPEG_PATH = _resolve_tool_path("ffmpeg", config.FFMPEG_PATH)
    logger.debug("Resolved ffmpeg path: %s", config.FFMPEG_PATH)

    config.FFPROBE_PATH = _resolve_tool_path("ffprobe", config.FFPROBE_PATH)
    logger.debug("Resolved ffprobe path: %s", config.FFPROBE_PATH)

    encoder = config.TRANSCODE_ENCODER.lower()
    if encoder not in config.ENCODERS:
        raise DependencyError(
            "encoder",
            f"未知编码器: {config.TRANSCODE_ENCODER}",
        )


def check_dependencies() -> None:
    """检测全部外部依赖。缺失时抛出 DependencyError。"""
    # yt-dlp
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise DependencyError("yt-dlp", "未找到 yt-dlp，请安装: pip install yt-dlp")
    logger.debug("OK: yt-dlp")

    resolve_dependency_paths()

    _verify_executable(config.FFMPEG_PATH, "ffmpeg")
    logger.debug("OK: ffmpeg (%s)", config.FFMPEG_PATH)

    _verify_executable(config.FFPROBE_PATH, "ffprobe")
    logger.debug("OK: ffprobe (%s)", config.FFPROBE_PATH)

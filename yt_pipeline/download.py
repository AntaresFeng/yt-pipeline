"""异步 yt-dlp 下载 + credits 生成。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from yt_pipeline.constants import MAX_TITLE_LENGTH, VIDEO_EXTS
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task

logger = logging.getLogger("pipeline.download")


def _do_download(url: str) -> dict:
    """同步下载（在线程池中执行）。"""
    import yt_dlp

    ydl_opts = {
        "writethumbnail": True,
        "writesubtitles": True,
        "subtitlesformat": "srt",
        "outtmpl": f"%(title).{MAX_TITLE_LENGTH}B [%(id)s].%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "png",
                "when": "before_dl",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info and info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                raise RuntimeError("链接是播放列表但未获取到可下载视频。")
            info = entries[0]
        return info


def resolve_video_path(info: dict, video_id: str) -> Path | None:
    """从 yt-dlp info dict 定位下载的视频文件路径。"""
    # 优先从 requested_downloads 中获取
    requested = info.get("requested_downloads") or []
    for item in requested:
        fp = item.get("filepath")
        if fp:
            path = Path(fp)
            if path.exists() and path.suffix.lower() in VIDEO_EXTS:
                return path

    # 回退到 _filename
    guessed = info.get("_filename")
    if guessed:
        path = Path(guessed)
        if path.exists() and path.suffix.lower() in VIDEO_EXTS:
            return path

    # 最后按 video_id glob
    candidates = [
        p
        for p in Path.cwd().glob(f"*{video_id}*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS
    ]
    return candidates[0] if candidates else None


def generate_credits(info: dict, source_url: str, video_path: Path) -> Path:
    """从 yt-dlp info dict 生成来源文案 .description 文件。"""
    channel = info.get("channel") or "未知"
    title = info.get("title") or "未知"
    description = info.get("description") or ""

    out_path = video_path.with_suffix(".description")
    text = (
        f"{source_url}\n"
        f"原作者：{channel}\n"
        f"原标题：{title}\n"
        "转载经原作者允许\n"
        "请各位观众在条件允许的情况下访问视频原始发布地址以支持原作者\n\n\n"
        f"{description}"
    )
    out_path.write_text(text, encoding="utf-8")
    return out_path


async def download_video(task: Task, shutdown: ShutdownManager) -> None:
    """异步下载视频，填充 task 的 video_id/video_path/thumbnail_path/credits_path。

    yt-dlp 阻塞调用通过 asyncio.to_thread 放入线程池。
    """
    if shutdown.is_set:
        raise asyncio.CancelledError("Shutdown before download")

    logger.info("[%s] Downloading...", task.url)
    info = await asyncio.to_thread(_do_download, task.url)

    if shutdown.is_set:
        raise asyncio.CancelledError("Shutdown after download")

    video_id = str(info.get("id") or "")
    video_path = resolve_video_path(info, video_id)
    if video_path is None:
        raise RuntimeError("下载完成但未定位到视频文件。")

    task.video_id = video_id
    task.title = info.get("title")
    task.video_path = str(video_path)

    # 封面：yt-dlp 已自动转换为 png（FFmpegThumbnailsConvertor）
    thumbnail_exts = {".png", ".jpg", ".jpeg", ".webp"}
    for ext in thumbnail_exts:
        candidate = video_path.with_suffix(ext)
        if candidate.exists():
            task.thumbnail_path = str(candidate)
            break

    # 生成来源文案
    credits_path = generate_credits(info, task.url, video_path)
    task.credits_path = str(credits_path)

    logger.info("[%s] Download done", task.url)

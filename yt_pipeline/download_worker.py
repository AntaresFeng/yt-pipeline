"""下载 worker：yt-dlp 下载 + credits 生成 + 并发调度。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from yt_pipeline.constants import MAX_TITLE_LENGTH, VIDEO_EXTS, IMAGE_EXTS
from yt_pipeline.model import Task, States
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.utils import handle_worker_error

logger = logging.getLogger("pipeline.download_worker")


def find_media_file(video_id: str, exts: set[str]) -> Path | None:
    """按 video_id glob 查找媒体文件，按扩展名过滤。"""
    candidates = [
        p
        for p in Path.cwd().glob(f"*{video_id}*")
        if p.is_file() and p.suffix.lower() in exts
    ]
    return candidates[0] if candidates else None


def find_thumbnail(video_path: Path, video_id: str) -> Path | None:
    """根据 video_path 同名前缀 + video_id glob 查找封面文件。"""
    from yt_pipeline.constants import IMAGE_EXTS

    candidates: list[Path] = []

    # 同视频文件名、不同图片扩展名
    for ext in IMAGE_EXTS:
        p = video_path.with_suffix(ext)
        if p.exists():
            candidates.append(p)

    # 按 video_id glob
    if video_id:
        found = find_media_file(video_id, IMAGE_EXTS)
        if found:
            candidates.append(found)

    if not candidates:
        return None

    uniq = list({c.resolve(): c for c in candidates}.values())
    uniq.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return uniq[0]


# ── 同步辅助函数（在线程池中执行）──────────────────────────────

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
    requested = info.get("requested_downloads") or []
    for item in requested:
        fp = item.get("filepath")
        if fp:
            path = Path(fp)
            if path.exists() and path.suffix.lower() in VIDEO_EXTS:
                return path

    guessed = info.get("_filename")
    if guessed:
        path = Path(guessed)
        if path.exists() and path.suffix.lower() in VIDEO_EXTS:
            return path

    return find_media_file(video_id, VIDEO_EXTS)


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


# ── 异步入口 ──────────────────────────────────────────────────

async def download_video(task: Task, shutdown: "ShutdownManager") -> None:
    """异步下载视频，填充 task 的 video_id/video_path/thumbnail_path/credits_path。"""
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

    for ext in IMAGE_EXTS:
        candidate = video_path.with_suffix(ext)
        if candidate.exists():
            task.thumbnail_path = str(candidate)
            break

    credits_path = generate_credits(info, task.url, video_path)
    task.credits_path = str(credits_path)

    logger.info("[%s] Download done", task.url)


# ── Worker 协程 ────────────────────────────────────────────────

async def download_worker(
    sem: asyncio.Semaphore,
    pending_queue: asyncio.Queue[Task],
    assessment_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: "ShutdownManager",
    state_file: Path,
) -> None:
    """并发下载 worker：从 pending_queue 取任务，完成后放入 assessment_queue。"""
    while True:
        if shutdown.is_set:
            break

        if not any(t.state == States.PENDING for t in tasks):
            break

        try:
            task = await asyncio.wait_for(pending_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != States.PENDING:
            pending_queue.task_done()
            continue

        async with sem:
            if shutdown.is_set:
                pending_queue.task_done()
                break

            task.state = States.DOWNLOADING
            save_all_progress(tasks, state_file)
            try:
                await download_video(task, shutdown)

                if not task.thumbnail_path and task.video_path and task.video_id:
                    found = await asyncio.to_thread(
                        find_thumbnail, Path(task.video_path), task.video_id
                    )
                    if found:
                        task.thumbnail_path = str(found)

                task.state = States.DOWNLOADED
                save_all_progress(tasks, state_file)
                await assessment_queue.put(task)
            except asyncio.CancelledError:
                logger.warning("[%s] Download cancelled by shutdown", task.url)
                raise
            except Exception as e:
                handle_worker_error(task, e, tasks, state_file)
            finally:
                pending_queue.task_done()

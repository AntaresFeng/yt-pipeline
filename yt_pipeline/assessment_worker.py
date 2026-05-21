"""Assessment worker：串行探测封面/视频尺寸并决策是否需要转码。"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yt_pipeline.config as C
from yt_pipeline.model import Task, States, StreamSpec
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.utils import handle_worker_error

if TYPE_CHECKING:
    from yt_pipeline.pipeline import ShutdownManager

logger = logging.getLogger("pipeline.assessment_worker")


async def run_command(cmd: list[str]) -> tuple[int, str, str]:
    """执行短命令，返回 (returncode, stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode() if stdout else "",
        stderr.decode() if stderr else "",
    )


async def probe(file_path: Path) -> StreamSpec:
    """ffprobe 获取媒体流尺寸。"""
    # fmt: off
    rc, stdout, stderr = await run_command([
        C.FFPROBE_PATH, "-hide_banner",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(file_path),
    ])
    # fmt: on

    if rc != 0:
        raise RuntimeError(f"ffprobe 失败: {stderr[:200]}")

    data = json.loads(stdout)
    streams = data.get("streams") or []

    if streams:
        stream = streams[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    else:
        # fmt: off
        rc2, stdout2, stderr2 = await run_command([
            C.FFPROBE_PATH, "-hide_banner",
            "-v", "error",
            "-show_entries", "format=width,height",
            "-of", "json",
            str(file_path),
        ])
        # fmt: on
        if rc2 != 0:
            raise RuntimeError(f"ffprobe format 探测失败: {stderr2[:200]}")
        data2 = json.loads(stdout2)
        fmt = data2.get("format") or {}
        width = int(fmt.get("width") or 0)
        height = int(fmt.get("height") or 0)

    if width <= 0 or height <= 0:
        raise RuntimeError(f"无法读取尺寸: {file_path}")
    return StreamSpec(width=width, height=height)


async def process_thumbnail(thumbnail_path: Path) -> None:
    """如果封面高度 < THUMBNAIL_MIN_HEIGHT，裁剪 16:9 后 2x 超分。"""
    spec = await probe(thumbnail_path)
    if spec.height >= C.THUMBNAIL_MIN_HEIGHT:
        logger.info(
            "封面高度 %dpx >= %d，跳过封面处理。",
            spec.height,
            C.THUMBNAIL_MIN_HEIGHT,
        )
        return

    # Python 端计算 16:9 裁剪尺寸，避免 ffmpeg if() 表达式在 Windows 下解析异常
    if spec.width / spec.height >= C.TARGET_ASPECT_RATIO:
        crop_w = spec.height * 16 // 9
        crop_h = spec.height
    else:
        crop_w = spec.width
        crop_h = spec.width * 9 // 16

    upscaled = thumbnail_path.with_name(
        f"{thumbnail_path.stem}_169_2x{thumbnail_path.suffix}"
    )

    # fmt: off
    rc, _, stderr = await run_command([
        C.FFMPEG_PATH, "-hide_banner", "-y",
        "-i", str(thumbnail_path),
        "-vf", f"crop={crop_w}:{crop_h},scale=iw*2:ih*2:flags=lanczos",
        "-frames:v", "1", "-update", "1",
        str(upscaled),
    ])
    # fmt: on
    if rc != 0:
        raise RuntimeError(f"封面处理失败: {stderr[:200]}")

    logger.info("已生成封面文件: %s", upscaled.name)


def decide_video_strategy(spec: StreamSpec) -> tuple[str, str | None]:
    """根据视频尺寸决定处理策略。

    Returns:
        (strategy, reason) — strategy 为 "skip" | "upscale_4k" | "pad_1600"，
        非 skip 时 reason 为 None。
    """
    if spec.width < spec.height:
        return C.STRATEGY_SKIP, "竖屏视频，按规则跳过"

    short_edge = spec.short_edge
    if short_edge <= C.MIN_SHORT_EDGE:
        return C.STRATEGY_SKIP, f"短边 {short_edge} <= {C.MIN_SHORT_EDGE}，按规则跳过"
    if short_edge >= C.MAX_SHORT_EDGE:
        return C.STRATEGY_SKIP, f"短边 {short_edge} >= {C.MAX_SHORT_EDGE}，按规则跳过"

    if spec.ratio < C.RATIO_THRESHOLD:
        return C.STRATEGY_UPSCALE_4K, None
    return C.STRATEGY_PAD_1600, None


def _processed_output(video_path: Path, strategy: str) -> Path:
    if strategy == C.STRATEGY_UPSCALE_4K:
        return video_path.with_name(f"{video_path.stem}_processed_4k.mp4")
    if strategy == C.STRATEGY_PAD_1600:
        return video_path.with_name(f"{video_path.stem}_processed_pad1600.mp4")
    raise ValueError(f"未知策略: {strategy}")


def _build_ffmpeg_command(video_path: Path, strategy: str) -> tuple[list[str], Path]:
    """根据策略构建 ffmpeg 命令和输出路径。"""
    output = _processed_output(video_path, strategy)
    if strategy == C.STRATEGY_UPSCALE_4K:
        vf = f"scale={C.TARGET_4K_WIDTH}:{C.TARGET_4K_HEIGHT}:flags=lanczos"
    else:
        vf = (
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            f"pad=iw:{C.TARGET_PAD_HEIGHT}:0:({C.TARGET_PAD_HEIGHT}-ih)/2:black"
        )

    # fmt: off
    command = [
        C.FFMPEG_PATH, "-hide_banner", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-crf", str(C.FFMPEG_CRF),
        "-preset", C.FFMPEG_PRESET,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", C.FFMPEG_AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(output),
    ]
    # fmt: on

    return command, output


def _even_floor(value: int) -> int:
    return value // 2 * 2


def _build_nvencc_command(
    video_path: Path,
    strategy: str,
    spec: StreamSpec,
) -> tuple[list[str], Path]:
    """根据策略构建 NVEncC 命令和输出路径。"""
    output = _processed_output(video_path, strategy)

    if strategy == C.STRATEGY_UPSCALE_4K:
        output_res = f"{C.TARGET_4K_WIDTH}x{C.TARGET_4K_HEIGHT}"
        pad_args: list[str] = []
    else:
        resize_w = _even_floor(spec.width)
        resize_h = _even_floor(spec.height)
        pad_total = C.TARGET_PAD_HEIGHT - resize_h
        if resize_w <= 0 or resize_h <= 0 or pad_total < 0:
            raise ValueError(
                f"无法为尺寸 {spec.width}x{spec.height} 构建 pad_1600 命令"
            )
        pad_top = pad_total // 2
        pad_bottom = pad_total - pad_top
        output_res = f"{resize_w}x{C.TARGET_PAD_HEIGHT}"
        pad_args = ["--vpp-pad", f"0,{pad_top},0,{pad_bottom}"]

    # fmt: off
    command = [
        C.NVENCC_PATH, "--avsw",
        "-i", str(video_path),
        "--codec", C.NVENCC_CODEC,
        "--qvbr", str(C.NVENCC_QVBR),
        "-u", C.NVENCC_PRESET,
        "--output-res", output_res,
        "--vpp-resize", C.NVENCC_RESIZE_ALGO,
        *pad_args,
        "--colorrange", "auto", "--colormatrix", "auto",
        "--colorprim", "auto", "--transfer", "auto", "--chromaloc", "auto",
        "--audio-codec", C.NVENCC_AUDIO_CODEC,
        "--audio-bitrate", str(C.NVENCC_AUDIO_BITRATE),
        "-f", "mp4",
        "-o", str(output),
    ]
    # fmt: on

    return command, output


def build_transcode_command(
    video_path: Path,
    strategy: str,
    spec: StreamSpec,
) -> tuple[list[str], Path]:
    """根据配置的转码后端构建命令和输出路径。"""
    backend = C.TRANSCODE_BACKEND.lower()
    if backend == C.BACKEND_FFMPEG:
        return _build_ffmpeg_command(video_path, strategy)
    if backend == C.BACKEND_NVENCC:
        return _build_nvencc_command(video_path, strategy, spec)
    raise ValueError(f"未知转码后端: {C.TRANSCODE_BACKEND}")


async def assessment_worker(
    assessment_queue: asyncio.Queue[Task],
    transcode_queue: asyncio.Queue[Task],
    tasks: list[Task],
    shutdown: ShutdownManager,
    state_file: Path,
) -> None:
    """串行 assessment worker：探测封面/视频尺寸并决策是否需要转码。"""
    while True:
        if shutdown.is_set:
            break

        try:
            task = await asyncio.wait_for(assessment_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != States.DOWNLOADED:
            assessment_queue.task_done()
            continue

        try:
            video_path = Path(task.video_path) if task.video_path else None
            if video_path is None:
                raise RuntimeError("video_path 未设置")

            task.state = States.ASSESSING
            if task.thumbnail_path:
                thumb_spec, video_spec = await asyncio.gather(
                    probe(Path(task.thumbnail_path)),
                    probe(video_path),
                )
            else:
                thumb_spec = None
                video_spec = await probe(video_path)

            if thumb_spec is not None and thumb_spec.height < C.THUMBNAIL_MIN_HEIGHT:
                try:
                    await process_thumbnail(Path(task.thumbnail_path))
                except Exception as e:
                    logger.warning("[%s] Cover processing skipped: %s", task.url, e)

            strategy, reason = decide_video_strategy(video_spec)

            if strategy == C.STRATEGY_SKIP:
                task.state = States.DONE
                save_all_progress(tasks, state_file)
                logger.info("[%s] Skipped: %s", task.url, reason)
            else:
                cmd, _ = build_transcode_command(video_path, strategy, video_spec)
                task.transcode_command = cmd
                task.state = States.PROCESSING_VIDEO
                save_all_progress(tasks, state_file)
                await transcode_queue.put(task)
        except asyncio.CancelledError:
            logger.warning("[%s] Assessment cancelled", task.url)
            raise
        except Exception as e:
            handle_worker_error(task, e, tasks, state_file)
        finally:
            assessment_queue.task_done()

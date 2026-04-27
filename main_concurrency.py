#!/usr/bin/env python3
"""
视频批量处理骨架 —— 异步并发版
- 下载并发 4（Semaphore）
- 转码串行（单 worker）
- 下载与转码重叠
- 优雅退出（转码时向 ffmpeg 发 q）
- 中断恢复
"""

import asyncio
import json
import logging
import signal
import subprocess
import sys
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ---------- 固定随机种子 ----------
random.seed(0)

# ---------- 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("pipeline")

# ---------- 持久化文件 ----------
STATE_FILE = Path("progress.json")

# ---------- 可配置参数 ----------
DOWNLOAD_CONCURRENCY = 4  # 下载并发数


# ---------- 任务状态模型 ----------
@dataclass
class Task:
    url: str
    state: str = "pending"  # pending, downloading, downloaded, probing_cover, processing_cover, probing_video, processing_video, done, failed
    error: Optional[str] = None


# ---------- 全局退出事件 ----------
shutdown_event = asyncio.Event()
_loop: Optional[asyncio.AbstractEventLoop] = None  # 保存 loop 引用，供信号线程调度


def handle_exit_signal(signum=None, frame=None):
    """SIGINT 回调 —— Windows 上可能从信号线程调用，必须线程安全"""
    logger.warning("Received Ctrl+C, requesting graceful shutdown...")
    if _loop is not None and _loop.is_running():
        _loop.call_soon_threadsafe(shutdown_event.set)


# ---------- 状态持久化 ----------
def load_progress():
    """从文件加载任务列表，重建队列所需的任务"""
    if not STATE_FILE.exists():
        logger.info("No saved state found.")
        return None

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        tasks = [Task(**t) for t in data["tasks"]]
        logger.info(f"Loaded {len(tasks)} tasks from saved state.")
        return tasks
    except Exception as e:
        logger.error(f"Failed to load progress: {e}")
        return None


def save_all_progress(tasks: list[Task]):
    """原子写入所有任务状态"""
    data = {
        "tasks": [{"url": t.url, "state": t.state, "error": t.error} for t in tasks]
    }
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


# ---------- Mock 操作 ----------
async def mock_download(task: Task):
    """模拟 yt-dlp 下载，支持中途退出"""
    logger.info(f"[{task.url}] Downloading...")
    try:
        # 用 wait_for 监听退出事件，实际上是模拟长时间 IO
        await asyncio.wait_for(shutdown_event.wait(), timeout=2.0)
        # 等到了退出事件
        raise asyncio.CancelledError("Shutdown during download")
    except asyncio.TimeoutError:
        pass  # 正常超时，下载完成
    logger.info(f"[{task.url}] Download done")


async def mock_probe(item: str) -> dict:
    """模拟探测封面/视频尺寸"""
    await asyncio.sleep(0.5)
    if item == "cover":
        choice = [{"width": 640, "height": 360}, {"width": 1280, "height": 720}]
        return choice[1]
    else:
        choice = [
            {"width": 2560, "height": 1440},
            {"width": 3840, "height": 2160},
        ]
        return choice[0]


async def mock_cover_process(task: Task):
    """模拟封面处理"""
    logger.info(f"[{task.url}] Processing cover...")
    await asyncio.sleep(1)
    logger.info(f"[{task.url}] Cover done")


async def mock_video_process(task: Task):
    """模拟 ffmpeg 转码，通过子进程实现可优雅退出。子进程放入独立进程组以隔离 Ctrl+C。"""
    logger.info(f"[{task.url}] Starting ffmpeg (mock)...")
    mock_script = "mock_script.py"

    # Windows: 子进程放入独立进程组，防止 Ctrl+C 波及
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        mock_script,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **popen_kwargs,
    )

    # 用 communicate() 保证管道回收
    process_task = asyncio.create_task(proc.communicate())
    shutdown_task = asyncio.create_task(shutdown_event.wait())
    done, pending = await asyncio.wait(
        [process_task, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    try:
        if shutdown_task in done:
            logger.info(f"[{task.url}] Sending 'q' to ffmpeg for graceful exit...")
            if proc.stdin and not proc.stdin.is_closing():
                try:
                    proc.stdin.write(b"q\n")
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()
            await process_task
            logger.info(f"[{task.url}] ffmpeg exited gracefully")
            raise asyncio.CancelledError("Shutdown during video processing")
        # 子进程自行退出 — 检查返回码以区分正常完成与被外部信号杀死
        stdout, stderr = await process_task
        if proc.returncode != 0:
            logger.warning(
                f"[{task.url}] ffmpeg exited with code {proc.returncode}, "
                f"likely killed by external signal (Ctrl+C on Windows hits whole process group). "
                f"stderr: {stderr.decode()[:200] if stderr else 'N/A'}"
            )
            shutdown_event.set()
            raise asyncio.CancelledError("ffmpeg killed by external signal")
        logger.info(f"[{task.url}] ffmpeg finished")
    finally:
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # 给 event loop 一个时间片以清理子进程 transport，避免 Event loop is closed
        await asyncio.sleep(0)


# ---------- 工作协程 ----------
async def download_worker(
    sem: asyncio.Semaphore,
    pending_queue: asyncio.Queue,
    transcode_queue: asyncio.Queue,
    tasks: list[Task],
):
    """并发下载 worker，从 pending_queue 取任务，完成后放入 transcode_queue"""
    while True:
        if shutdown_event.is_set():
            # 收到退出信号，不再取新任务
            break

        try:
            task = await asyncio.wait_for(pending_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        # 确认任务仍处于 pending 状态（有可能恢复时状态不一致）
        if task.state != "pending":
            pending_queue.task_done()
            continue

        async with sem:  # 控制并发数
            if shutdown_event.is_set():
                # 正在等待 sem 时可能收到了退出信号
                pending_queue.task_done()
                break

            task.state = "downloading"
            save_all_progress(tasks)
            try:
                await mock_download(task)
                # 下载成功
                task.state = "downloaded"
                save_all_progress(tasks)
                await transcode_queue.put(task)
            except asyncio.CancelledError:
                # 下载过程中收到退出信号，任务状态保留为 downloading（finally 会统一 task_done）
                logger.warning(f"[{task.url}] Download cancelled by shutdown")
                raise
            except Exception as e:
                task.state = "failed"
                task.error = str(e)
                save_all_progress(tasks)
                logger.error(f"[{task.url}] Download failed: {e}")
            finally:
                pending_queue.task_done()


async def transcode_worker(transcode_queue: asyncio.Queue, tasks: list[Task]):
    """串行转码 worker，从 transcode_queue 取任务逐个处理"""
    while True:
        if shutdown_event.is_set() and transcode_queue.empty():
            break

        try:
            task = await asyncio.wait_for(transcode_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue

        if task.state != "downloaded":
            transcode_queue.task_done()
            continue

        try:
            # 探测封面
            task.state = "probing_cover"
            save_all_progress(tasks)
            cover_info = await mock_probe("cover")
            need_cover = cover_info["height"] < 720

            if need_cover:
                task.state = "processing_cover"
                save_all_progress(tasks)
                await mock_cover_process(task)

            # 探测视频
            task.state = "probing_video"
            save_all_progress(tasks)
            video_info = await mock_probe("video")
            need_video = 1080 < video_info["height"] < 1600

            if need_video:
                task.state = "processing_video"
                save_all_progress(tasks)
                await mock_video_process(task)  # 内部会响应优雅退出

            task.state = "done"
            save_all_progress(tasks)
            logger.info(f"[{task.url}] Completed successfully")
        except asyncio.CancelledError:
            # 优雅退出时抛出的异常，任务保留当前状态，重新放入队列以便恢复
            logger.warning(
                f"[{task.url}] Transcode cancelled by shutdown, will be re-queued on resume"
            )
            # 将任务重新置为 downloaded 状态，下次恢复时会重新处理
            task.state = "downloaded"
            save_all_progress(tasks)
            transcode_queue.task_done()
            raise
        except Exception as e:
            task.state = "failed"
            task.error = str(e)
            save_all_progress(tasks)
            logger.error(f"[{task.url}] Processing failed: {e}")
        finally:
            transcode_queue.task_done()


# ---------- 启动 Pipeline ----------
async def run_pipeline(tasks: list[Task]):
    # 建立队列
    pending_queue = asyncio.Queue()
    transcode_queue = asyncio.Queue()

    # 填充 pending 队列
    for task in tasks:
        if task.state == "pending":
            await pending_queue.put(task)
        elif task.state == "downloaded":
            await transcode_queue.put(task)
        # done/failed 忽略

    # 下载并发信号量
    sem = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)

    # 启动并发下载 workers
    downloaders = [
        asyncio.create_task(download_worker(sem, pending_queue, transcode_queue, tasks))
        for _ in range(DOWNLOAD_CONCURRENCY)
    ]

    # 启动转码 worker
    transcoder = asyncio.create_task(transcode_worker(transcode_queue, tasks))

    try:
        # 等待所有下载完成
        await asyncio.gather(*downloaders)
    except asyncio.CancelledError:
        pass

    # 下载 worker 全部结束后，等待转码队列处理完
    if not shutdown_event.is_set():
        # 正常情况：等待转码完成
        await transcode_queue.join()
        transcoder.cancel()
        try:
            await transcoder
        except asyncio.CancelledError:
            pass
    else:
        # 退出情况：转码 worker 会自行退出，等待它
        await transcoder

    # 最终保存一次状态
    save_all_progress(tasks)

    # 检查是否全部完成
    if all(t.state in ("done", "failed") for t in tasks):
        logger.info("All tasks processed.")
        if STATE_FILE.exists():
            STATE_FILE.unlink()
    else:
        logger.info("Pipeline stopped, progress saved.")


# ---------- 入口 ----------
async def main():
    global _loop
    _loop = asyncio.get_running_loop()

    # 注册信号处理
    try:
        _loop.add_signal_handler(signal.SIGINT, handle_exit_signal)
    except NotImplementedError:
        # Windows: asyncio 不支持 SIGINT，用 stdlib signal（回调在信号线程，handle_exit_signal 通过 call_soon_threadsafe 回到事件循环）
        signal.signal(signal.SIGINT, handle_exit_signal)

    # 命令行参数：-y 自动恢复，-n 自动丢弃
    auto_yes = "-y" in sys.argv[1:]
    auto_no = "-n" in sys.argv[1:]

    saved_tasks = load_progress()
    if saved_tasks:
        if auto_yes:
            logger.info("Found previous progress. Auto-resuming (-y).")
        elif auto_no:
            logger.info("Found previous progress. Auto-discarding (-n).")
            STATE_FILE.unlink()
            saved_tasks = None
        else:
            answer = input("Found previous progress. Resume? [Y/n] ").strip().lower()
            if answer not in ("", "y", "yes"):
                logger.info("Starting fresh, discarding old state.")
                STATE_FILE.unlink()
                saved_tasks = None

    if saved_tasks:
        tasks = saved_tasks
        # 将处理中的状态重置为合适的早期状态
        for task in tasks:
            if task.state == "downloading":
                task.state = "pending"
            elif task.state in (
                "probing_cover",
                "processing_cover",
                "probing_video",
                "processing_video",
            ):
                task.state = "downloaded"
    else:
        tasks = []

    if not tasks:
        urls = [f"https://example.com/video{i}" for i in range(1, 6)]
        tasks = [Task(url) for url in urls]

    try:
        await run_pipeline(tasks)
    except asyncio.CancelledError:
        logger.info("Pipeline interrupted by user.")
    except KeyboardInterrupt:
        # 信号处理器未生效时的兜底（直接设，当前在事件循环线程）
        shutdown_event.set()
        logger.info("KeyboardInterrupt caught, waiting for cleanup...")
    finally:
        logger.info("Cleanup done.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBye.")

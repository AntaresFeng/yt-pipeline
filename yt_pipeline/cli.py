"""CLI 入口：argparse + 主流程。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import random

from yt_pipeline.config import PipelineConfig
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.task import Task, RESUME_RESET
from yt_pipeline.persistence import load_progress
from yt_pipeline.pipeline import run_pipeline

logger = logging.getLogger("pipeline")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stderr)],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yt-pipeline",
        description="Video batch-processing pipeline with graceful shutdown.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--resume",
        "-y",
        action="store_true",
        help="Auto-resume from saved progress.",
    )
    group.add_argument(
        "--fresh",
        "-n",
        action="store_true",
        help="Discard saved progress and start fresh.",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use shortened delays (for automated testing).",
    )
    parser.add_argument(
        "--urls",
        nargs="*",
        help="Video URLs to process (default: 5 example URLs).",
    )
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> None:
    random.seed(0)

    # 加载配置
    cfg = PipelineConfig.fast() if args.fast else PipelineConfig.from_env()

    # 注册优雅退出
    shutdown = ShutdownManager()
    shutdown.attach(asyncio.get_running_loop())

    # 加载/创建任务
    saved_tasks = load_progress(cfg.state_file)
    if saved_tasks:
        if args.resume:
            logger.info("Found previous progress. Auto-resuming (-y).")
        elif args.fresh:
            logger.info("Found previous progress. Auto-discarding (-n).")
            cfg.state_file.unlink()
            saved_tasks = None
        else:
            try:
                answer = (
                    input("Found previous progress. Resume? [Y/n] ").strip().lower()
                )
            except (EOFError, OSError):
                answer = "n"
            if answer not in ("", "y", "yes"):
                logger.info("Starting fresh, discarding old state.")
                cfg.state_file.unlink()
                saved_tasks = None

    if saved_tasks:
        tasks = saved_tasks
        for task in tasks:
            new_state = RESUME_RESET.get(task.state)
            if new_state is not None:
                task.state = new_state
    else:
        tasks = []

    if not tasks:
        urls = args.urls if args.urls else list(cfg.default_urls)
        tasks = [Task(url) for url in urls]

    try:
        await run_pipeline(tasks, shutdown, cfg)
    except asyncio.CancelledError:
        logger.info("Pipeline interrupted by user.")
    except KeyboardInterrupt:
        shutdown.event.set()
        logger.info("KeyboardInterrupt caught, waiting for cleanup...")
    finally:
        logger.info("Cleanup done.")


def main() -> None:
    _setup_logging()
    args = parse_args()
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nBye.")

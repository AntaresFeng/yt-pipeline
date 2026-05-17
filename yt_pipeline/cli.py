"""CLI 入口：argparse + 主流程。"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from yt_pipeline.config import STATE_FILE
from yt_pipeline.pipeline import ShutdownManager, run_pipeline
from yt_pipeline.model import Task, States, RESUME_RESET
from yt_pipeline.persistence import load_progress
from yt_pipeline.url_collector import collect_urls

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
        "--file",
        "-f",
        help="Read URLs from a text file (one per line).",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="Video URLs or YouTube IDs to process.",
    )
    return parser.parse_args(argv)


def prepare_tasks(args: argparse.Namespace) -> list[Task]:
    saved_tasks = load_progress(STATE_FILE)

    if not saved_tasks:
        return _new_tasks(args)

    if args.fresh:
        logger.info("Found previous progress. Auto-discarding (-n).")
        STATE_FILE.unlink()
        return _new_tasks(args)

    if not args.resume:
        try:
            answer = input("Found previous progress. Resume? [Y/n] ").strip().lower()
            should_resume = answer in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt, OSError):
            should_resume = False
        if not should_resume:
            logger.info("Starting fresh, discarding old state.")
            STATE_FILE.unlink()
            return _new_tasks(args)

    logger.info("Resuming from saved state.")

    done_tasks = [t for t in saved_tasks if t.state == States.DONE]
    if done_tasks:
        logger.info("Skipping %d completed tasks.", len(done_tasks))
    tasks = [t for t in saved_tasks if t.state != States.DONE]

    for task in tasks:
        new_state = RESUME_RESET.get(task.state)
        if new_state is not None:
            if task.state == States.FAILED:
                logger.info(
                    "Retrying failed task: %s (previous errors: %d)",
                    task.url,
                    len(task.errors),
                )
            task.state = new_state
    return tasks


def _new_tasks(args: argparse.Namespace) -> list[Task]:
    urls = collect_urls(args.urls, args.file)
    if not urls:
        logger.info("No URLs to process. Exiting.")
        return []
    return [Task(url) for url in urls]


async def _run_pipeline(tasks: list[Task]) -> None:
    shutdown = ShutdownManager()
    shutdown.attach(asyncio.get_running_loop())
    await run_pipeline(tasks, shutdown, STATE_FILE)


def main() -> None:
    _setup_logging()
    args = parse_args()
    try:
        tasks = prepare_tasks(args)
        if not tasks:
            return
        asyncio.run(_run_pipeline(tasks))
    except KeyboardInterrupt:
        print("\nBye.")

"""通用工具：错误处理。"""

from __future__ import annotations

import logging
from pathlib import Path

from yt_pipeline.model import States, Task
from yt_pipeline.persistence import save_all_progress

logger = logging.getLogger("pipeline.utils")


def handle_worker_error(
    task: Task, error: Exception, tasks: list[Task], state_file: Path
) -> None:
    """异常处理：标记 FAILED + 持久化 + 日志。"""
    task.state = States.FAILED
    task.errors.append(str(error))
    save_all_progress(tasks, state_file)
    logger.error("[%s] failed (attempt %d): %s", task.url, len(task.errors), error)

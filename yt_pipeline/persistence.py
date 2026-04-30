"""进度持久化：progress.json 的读写与原子替换。"""

import json
import logging
from pathlib import Path

from yt_pipeline.task import Task

logger = logging.getLogger("pipeline.persistence")

_SERIALIZED_FIELDS = [
    "url",
    "state",
    "error",
    "video_id",
    "video_path",
    "thumbnail_path",
    "credits_path",
    "strategy",
    "output_path",
]


def load_progress(state_file: Path) -> list[Task] | None:
    """从文件加载任务列表，不存在或损坏时返回 None。"""
    if not state_file.exists():
        logger.info("No saved state found.")
        return None

    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
        tasks = [Task(**{k: t.get(k) for k in _SERIALIZED_FIELDS}) for t in data["tasks"]]
        logger.info(f"Loaded {len(tasks)} tasks from saved state.")
        return tasks
    except Exception as e:
        logger.error(f"Failed to load progress: {e}")
        return None


def save_all_progress(tasks: list[Task], state_file: Path) -> None:
    """原子写入所有任务状态。"""
    data = {
        "tasks": [{k: getattr(t, k) for k in _SERIALIZED_FIELDS} for t in tasks]
    }
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(state_file)

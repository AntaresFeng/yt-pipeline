"""进度持久化：progress.json 的读写与原子替换。"""

import json
import logging
from dataclasses import asdict
from pathlib import Path

from yt_pipeline.model import Task

logger = logging.getLogger("pipeline.persistence")

def load_progress(state_file: Path) -> list[Task] | None:
    """从文件加载任务列表，不存在或损坏时返回 None。"""
    try:
        raw = state_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.info("No saved state found.")
        return None

    try:
        data = json.loads(raw)
        for t in data["tasks"]:
            # 旧格式兼容：error → errors
            if "errors" not in t:
                if "error" in t and t["error"] is not None:
                    t["errors"] = [t.pop("error")]
                else:
                    t["errors"] = []
            t.pop("error", None)
        tasks = [Task(**t) for t in data["tasks"]]
        logger.info(f"Loaded {len(tasks)} tasks from saved state.")
        return tasks
    except json.JSONDecodeError:
        logger.error("Failed to parse progress file: invalid JSON.")
        return None
    except Exception as e:
        logger.error(f"Failed to load progress: {e}")
        return None


def save_all_progress(tasks: list[Task], state_file: Path) -> None:
    """原子写入所有任务状态。"""
    data = {
        "tasks": [asdict(t) for t in tasks]
    }
    tmp = state_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(state_file)

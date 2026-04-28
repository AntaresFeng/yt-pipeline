"""任务状态模型。"""

from dataclasses import dataclass


@dataclass
class Task:
    url: str
    state: str = "pending"
    error: str | None = None


class States:
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    PROBING_COVER = "probing_cover"
    PROCESSING_COVER = "processing_cover"
    PROBING_VIDEO = "probing_video"
    PROCESSING_VIDEO = "processing_video"
    DONE = "done"
    FAILED = "failed"


# 终端状态：任务不再需要处理
TERMINAL_STATES = frozenset({States.DONE, States.FAILED})

# 中断恢复时的状态重置映射
RESUME_RESET: dict[str, str] = {
    States.DOWNLOADING: States.PENDING,
    States.PROBING_COVER: States.DOWNLOADED,
    States.PROCESSING_COVER: States.DOWNLOADED,
    States.PROBING_VIDEO: States.DOWNLOADED,
}

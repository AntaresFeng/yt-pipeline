"""任务状态模型与数据规格。"""

from dataclasses import dataclass, field


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


@dataclass
class Task:
    url: str
    state: str = States.PENDING
    errors: list[str] = field(default_factory=list)
    video_id: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    ffmpeg_command: list[str] | None = None


# 中断恢复时的状态重置映射
RESUME_RESET: dict[str, str] = {
    States.DOWNLOADING: States.PENDING,
    States.PROBING_COVER: States.DOWNLOADED,
    States.PROCESSING_COVER: States.DOWNLOADED,
    States.PROBING_VIDEO: States.DOWNLOADED,
    States.FAILED: States.PENDING,
}


@dataclass
class StreamSpec:
    width: int
    height: int

    @property
    def short_edge(self) -> int:
        return min(self.width, self.height)

    @property
    def long_edge(self) -> int:
        return max(self.width, self.height)

    @property
    def ratio(self) -> float:
        return self.long_edge / self.short_edge

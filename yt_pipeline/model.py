"""任务状态模型与数据规格。"""

from dataclasses import dataclass


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
    error: str | None = None
    # 下载阶段填充
    video_id: str | None = None
    title: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    credits_path: str | None = None
    # assessment 阶段填充
    strategy: str | None = None
    output_path: str | None = None
    ffmpeg_command: list[str] | None = None


# 终端状态：任务不再需要处理
TERMINAL_STATES = frozenset({States.DONE, States.FAILED})

# 中断恢复时的状态重置映射
RESUME_RESET: dict[str, str] = {
    States.DOWNLOADING: States.PENDING,
    States.PROBING_COVER: States.DOWNLOADED,
    States.PROCESSING_COVER: States.DOWNLOADED,
    States.PROBING_VIDEO: States.DOWNLOADED,
}


@dataclass
class ImageSpec:
    width: int
    height: int

    @property
    def is_portrait(self) -> bool:
        return self.height > self.width

    @property
    def is_landscape(self) -> bool:
        return not self.is_portrait


@dataclass
class VideoSpec:
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

    @property
    def is_horizontal(self) -> bool:
        return self.width >= self.height

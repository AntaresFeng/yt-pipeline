"""数据模型：ImageSpec / VideoSpec。"""

from dataclasses import dataclass


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

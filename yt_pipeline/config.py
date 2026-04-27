"""集中化配置管理。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline 所有可配置参数。通过 from_env() 从环境变量加载，也可直接构造或覆盖。"""

    # ---- 并发 ----
    download_concurrency: int = 4

    # ---- 各阶段延时 (秒) ----
    download_delay: float = 2.0
    probe_delay: float = 0.5
    cover_process_delay: float = 1.0

    # ---- Mock ffmpeg 子进程 ----
    mock_ffmpeg_frames: int = 10
    mock_ffmpeg_frame_delay: float = 1.0
    mock_ffmpeg_cleanup_delay: float = 0.5

    # ---- 持久化 ----
    state_file: Path = field(default_factory=lambda: Path("progress.json"))

    # ---- 默认任务 URL ----
    default_urls: tuple[str, ...] = (
        "https://example.com/video1",
        "https://example.com/video2",
        "https://example.com/video3",
        "https://example.com/video4",
        "https://example.com/video5",
    )

    @classmethod
    def from_env(cls, **overrides) -> PipelineConfig:
        """从环境变量加载配置，**overrides 可精确覆盖任意字段。"""
        env = os.environ
        kwargs: dict = {
            "download_concurrency": int(env.get("PIPELINE_DOWNLOAD_CONCURRENCY", "4")),
            "download_delay": float(env.get("PIPELINE_DOWNLOAD_DELAY", "2.0")),
            "probe_delay": float(env.get("PIPELINE_PROBE_DELAY", "0.5")),
            "cover_process_delay": float(env.get("PIPELINE_COVER_DELAY", "1.0")),
            "mock_ffmpeg_frames": int(env.get("MOCK_FFMPEG_FRAMES", "10")),
            "mock_ffmpeg_frame_delay": float(env.get("MOCK_FFMPEG_FRAME_DELAY", "1.0")),
            "mock_ffmpeg_cleanup_delay": float(
                env.get("MOCK_FFMPEG_CLEANUP_DELAY", "0.5")
            ),
            "state_file": Path(env.get("PIPELINE_STATE_FILE", "progress.json")),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

    @classmethod
    def fast(cls) -> PipelineConfig:
        """快速模式预设：所有延时缩短，用于测试。"""
        return cls(
            download_delay=0.1,
            probe_delay=0.05,
            cover_process_delay=0.1,
            mock_ffmpeg_frames=3,
            mock_ffmpeg_frame_delay=0.05,
        )

    def to_env(self) -> dict[str, str]:
        """将配置序列化为环境变量 dict，用于传递给子进程。"""
        return {
            "PIPELINE_DOWNLOAD_CONCURRENCY": str(self.download_concurrency),
            "PIPELINE_DOWNLOAD_DELAY": str(self.download_delay),
            "PIPELINE_PROBE_DELAY": str(self.probe_delay),
            "PIPELINE_COVER_DELAY": str(self.cover_process_delay),
            "MOCK_FFMPEG_FRAMES": str(self.mock_ffmpeg_frames),
            "MOCK_FFMPEG_FRAME_DELAY": str(self.mock_ffmpeg_frame_delay),
            "MOCK_FFMPEG_CLEANUP_DELAY": str(self.mock_ffmpeg_cleanup_delay),
            "PIPELINE_STATE_FILE": str(self.state_file),
        }

"""集中化配置管理。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline 所有可配置参数。通过 from_env() 从环境变量加载。"""

    # ---- 并发 ----
    download_concurrency: int = 4

    # ---- 持久化 ----
    state_file: Path = field(default_factory=lambda: Path("progress.json"))

    # ---- 调试 ----
    dry_run: bool = False
    mock_transcode: bool = False  # 用 mock_ffmpeg.py 替代真实 ffmpeg

    @classmethod
    def from_env(cls, **overrides) -> PipelineConfig:
        """从环境变量加载配置，**overrides 可精确覆盖任意字段。"""
        env = os.environ
        kwargs: dict = {
            "download_concurrency": int(env.get("PIPELINE_DOWNLOAD_CONCURRENCY", "4")),
            "state_file": Path(env.get("PIPELINE_STATE_FILE", "progress.json")),
            "dry_run": env.get("PIPELINE_DRY_RUN", "").lower() in ("1", "true", "yes"),
            "mock_transcode": env.get("PIPELINE_MOCK_TRANSCODE", "").lower() in ("1", "true", "yes"),
        }
        kwargs.update(overrides)
        return cls(**kwargs)

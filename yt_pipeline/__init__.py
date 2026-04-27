"""Video batch-processing pipeline with graceful shutdown and interrupt-resume."""

from yt_pipeline.config import PipelineConfig
from yt_pipeline.task import Task, States, RESUME_RESET
from yt_pipeline.shutdown import ShutdownManager
from yt_pipeline.pipeline import run_pipeline

__all__ = [
    "PipelineConfig",
    "Task",
    "States",
    "RESUME_RESET",
    "ShutdownManager",
    "run_pipeline",
]

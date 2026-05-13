"""策略引擎测试：decide_video_strategy + build_ffmpeg_command。"""

from pathlib import Path

import pytest

from yt_pipeline.model import StreamSpec
from yt_pipeline.assessment_worker import decide_video_strategy, build_ffmpeg_command


STRATEGY_PARAMS = [
    # (width, height, expected_strategy, expected_reason_keyword)
    # 竖屏 → skip
    (1080, 1920, "skip", "竖屏"),
    # 短边 ≤ 1080 → skip（边界值）
    (1920, 1080, "skip", "1080"),
    # 短边 ≥ 1600 → skip（边界值）
    (2560, 1600, "skip", "1600"),
    # 1081–1599, ratio < 2.0 → upscale_4k
    (1920, 1081, "upscale_4k", None),
    (1920, 1599, "upscale_4k", None),
    # 1081–1599, ratio ≥ 2.0 → pad_1600
    (3840, 1081, "pad_1600", None),
]


@pytest.mark.parametrize(
    "width, height, expected_strategy, expected_reason",
    STRATEGY_PARAMS,
    ids=[
        "竖屏_skip",
        "短边=1080_skip",
        "短边=1600_skip",
        "短边=1081_ratio<2_upscale_4k",
        "短边=1599_ratio<2_upscale_4k",
        "短边=1081_ratio>=2_pad_1600",
    ],
)
def test_decide_strategy(width, height, expected_strategy, expected_reason):
    spec = StreamSpec(width=width, height=height)
    strategy, reason = decide_video_strategy(spec)
    assert strategy == expected_strategy
    if expected_reason is None:
        assert reason is None
    else:
        assert expected_reason in reason


class TestBuildFfmpegCommand:
    def test_upscale_4k(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, output = build_ffmpeg_command(video, "upscale_4k")
        assert "scale=3840:2160:flags=lanczos" in " ".join(cmd)
        assert output.name.endswith("_processed_4k.mp4")
        assert output != video

    def test_pad_1600(self, tmp_path: Path):
        video = tmp_path / "test.mkv"
        video.touch()
        cmd, output = build_ffmpeg_command(video, "pad_1600")
        assert "pad=iw:1600:0:" in " ".join(cmd)
        assert output.name.endswith("_processed_pad1600.mp4")
        assert output != video

    def test_unknown_strategy_raises(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        with pytest.raises(ValueError, match="未知策略"):
            build_ffmpeg_command(video, "unknown")

    def test_output_path_idempotent(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        _, out1 = build_ffmpeg_command(video, "upscale_4k")
        _, out2 = build_ffmpeg_command(video, "upscale_4k")
        assert out2 == out1

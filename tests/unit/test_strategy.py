"""策略引擎测试：decide_video_strategy + build_transcode_command。"""

from pathlib import Path

import pytest

import yt_pipeline.config as C
from yt_pipeline.model import StreamSpec
from yt_pipeline.assessment_worker import decide_video_strategy, build_transcode_command


STRATEGY_PARAMS = [
    # (width, height, expected_strategy, expected_reason_keyword)
    # 竖屏 → skip
    (1080, 1920, "skip", "竖屏"),
    # 短边 ≤ 1080 → skip（边界值）
    (1920, 1080, "skip", "1080"),
    # 短边 ≥ 1600 → skip（边界值）
    (2560, 1600, "skip", "1600"),
    # 1081–1599, ratio ≤ 2.0 → upscale_4k
    (2560, 1440, "upscale_4k", None),  # 2k 16:9 视频
    (2560, 1280, "upscale_4k", None),  # ratio = 2.0 边界
    # 1081–1599, ratio > 2.0 → pad_1600
    (3440, 1440, "pad_1600", None),  # 超宽
]


@pytest.fixture
def ffmpeg_backend(monkeypatch):
    """注入 ffmpeg/libsvtav1 后端常量，供 build_transcode_command 走 ffmpeg 分支。"""
    monkeypatch.setattr(C, "TRANSCODE_BACKEND", "ffmpeg")
    monkeypatch.setattr(C, "FFMPEG_PATH", "ffmpeg", raising=False)
    monkeypatch.setattr(C, "FFMPEG_PRESET", 6, raising=False)
    monkeypatch.setattr(C, "FFMPEG_CRF", 29, raising=False)
    monkeypatch.setattr(C, "FFMPEG_GOP", 300, raising=False)
    monkeypatch.setattr(C, "FFMPEG_SVTAV1_PARAMS", "tune=0", raising=False)


@pytest.mark.parametrize(
    "width, height, expected_strategy, expected_reason",
    STRATEGY_PARAMS,
    ids=[
        "竖屏_skip",
        "短边=1080_skip",
        "短边=1600_skip",
        "短边=1081_ratio<=2_upscale_4k",
        "短边=1081_ratio=2.0_upscale_4k",
        "短边=1081_ratio>2_pad_1600",
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


def _arg_after(cmd: list[str], name: str) -> str:
    return cmd[cmd.index(name) + 1]


class TestBuildTranscodeCommand:
    @pytest.fixture(autouse=True)
    def default_nvencc_config(self, monkeypatch):
        monkeypatch.setattr(C, "TRANSCODE_BACKEND", "nvencc", raising=False)
        monkeypatch.setattr(C, "FFMPEG_PATH", "ffmpeg", raising=False)
        monkeypatch.setattr(C, "NVENCC_PATH", "NVEncC64.exe", raising=False)
        monkeypatch.setattr(C, "NVENCC_CODEC", "hevc", raising=False)
        monkeypatch.setattr(C, "NVENCC_QVBR", 23, raising=False)
        monkeypatch.setattr(C, "NVENCC_PRESET", "quality", raising=False)
        monkeypatch.setattr(C, "NVENCC_RESIZE_ALGO", "spline36", raising=False)
        monkeypatch.setattr(C, "NVENCC_AUDIO_CODEC", "aac", raising=False)
        monkeypatch.setattr(C, "NVENCC_AUDIO_BITRATE", 192, raising=False)

    def test_nvencc_upscale_4k(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, output = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=1920, height=1081),
        )

        assert cmd[0] == "NVEncC64.exe"
        assert "--avsw" in cmd
        assert "--avhw" not in cmd
        assert _arg_after(cmd, "--output-res") == "3836x2160"
        assert _arg_after(cmd, "--vpp-resize") == "spline36"
        assert "--vpp-pad" not in cmd
        assert _arg_after(cmd, "--codec") == "hevc"
        assert "--cqp" not in cmd
        assert _arg_after(cmd, "--qvbr") == "23"
        assert _arg_after(cmd, "-u") == "quality"
        assert _arg_after(cmd, "--audio-codec") == "aac"
        assert _arg_after(cmd, "--audio-bitrate") == "192"
        assert _arg_after(cmd, "-f") == "mp4"
        assert _arg_after(cmd, "-o") == str(output)
        assert output.name.endswith("_processed_4k.mp4")
        assert output != video

    @pytest.mark.parametrize(
        "width, height, expected_res",
        [
            (2560, 1440, "3840x2160"),  # 恰好 16:9, 不变
            (1440, 1080, "2880x2160"),  # 4:3, 高度顶满
            (1920, 800, "3840x1600"),  # 2.4:1, 宽度顶满
        ],
        ids=["exact_16_9", "4_3", "2_4_1"],
    )
    def test_nvencc_upscale_4k_preserves_aspect_ratio(
        self, tmp_path: Path, width, height, expected_res
    ):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, _ = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=width, height=height),
        )
        assert _arg_after(cmd, "--output-res") == expected_res
        assert "--vpp-pad" not in cmd

    def test_nvencc_pad_1600(self, tmp_path: Path):
        video = tmp_path / "test.mkv"
        video.touch()
        cmd, output = build_transcode_command(
            video,
            "pad_1600",
            StreamSpec(width=3840, height=1081),
        )

        assert _arg_after(cmd, "--output-res") == "3840x1600"
        assert _arg_after(cmd, "--vpp-pad") == "0,260,0,260"
        assert _arg_after(cmd, "--vpp-resize") == "spline36"
        assert output.name.endswith("_processed_pad1600.mp4")
        assert output != video

    def test_ffmpeg_backend_upscale_4k_svtav1(
        self,
        tmp_path: Path,
        ffmpeg_backend,
    ):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, output = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=1920, height=1081),
        )

        assert cmd[0] == C.FFMPEG_PATH
        vf = _arg_after(cmd, "-vf")
        assert (
            "scale=3840:2160:flags=lanczos:force_original_aspect_ratio=decrease"
            in vf
        )
        assert "force_divisible_by=2" in vf
        assert _arg_after(cmd, "-c:v") == "libsvtav1"
        assert _arg_after(cmd, "-preset") == "6"
        assert _arg_after(cmd, "-crf") == "29"
        assert _arg_after(cmd, "-g") == "300"
        assert _arg_after(cmd, "-pix_fmt") == "yuv420p10le"
        assert _arg_after(cmd, "-svtav1-params") == "tune=0"
        assert _arg_after(cmd, "-c:a") == "copy"
        assert "-b:a" not in cmd
        assert "-movflags" not in cmd
        assert output.name.endswith("_processed_4k.mkv")

    def test_ffmpeg_backend_pad_1600_svtav1(self, tmp_path: Path, ffmpeg_backend):
        video = tmp_path / "test.mkv"
        video.touch()
        cmd, output = build_transcode_command(
            video,
            "pad_1600",
            StreamSpec(width=3840, height=1081),
        )

        assert cmd[0] == C.FFMPEG_PATH
        assert "pad=iw:1600:0:" in _arg_after(cmd, "-vf")
        assert _arg_after(cmd, "-c:v") == "libsvtav1"
        assert _arg_after(cmd, "-preset") == "6"
        assert _arg_after(cmd, "-crf") == "29"
        assert _arg_after(cmd, "-g") == "300"
        assert _arg_after(cmd, "-pix_fmt") == "yuv420p10le"
        assert _arg_after(cmd, "-svtav1-params") == "tune=0"
        assert _arg_after(cmd, "-c:a") == "copy"
        assert "-b:a" not in cmd
        assert "-movflags" not in cmd
        assert output.name.endswith("_processed_pad1600.mkv")

    def test_unknown_strategy_raises(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        with pytest.raises(ValueError, match="未知策略"):
            build_transcode_command(
                video, "unknown", StreamSpec(width=1920, height=1081)
            )

    def test_unknown_backend_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(C, "TRANSCODE_BACKEND", "bad-backend")
        video = tmp_path / "test.mp4"
        video.touch()
        with pytest.raises(ValueError, match="未知转码后端"):
            build_transcode_command(
                video,
                "upscale_4k",
                StreamSpec(width=1920, height=1081),
            )

    def test_output_path_idempotent(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        spec = StreamSpec(width=1920, height=1081)
        _, out1 = build_transcode_command(video, "upscale_4k", spec)
        _, out2 = build_transcode_command(video, "upscale_4k", spec)
        assert out2 == out1

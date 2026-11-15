"""策略引擎测试：decide_video_strategy + build_transcode_command。"""

from pathlib import Path

import pytest

import yt_pipeline.config as C
from yt_pipeline.assessment_worker import build_transcode_command, decide_video_strategy
from yt_pipeline.model import StreamSpec

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
def svtav1_encoder(monkeypatch):
    """注入 svtav1 编码器常量，供 build_transcode_command 走 libsvtav1 分支。"""
    monkeypatch.setattr(C, "TRANSCODE_ENCODER", "svtav1")
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
    def default_nvenc_config(self, monkeypatch):
        monkeypatch.setattr(C, "TRANSCODE_ENCODER", "nvenc", raising=False)
        monkeypatch.setattr(C, "FFMPEG_PATH", "ffmpeg", raising=False)
        monkeypatch.setattr(C, "NVENC_PRESET", "p4", raising=False)
        monkeypatch.setattr(C, "NVENC_TUNE", "hq", raising=False)
        monkeypatch.setattr(C, "NVENC_RC", "vbr", raising=False)
        monkeypatch.setattr(C, "NVENC_CQ", 24, raising=False)
        monkeypatch.setattr(C, "NVENC_SPATIAL_AQ", 1, raising=False)
        monkeypatch.setattr(C, "NVENC_PROFILE", "main", raising=False)
        monkeypatch.setattr(C, "NVENC_AUDIO_BITRATE", 256, raising=False)
        monkeypatch.setattr(C, "NVENC_HW_DECODE", True, raising=False)

    def test_nvenc_upscale_4k(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, output = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=1920, height=1081, codec_name="vp9"),
        )

        assert cmd[0] == "ffmpeg"
        assert _arg_after(cmd, "-init_hw_device") == "cuda=cu:0"
        assert _arg_after(cmd, "-hwaccel") == "cuda"
        assert _arg_after(cmd, "-hwaccel_device") == "cu"
        assert _arg_after(cmd, "-hwaccel_output_format") == "cuda"
        vf = _arg_after(cmd, "-vf")
        assert vf.startswith("hwdownload,format=nv12,format=yuv420p,")
        assert (
            "scale=3840:2160:flags=lanczos:force_original_aspect_ratio=decrease" in vf
        )
        assert "force_divisible_by=2" in vf
        assert _arg_after(cmd, "-c:v") == "hevc_nvenc"
        assert _arg_after(cmd, "-preset") == "p4"
        assert _arg_after(cmd, "-tune") == "hq"
        assert _arg_after(cmd, "-rc") == "vbr"
        assert _arg_after(cmd, "-cq") == "24"
        assert _arg_after(cmd, "-b:v") == "0"
        assert _arg_after(cmd, "-spatial_aq") == "1"
        assert "-temporal_aq" not in cmd
        assert _arg_after(cmd, "-profile:v") == "main"
        assert _arg_after(cmd, "-tag:v") == "hvc1"
        assert _arg_after(cmd, "-c:a") == "aac"
        assert _arg_after(cmd, "-b:a") == "256k"
        assert _arg_after(cmd, "-ac") == "2"
        assert "0:V:0" in cmd
        assert "0:a:0?" in cmd
        assert _arg_after(cmd, "-movflags") == "+faststart"
        assert output.name.endswith("_processed_4k.mp4")
        assert output != video

    @pytest.mark.parametrize(
        "width, height",
        [(2560, 1440), (1440, 1080), (1920, 800)],
        ids=["exact_16_9", "4_3", "2_4_1"],
    )
    def test_nvenc_upscale_4k_preserves_aspect_ratio(
        self, tmp_path: Path, width, height
    ):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, _ = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=width, height=height, codec_name="vp9"),
        )
        vf = _arg_after(cmd, "-vf")
        # 尺寸交给 CPU Lanczos 的 scale 表达式，命令中不再出现输出尺寸参数
        assert (
            "scale=3840:2160:flags=lanczos:force_original_aspect_ratio=decrease" in vf
        )
        assert "pad" not in vf

    def test_nvenc_pad_1600(self, tmp_path: Path):
        video = tmp_path / "test.mkv"
        video.touch()
        cmd, output = build_transcode_command(
            video,
            "pad_1600",
            StreamSpec(width=3840, height=1081, codec_name="vp9"),
        )

        vf = _arg_after(cmd, "-vf")
        assert "pad=iw:1600:0:(1600-ih)/2:black" in vf
        assert _arg_after(cmd, "-c:v") == "hevc_nvenc"
        assert output.name.endswith("_processed_pad1600.mp4")
        assert output != video

    def test_nvenc_av1_falls_back_to_software_decode(self, tmp_path: Path):
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, _ = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=1920, height=1081, codec_name="av1"),
        )

        assert "-hwaccel" not in cmd
        assert "-hwaccel_output_format" not in cmd
        vf = _arg_after(cmd, "-vf")
        assert "hwdownload" not in vf
        assert vf.startswith("format=yuv420p,")

    def test_nvenc_hw_decode_disabled(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(C, "NVENC_HW_DECODE", False, raising=False)
        video = tmp_path / "test.mp4"
        video.touch()
        cmd, _ = build_transcode_command(
            video,
            "upscale_4k",
            StreamSpec(width=1920, height=1081, codec_name="vp9"),
        )

        assert "-hwaccel" not in cmd
        assert "hwdownload" not in _arg_after(cmd, "-vf")

    def test_svtav1_encoder_upscale_4k_svtav1(
        self,
        tmp_path: Path,
        svtav1_encoder,
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
            "scale=3840:2160:flags=lanczos:force_original_aspect_ratio=decrease" in vf
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

    def test_svtav1_encoder_pad_1600_svtav1(self, tmp_path: Path, svtav1_encoder):
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

    def test_unknown_encoder_raises(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(C, "TRANSCODE_ENCODER", "bad-encoder")
        video = tmp_path / "test.mp4"
        video.touch()
        with pytest.raises(ValueError, match="未知编码器"):
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

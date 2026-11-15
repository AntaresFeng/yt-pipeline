"""StreamSpec 属性测试。"""

import pytest

from yt_pipeline.model import StreamSpec


class TestStreamSpec:
    def test_horizontal_16_9(self):
        spec = StreamSpec(width=1920, height=1080)
        assert spec.short_edge == 1080
        assert spec.long_edge == 1920
        assert spec.ratio == pytest.approx(1920 / 1080)

    def test_vertical_9_16(self):
        spec = StreamSpec(width=1080, height=1920)
        assert spec.short_edge == 1080
        assert spec.long_edge == 1920
        assert spec.ratio == pytest.approx(1920 / 1080)

    def test_square(self):
        spec = StreamSpec(width=1080, height=1080)
        assert spec.short_edge == 1080
        assert spec.long_edge == 1080
        assert spec.ratio == 1.0

"""ImageSpec / VideoSpec 属性测试。"""

import pytest
from yt_pipeline.model import ImageSpec, VideoSpec


class TestImageSpec:
    def test_landscape(self):
        spec = ImageSpec(width=1920, height=1080)
        assert spec.is_landscape is True
        assert spec.is_portrait is False

    def test_portrait(self):
        spec = ImageSpec(width=1080, height=1920)
        assert spec.is_portrait is True
        assert spec.is_landscape is False

    def test_square_is_horizontal_like_reference(self):
        """正方形：width >= height → is_landscape=True, is_portrait=False。
        与参考项目行为一致。
        """
        spec = ImageSpec(width=1080, height=1080)
        assert spec.is_landscape is True
        assert spec.is_portrait is False


class TestVideoSpec:
    def test_horizontal_16_9(self):
        spec = VideoSpec(width=1920, height=1080)
        assert spec.is_horizontal is True
        assert spec.short_edge == 1080
        assert spec.long_edge == 1920
        assert spec.ratio == pytest.approx(1920 / 1080)

    def test_vertical_9_16(self):
        spec = VideoSpec(width=1080, height=1920)
        assert spec.is_horizontal is False
        assert spec.short_edge == 1080
        assert spec.long_edge == 1920

    def test_ultrawide_ratio(self):
        spec = VideoSpec(width=3840, height=1080)
        assert spec.is_horizontal is True
        assert spec.ratio == pytest.approx(3840 / 1080)

    def test_square(self):
        spec = VideoSpec(width=1080, height=1080)
        assert spec.is_horizontal is True  # width >= height
        assert spec.short_edge == 1080
        assert spec.long_edge == 1080
        assert spec.ratio == 1.0

"""Generate test media files using ffmpeg lavfi built-in sources.

Usage:
    python scripts/generate_test_media.py <output_dir>

Generates:
  - 16x9.png          Small test pattern image (16x9)
  - 640x480.png       SD test pattern image (640x480)
  - cover_640x360.png Small cover image (below 720p threshold)
  - cover_1280x720.png HD cover image (at 720p threshold)
  - test_short.mp4    Short test video clip (1s, 320x240)
"""

import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def generate_all(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # Small test pattern (16x9)
    # fmt: off
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=red:s=16x9:d=0.1",
        "-frames:v", "1",
        str(output_dir / "16x9.png"),
    ])
    # fmt: on

    # SD size (640x480, horizontal)
    # fmt: off
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=s=640x480:d=0.1",
        "-frames:v", "1",
        str(output_dir / "640x480.png"),
    ])
    # fmt: on

    # Small cover (below 720p threshold)
    # fmt: off
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=s=640x360:d=0.1",
        "-frames:v", "1",
        str(output_dir / "cover_640x360.png"),
    ])
    # fmt: on

    # HD cover (at 720p threshold)
    # fmt: off
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=s=1280x720:d=0.1",
        "-frames:v", "1",
        str(output_dir / "cover_1280x720.png"),
    ])
    # fmt: on

    # Short video clip (1s)
    # fmt: off
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "testsrc=s=320x240:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-t", "1",
        str(output_dir / "test_short.mp4"),
    ])
    # fmt: on

    print(f"Generated test media in {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/generate_test_media.py <output_dir>")
        sys.exit(1)
    generate_all(Path(sys.argv[1]))

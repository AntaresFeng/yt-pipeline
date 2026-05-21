"""yt-pipeline 便捷入口: python main.py --help"""

import sys
from yt_pipeline.cli import main


def flush_input():
    """清空标准输入缓冲区中所有未读取的内容。"""
    try:
        # Windows
        import msvcrt

        while msvcrt.kbhit():
            msvcrt.getch()
    except ImportError:
        # Unix (Linux / macOS)
        import termios

        termios.tcflush(sys.stdin, termios.TCIFLUSH)


if __name__ == "__main__":
    main()
    flush_input()
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass

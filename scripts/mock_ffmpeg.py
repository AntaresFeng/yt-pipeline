"""Mock ffmpeg —— 用于测试优雅退出。

通过 stdin 接收 'q\n' 触发优雅退出（exit 42），与正常完成（exit 0）区分。
环境变量控制行为（由 PipelineConfig.to_env() 传入）:
  MOCK_FFMPEG_FRAMES      - 处理帧数 (默认 10)
  MOCK_FFMPEG_FRAME_DELAY - 每帧延时秒数 (默认 1.0)
  MOCK_FFMPEG_CLEANUP_DELAY - 退出清理延时 (默认 0.5)

注意：真实 ffmpeg 的交互模式通过终端 raw 模式读取单字符 'q' 即可退出，
无需回车。本 mock 因为 stdin 是管道（非 tty），只能行缓冲读取，故
要求发送 'q\n'。调用方（mocks.py）已处理此差异。
"""

import argparse
import os
import sys
import threading
import time

EXIT_Q = 42  # 收到 'q' 优雅退出
STATUS_CONTROL_C_EXIT = -1073741510  # 被 Ctrl+C 杀死


def _stdin_reader(stop_event: threading.Event, q_event: threading.Event):
    """后台线程：从 stdin 管道读取，检测 'q' 指令。"""
    try:
        for line in sys.stdin:
            if stop_event.is_set():
                return
            if line.strip() == "q":
                q_event.set()
                return
    except (OSError, ValueError):
        pass


def main():
    parser = argparse.ArgumentParser(
        description="Mock ffmpeg for graceful shutdown testing"
    )
    parser.add_argument(
        "--frames", type=int, default=None, help="Number of frames to process"
    )
    parser.add_argument(
        "--frame-delay", type=float, default=None, help="Delay per frame in seconds"
    )
    parser.add_argument(
        "--cleanup-delay", type=float, default=None, help="Cleanup delay in seconds"
    )
    args = parser.parse_args()

    frame_count = args.frames or int(os.environ.get("MOCK_FFMPEG_FRAMES", "10"))
    frame_delay = args.frame_delay or float(
        os.environ.get("MOCK_FFMPEG_FRAME_DELAY", "1.0")
    )
    cleanup_delay = args.cleanup_delay or float(
        os.environ.get("MOCK_FFMPEG_CLEANUP_DELAY", "0.5")
    )

    # 启动 stdin 读取线程（pipe 模式）
    q_event = threading.Event()
    stop_event = threading.Event()
    reader = threading.Thread(
        target=_stdin_reader, args=(stop_event, q_event), daemon=True
    )
    reader.start()

    print("ffmpeg version xxxxx (mock)")
    exit_code = 0
    try:
        for i in range(frame_count):
            print(f"processing frame {i}...", flush=True)
            # 使用 wait 而不是 sleep，收到 'q' 时立即响应
            if q_event.wait(timeout=frame_delay):
                print("Received 'q', exiting...")
                time.sleep(cleanup_delay)
                exit_code = EXIT_Q
                break
    except KeyboardInterrupt:
        print("KeyboardInterrupt received, exiting...")
        time.sleep(cleanup_delay)
        exit_code = STATUS_CONTROL_C_EXIT
    finally:
        stop_event.set()

    if exit_code == 0:
        print("ffmpeg done")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

import signal
import time


def handler(sig, frame):
    print("捕获到 CTRL+Break")
    raise KeyboardInterrupt


signal.signal(signal.SIGBREAK, handler)  # 仅 Windows 有效

while True:
    time.sleep(1)
    print("正在运行...")

# mock ffmpeg script for testing graceful shutdown
import sys
import time
import msvcrt

STATUS_CONTROL_C_EXIT = -1073741510  # Windows 上 Ctrl+C 导致的退出码

def check_key():
    """非阻塞地检查是否有按键输入。"""
    if msvcrt.kbhit():  # 核心函数：检查是否有按键事件
        key = msvcrt.getch()  # 读取一个字节的按键值
        return key
    return None


print("ffmpeg version xxxxx (mock)")
try:
    for i in range(10):
        ch = check_key()
        if ch and ch == b"q":
            print("Received 'q', exiting...")
            time.sleep(0.5)  # 模拟 ffmpeg 退出前的清理时间
            sys.exit(0)
        print(f"processing frame {i}...", flush=True)
        time.sleep(1)
except KeyboardInterrupt:
    print("KeyboardInterrupt received, exiting...")
    time.sleep(0.5)
    sys.exit(STATUS_CONTROL_C_EXIT)

print("ffmpeg done")

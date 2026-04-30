"""URL 收集：文件读取、剪贴板监控、交互输入。"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

try:
    import pyperclip
except ImportError:
    pyperclip = None  # type: ignore


def collect_urls(urls: list[str] | None = None, file_path: str | None = None) -> list[str]:
    """收集 URL。优先级：file_path > urls > 交互输入。"""
    if file_path:
        return _from_file(Path(file_path))

    if urls:
        return _filter(urls)

    return _from_input()


# ---------------------------------------------------------------------------
# internal
# ---------------------------------------------------------------------------


def _from_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    result = _filter(lines)
    if not result:
        print("文件中未找到有效链接。")
    return result


def _from_input() -> list[str]:
    monitor = _ClipboardMonitor()
    monitor.start()
    try:
        typed = input("请输入视频链接（回车结束）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        monitor.stop()
        return []
    clipboard_items = monitor.stop()

    candidates = ([typed] if typed else []) + clipboard_items
    urls = _filter(candidates)
    return _confirm(urls)


def _filter(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in items:
        s = raw.strip()
        if s and s not in seen and _is_url(s):
            seen.add(s)
            result.append(s)
    return result


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://")) or bool(_YT_ID_RE.match(s))


def _confirm(urls: list[str]) -> list[str]:
    if not urls:
        print("未检测到有效链接。")
        return []
    print(f"\n检测到 {len(urls)} 个有效链接:")
    for i, url in enumerate(urls, 1):
        print(f"  {i}. {url}")
    while True:
        try:
            raw = input("确认处理以上链接? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            return []
        if not raw or raw in ("y", "yes"):
            return urls
        if raw in ("n", "no"):
            return []
        print("请输入 y 或 n。")


class _ClipboardMonitor:
    def __init__(self):
        self._items: list[str] = []
        self._thread: threading.Thread | None = None
        self._last = ""
        self._stop = threading.Event()

    def start(self) -> None:
        if not pyperclip:
            return
        self._last = pyperclip.paste() or ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print("剪贴板监控已启动，复制链接后按回车确认...")

    def stop(self) -> list[str]:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1)
            self._thread = None
        return list(self._items)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                cur = pyperclip.paste()
                if cur and cur != self._last:
                    self._last = cur
                    self._items.append(cur)
            except Exception:
                pass
            time.sleep(0.5)

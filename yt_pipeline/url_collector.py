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


def collect_urls(
    urls: list[str] | None = None, file_path: str | None = None
) -> list[str]:
    """收集 URL。优先级：file_path > urls > 交互输入。"""
    if file_path:
        return _from_file(Path(file_path))
    if urls:
        return _filter(urls)
    return _from_input()


def _from_file(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    result = _filter(lines)
    if not result:
        print("No valid links were found in the file.")
    return result


def _from_input() -> list[str]:
    monitor = _ClipboardMonitor()
    monitor.start()
    try:
        typed = input("Enter video links (press Enter to finish): ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
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
        print("No valid links detected.")
        return []
    if len(urls) == 1:
        print(f"\nDetected 1 valid link: {urls[0]}")
        return urls

    print(f"\nDetected {len(urls)} valid links:")
    for i, url in enumerate(urls, 1):
        print(f"  {i}. {url}")
    while True:
        try:
            raw = input("Confirm processing these links? [Y/n] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return []
        if not raw or raw in ("y", "yes"):
            return urls
        if raw in ("n", "no"):
            return []
        print("Please enter y or n.")


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
        print(
            "Clipboard monitoring started. Copy links, then press Enter to confirm..."
        )

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
            except Exception:  # noqa: S110, BLE001 - 剪贴板轮询，读取失败直接忽略
                pass
            time.sleep(0.5)

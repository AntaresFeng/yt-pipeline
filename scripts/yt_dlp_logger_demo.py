"""yt-dlp logger + progress_hooks 功能演示。

独立脚本，验证 yt-dlp 的日志桥接和下载进度回调机制。

用法:
    python examples/yt_dlp_logger_demo.py                           # 使用默认测试 URL
    python examples/yt_dlp_logger_demo.py https://youtube.com/...   # 指定 URL
"""

from __future__ import annotations

import logging
import sys
from datetime import timedelta

import yt_dlp
from yt_dlp.utils import DownloadError

# ---------------------------------------------------------------------------
# Logging 配置 —— 与项目 cli.py 风格一致
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("pipeline.ytdlp")


# ---------------------------------------------------------------------------
# 自定义 Logger：桥接 yt-dlp 内部日志到 Python logging
# ---------------------------------------------------------------------------
class YtdlpLogger:
    """实现 yt-dlp logger 接口 (debug / info / warning / error)。

    yt-dlp 的 debug 和 info 都通过 debug() 方法传递，
    通过 '[debug] ' 前缀区分两者。
    """

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            logger.debug(msg)
        elif msg.startswith("[download]") and "ETA" in msg:
            pass  # 进度信息不显示
        else:
            self.info(msg)

    def info(self, msg: str) -> None:
        logger.info(msg)

    def warning(self, msg: str) -> None:
        logger.warning(msg)

    def error(self, msg: str) -> None:
        logger.error(msg)


# ---------------------------------------------------------------------------
# Progress Hook：实时下载进度回调
# ---------------------------------------------------------------------------
def progress_hook(d: dict) -> None:
    """yt-dlp progress_hooks 回调。

    d 字典关键字段:
        status:         'downloading' | 'finished' | 'error'
        downloaded_bytes: 已下载字节数
        total_bytes:      总字节数 (可能为 None)
        total_bytes_estimate: 预估总字节数
        speed:          下载速度 (bytes/s)
        eta:            预估剩余秒数
        filename:       文件名
        elapsed:        已用秒数
    """
    status = d.get("status")

    if status == "downloading":
        downloaded = d.get("downloaded_bytes", 0)
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        speed = d.get("speed")
        eta = d.get("eta")

        # 百分比
        if total:
            pct = downloaded / total * 100
            size_str = f"{downloaded / 1048576:.1f}/{total / 1048576:.1f} MB"
        else:
            pct = 0
            size_str = f"{downloaded / 1048576:.1f}/? MB"

        # 速度
        speed_str = f"{speed / 1048576:.2f} MB/s" if speed else "?"

        # ETA
        if eta is not None:
            eta_str = str(timedelta(seconds=int(eta)))
        else:
            eta_str = "?"

        print(
            f"\r  [{pct:5.1f}%] {size_str}  |  {speed_str}  |  ETA {eta_str}  ",
            end="",
            flush=True,
        )

    elif status == "finished":
        print()  # 换行，结束 \r 行
        filename = d.get("filename", "")
        logger.info("下载完成: %s", filename)
        logger.info("开始后处理...")

    elif status == "error":
        logger.error("下载出错: %s", d.get("error", "未知错误"))


# ---------------------------------------------------------------------------
# 主函数
# ---------------------------------------------------------------------------
def download(url: str) -> dict:
    """下载单个视频，返回 yt-dlp info dict。"""
    ydl_opts = {
        "logger": YtdlpLogger(),
        # "progress_hooks": [progress_hook],
        # 以下选项与项目 download.py 保持一致
        "writethumbnail": True,
        "writesubtitles": True,
        # "writeinfojson": True,
        # "subtitlesformat": "srt",
        "outtmpl": "%(title).180B [%(id)s].%(ext)s",
        "postprocessors": [
            {
                "key": "FFmpegThumbnailsConvertor",
                "format": "png",
                "when": "before_dl",
            }
        ],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if info and info.get("_type") == "playlist":
            entries = info.get("entries") or []
            if not entries:
                raise RuntimeError("链接是播放列表但未获取到可下载视频。")
            info = entries[0]
        # ℹ️ ydl.sanitize_info makes the info json-serializable
        # save to file
        # with open("downloaded_info.json", "w", encoding="utf-8") as f:
        #     json.dump(ydl.sanitize_info(info), f, ensure_ascii=False, indent=2)
        return info


def print_summary(info: dict) -> None:
    """打印下载结果摘要。"""
    print("\n" + "=" * 60)
    print("下载摘要")
    print("=" * 60)
    print(f"  标题:   {info.get('title', '?')}")
    print(f"  ID:     {info.get('id', '?')}")
    print(f"  时长:   {info.get('duration_string', '?')}")
    print(f"  分辨率: {info.get('width', '?')}x{info.get('height', '?')}")
    print(f"  上传者: {info.get('uploader', '?')}")
    filename = info.get("_filename")
    if not filename:
        try:
            filename = info["requested_downloads"][0]["filepath"]
        except (KeyError, IndexError):
            filename = "未知文件名"
    print(f"  文件:   {filename}")
    print("=" * 60)


def main() -> None:
    urls = (
        sys.argv[1:]
        if len(sys.argv) > 1
        else [
            "https://www.youtube.com/watch?v=BaW_jenozKc",
            "https://www.youtube.com/watch?v=DTi8wZ1a1TA",
        ]
    )

    for url in urls:
        logger.info("开始下载: %s", url)
        try:
            info = download(url)
            print_summary(info)
        except DownloadError as e:
            logger.error("下载失败: %s — %s", url, e)
            continue
        except Exception:
            logger.exception("下载失败（意外错误）: %s", url)
            sys.exit(1)


if __name__ == "__main__":
    main()

"""url_collector 单元测试：URL 收集、过滤、文件读取。"""

from pathlib import Path

from yt_pipeline.url_collector import collect_urls, _filter


class TestCollectUrlsFromFile:
    def test_collect_urls_from_file(self, tmp_path: Path):
        path = tmp_path / "urls.txt"
        path.write_text(
            "https://youtube.com/watch?v=abc123\n"
            "AbCdEfGhIjK\n"
            "\n",
            encoding="utf-8",
        )
        result = collect_urls(file_path=str(path))
        assert len(result) == 2
        assert result[0] == "https://youtube.com/watch?v=abc123"
        assert result[1] == "AbCdEfGhIjK"

    def test_collect_urls_from_file_empty(self, tmp_path: Path, capsys):
        path = tmp_path / "urls.txt"
        path.write_text("\nnot a url\n  \n", encoding="utf-8")
        result = collect_urls(file_path=str(path))
        assert result == []
        assert "No valid links were found in the file." in capsys.readouterr().out


class TestCollectUrlsFromList:
    def test_collect_urls_from_list(self):
        result = collect_urls(
            urls=["https://a.com", "https://b.com", "https://a.com"]
        )
        assert result == ["https://a.com", "https://b.com"]


class TestFilterIsUrlVariants:
    def test_filter_is_url_variants(self):
        result = _filter(
            [
                "https://youtube.com/watch?v=x",
                "AbCdEfGhIjK",
                "ftp://example.com",
                "short",
                "",
            ]
        )
        assert result == ["https://youtube.com/watch?v=x", "AbCdEfGhIjK"]


def make_input_sequence(responses: list[str]):
    """返回一个 input() 替身，依次返回 responses，用完抛 EOFError。"""
    it = iter(responses)

    def _input(prompt=""):
        try:
            return next(it)
        except StopIteration:
            raise EOFError

    return _input


class TestFromInput:
    def test_from_input_typed_and_clipboard(self, monkeypatch):
        class FakeMonitor:
            def start(self): ...
            def stop(self):
                return ["https://clip.com"]

        monkeypatch.setattr(
            "yt_pipeline.url_collector._ClipboardMonitor", FakeMonitor
        )
        monkeypatch.setattr(
            "builtins.input", make_input_sequence(["https://typed.com", "y"])
        )
        result = collect_urls()
        assert "https://typed.com" in result
        assert "https://clip.com" in result

    def test_from_input_cancel_eof(self, monkeypatch):
        class FakeMonitor:
            def __init__(self):
                self.stopped = False

            def start(self): ...

            def stop(self):
                self.stopped = True
                return []

        fake = FakeMonitor()
        monkeypatch.setattr(
            "yt_pipeline.url_collector._ClipboardMonitor",
            lambda: fake,
        )
        monkeypatch.setattr("builtins.input", make_input_sequence([]))
        result = collect_urls()
        assert result == []
        assert fake.stopped

    def test_clipboard_monitor_no_pyperclip(self, monkeypatch):
        monkeypatch.setattr("yt_pipeline.url_collector.pyperclip", None)
        from yt_pipeline.url_collector import _ClipboardMonitor

        monitor = _ClipboardMonitor()
        monitor.start()
        result = monitor.stop()
        assert monitor._thread is None
        assert result == []

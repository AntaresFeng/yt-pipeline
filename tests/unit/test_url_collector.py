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

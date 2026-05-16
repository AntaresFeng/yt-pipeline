'''cli 单元测试：参数解析、任务准备、主流程调度。'''

import argparse

import pytest

from yt_pipeline.cli import parse_args, prepare_tasks
from yt_pipeline.model import Task, States, RESUME_RESET


class TestParseArgs:
    def test_parse_args_defaults(self):
        args = parse_args([])
        assert args.resume is False
        assert args.fresh is False
        assert args.file is None
        assert args.urls == []

    def test_parse_args_resume_and_urls(self):
        args = parse_args(["--resume", "https://a.com"])
        assert args.resume is True
        assert args.urls == ["https://a.com"]

    def test_parse_args_fresh_and_file(self):
        args = parse_args(["--fresh", "--file", "urls.txt"])
        assert args.fresh is True
        assert args.file == "urls.txt"

    def test_parse_args_resume_fresh_exclusive(self):
        with pytest.raises(SystemExit):
            parse_args(["--resume", "--fresh"])

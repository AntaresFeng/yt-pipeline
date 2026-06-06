"""cli 单元测试：参数解析、任务准备、主流程调度。"""

import argparse
import pytest

from yt_pipeline.cli import parse_args, prepare_tasks
from yt_pipeline.model import Task, States


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


class TestPrepareTasks:
    def test_prepare_tasks_fresh(
        self, state_file, mock_load_progress, mock_collect_urls
    ):
        mock_load_progress([Task(url="https://old.com", state=States.DOWNLOADING)])
        mock_collect_urls(["https://a.com"])
        state_file.write_text("{}", encoding="utf-8")  # create the file

        args = argparse.Namespace(resume=False, fresh=True, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert not state_file.exists()
        assert len(tasks) == 1
        assert tasks[0].url == "https://a.com"
        assert tasks[0].state == States.PENDING

    def test_prepare_tasks_resume(self, state_file, mock_load_progress):
        saved = [Task(url="https://old.com", state=States.DOWNLOADING)]
        mock_load_progress(saved)

        args = argparse.Namespace(resume=True, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert len(tasks) == 1
        assert (
            tasks[0].state == States.PENDING
        )  # DOWNLOADING → PENDING via RESUME_RESET

    def test_prepare_tasks_prompt_yes(
        self, state_file, mock_load_progress, monkeypatch
    ):
        saved = [Task(url="https://old.com", state=States.DOWNLOADING)]
        mock_load_progress(saved)
        monkeypatch.setattr("builtins.input", lambda prompt="": "y")

        args = argparse.Namespace(resume=False, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert tasks[0].state == States.PENDING

    def test_prepare_tasks_prompt_no(
        self, state_file, mock_load_progress, mock_collect_urls, monkeypatch
    ):
        saved = [Task(url="https://old.com", state=States.DOWNLOADING)]
        mock_load_progress(saved)
        mock_collect_urls(["https://new.com"])
        state_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("builtins.input", lambda prompt="": "n")

        args = argparse.Namespace(resume=False, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert not state_file.exists()
        assert len(tasks) == 1
        assert tasks[0].url == "https://new.com"

    def test_prepare_tasks_no_urls(self, mock_load_progress, mock_collect_urls):
        mock_load_progress(None)
        mock_collect_urls([])

        args = argparse.Namespace(resume=False, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert tasks == []

    def test_prepare_tasks_resume_failed(self, state_file, mock_load_progress):
        saved = [Task(url="https://old.com", state=States.FAILED, errors=["boom"])]
        mock_load_progress(saved)

        args = argparse.Namespace(resume=True, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert len(tasks) == 1
        assert tasks[0].state == States.PENDING  # FAILED → PENDING via RESUME_RESET
        assert tasks[0].errors == ["boom"]  # errors 保留

    def test_prepare_tasks_resume_filters_done(self, state_file, mock_load_progress):
        saved = [
            Task(url="https://done.com", state=States.DONE),
            Task(url="https://old.com", state=States.DOWNLOADING),
        ]
        mock_load_progress(saved)

        args = argparse.Namespace(resume=True, fresh=False, file=None, urls=[])
        tasks = prepare_tasks(args)

        assert len(tasks) == 1
        assert tasks[0].url == "https://old.com"
        assert tasks[0].state == States.PENDING  # DOWNLOADING → PENDING


class TestMain:
    def test_main_resolves_paths_when_dependency_check_skipped(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.SKIP_CHECK_DEPENDENCIES", True)
        monkeypatch.setattr("yt_pipeline.cli.OUTPUT_DIR", tmp_path)

        calls = []
        monkeypatch.setattr(
            "yt_pipeline.cli.resolve_dependency_paths",
            lambda: calls.append("resolve"),
        )
        monkeypatch.setattr(
            "yt_pipeline.cli.check_dependencies",
            lambda: (_ for _ in ()).throw(AssertionError("should be skipped")),
        )
        monkeypatch.setattr(
            "yt_pipeline.cli.parse_args",
            lambda: argparse.Namespace(resume=False, fresh=False, file=None, urls=[]),
        )
        monkeypatch.setattr("yt_pipeline.cli.prepare_tasks", lambda args: [])

        from yt_pipeline.cli import main

        main()

        assert calls == ["resolve"]

    def test_main_no_tasks(self, monkeypatch, tmp_path):
        monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.resolve_dependency_paths", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("yt_pipeline.deps.check_dependencies", lambda: None)
        monkeypatch.setattr(
            "yt_pipeline.cli.parse_args",
            lambda: argparse.Namespace(resume=False, fresh=False, file=None, urls=[]),
        )
        monkeypatch.setattr("yt_pipeline.cli.prepare_tasks", lambda args: [])
        called = []

        def _fake_run(coro):
            called.append(coro)
            coro.close()

        monkeypatch.setattr("asyncio.run", _fake_run)

        from yt_pipeline.cli import main

        main()
        assert len(called) == 0

    def test_main_with_tasks(self, monkeypatch, tmp_path):
        monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.resolve_dependency_paths", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.OUTPUT_DIR", tmp_path)
        monkeypatch.setattr("yt_pipeline.deps.check_dependencies", lambda: None)
        monkeypatch.setattr(
            "yt_pipeline.cli.parse_args",
            lambda: argparse.Namespace(resume=False, fresh=False, file=None, urls=[]),
        )
        monkeypatch.setattr(
            "yt_pipeline.cli.prepare_tasks",
            lambda args: [Task(url="https://a.com")],
        )
        called = []

        def _fake_run(coro):
            called.append(coro)
            coro.close()

        monkeypatch.setattr("asyncio.run", _fake_run)

        from yt_pipeline.cli import main

        main()
        assert len(called) == 1

    def test_main_dependency_missing(self, monkeypatch, tmp_path):
        import argparse

        from yt_pipeline.deps import DependencyError

        monkeypatch.setattr("yt_pipeline.cli._setup_logging", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.resolve_dependency_paths", lambda: None)
        monkeypatch.setattr("yt_pipeline.cli.OUTPUT_DIR", tmp_path)

        def _fail():
            raise DependencyError("ffmpeg", "未找到 ffmpeg")

        monkeypatch.setattr("yt_pipeline.cli.SKIP_CHECK_DEPENDENCIES", False)
        monkeypatch.setattr("yt_pipeline.cli.check_dependencies", _fail)
        monkeypatch.setattr(
            "yt_pipeline.cli.parse_args",
            lambda: argparse.Namespace(resume=False, fresh=False, file=None, urls=[]),
        )

        from yt_pipeline.cli import main

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

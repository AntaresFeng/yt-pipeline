"""单元测试共享 fixture。"""

import os
from pathlib import Path

import pytest


@pytest.fixture
def chdir(tmp_path: Path):
    """切换工作目录到 tmp_path，测试结束后自动恢复。"""
    orig = os.getcwd()
    os.chdir(tmp_path)
    yield
    os.chdir(orig)


@pytest.fixture
def state_file(tmp_path, monkeypatch):
    """替换 cli 中的 STATE_FILE 到 tmp_path。"""
    sf = tmp_path / "progress.json"
    monkeypatch.setattr("yt_pipeline.cli.STATE_FILE", sf)
    return sf


@pytest.fixture
def mock_load_progress(monkeypatch):
    """替换 load_progress，返回可配置的预设值。用法：mock_load_progress(tasks_list)"""
    _return = [None]

    def _set(tasks):
        _return[0] = tasks

    monkeypatch.setattr("yt_pipeline.cli.load_progress", lambda _: _return[0])
    return _set


@pytest.fixture
def mock_collect_urls(monkeypatch):
    """替换 collect_urls，返回可配置的预设值。用法：mock_collect_urls(["url1"])"""
    _return = [[]]

    def _set(urls):
        _return[0] = urls

    monkeypatch.setattr("yt_pipeline.cli.collect_urls", lambda *a: _return[0])
    return _set

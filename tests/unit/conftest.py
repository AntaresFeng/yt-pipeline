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

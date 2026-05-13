# 测试重构：单元测试分离

> 范围仅限单元测试，集成测试重构后续再做。

**Goal:** 将当前 `tests/` 根目录下混杂的单元测试提取到 `tests/unit/`，清理样板代码，删除历史残留。

**Architecture:** `tests/unit/` 下 4 个模块文件 + 1 个空 conftest，被测函数全部不 spawn 子进程（纯内存/文件操作）。

---

## 目录变化

```
tests/                          →  删除根级旧文件（test_models.py, test_strategy.py, test_download.py）
tests/unit/
├── __init__.py
├── conftest.py                 →  空，tmp_path 是 pytest 内置无需定义
├── test_models.py              ←  移自 tests/test_models.py（无改动）
├── test_strategy.py            ←  移自 tests/test_strategy.py（无改动）
├── test_download.py            ←  移自 tests/test_download.py + chdir fixture 消重
└── test_thumbnail.py           ←  从 tests/test_thumbnail.py 拆出 TestFindThumbnail
```

## 被测函数覆盖

| 文件 | 函数 | 测试数 |
|------|------|--------|
| test_models.py | StreamSpec 属性 | 4 |
| test_strategy.py | decide_video_strategy + build_ffmpeg_command | 15 |
| test_download.py | generate_credits + resolve_video_path | 6 |
| test_thumbnail.py | find_thumbnail | 3 |

## 样板清理

- `test_download.py` / `test_thumbnail.py` 中重复的 `os.chdir(tmp_path)` pattern 抽出为 `chdir` fixture
- 删除根级 `conftest.py` 中的集成测试专用工具（PipelineEnv, make_test_image 等），这些后续归入 `tests/integration/conftest.py`

## 不涉及

- 集成测试文件（test_probe.py, test_process.py, test_transcode.py, test_transcoder.py, test_pipeline.py）暂留原位
- 无新测试逻辑编写

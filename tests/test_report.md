# 测试分类报告

## 概览

| 分类 | 数量 | 说明 |
|------|------|------|
| 单元测试 | 31 | 纯逻辑验证，无外部依赖（或仅依赖文件系统） |
| 集成测试 | 20 | 涉及真实子进程、ffmpeg/ffprobe 或 monkeypatch 替换业务函数 |
| 合计 | 51 | — |

---

## 单元测试（31 个）

### test_models.py — 数据模型（7 个）

验证 `ImageSpec` / `VideoSpec` 的纯属性逻辑。

| 用例 | 测试内容 |
|------|----------|
| `test_landscape` | 横向图片 `is_landscape` / `is_portrait` |
| `test_portrait` | 纵向图片方向检测 |
| `test_square_is_horizontal_like_reference` | 正方形归类为横向 |
| `test_horizontal_16_9` | 16:9 的 `short_edge`、`long_edge`、`ratio` |
| `test_vertical_9_16` | 纵向视频属性 |
| `test_ultrawide_ratio` | 超宽屏 (3840x1080) 属性 |
| `test_square` | 正方形 `is_horizontal=True`、`ratio=1.0` |

外部依赖：无。

### test_strategy.py — 策略引擎（15 个）

验证 `decide_video_strategy` 决策逻辑和 `build_ffmpeg_command` 命令构建。

| 用例 | 测试内容 |
|------|----------|
| `test_decide_strategy` (10 个参数化) | 竖屏 / 短边阈值 / 4K 超分 / 黑边填充各场景 |
| `test_upscale_4k` | 命令包含 `scale=3840:2160:flags=lanczos` |
| `test_pad_1600` | 命令包含 `pad=iw:1600:0:` |
| `test_unknown_strategy_raises` | 未知策略抛 `ValueError` |
| `test_output_avoids_overwrite` | 输出文件已存在时自动加后缀 |
| `test_command_flags` | 命令含 `-n`、`-c:v libx264`、`-c:a aac` |

外部依赖：仅 `tmp_path`（创建空文件做路径测试）。

### test_download.py — 下载模块（6 个）

验证 `generate_credits` 文案生成和 `resolve_video_path` 路径解析。

| 用例 | 测试内容 |
|------|----------|
| `test_basic` | 生成 `.description` 含 URL、频道、标题、版权声明 |
| `test_missing_fields` | 字段缺失时回退到 "未知" |
| `test_from_requested_downloads` | 从 `requested_downloads[].filepath` 解析 |
| `test_from_filename` | 从 `_filename` 回退解析 |
| `test_from_glob` | 通过 video_id glob 匹配 |
| `test_not_found` | 找不到文件返回 `None` |

外部依赖：仅文件系统（`tmp_path` + `.touch()` 创建假文件）。

### test_thumbnail.py::TestFindThumbnail — 封面查找（3 个）

| 用例 | 测试内容 |
|------|----------|
| `test_by_video_extensions` | 同名扩展名匹配（video.mp4 → video.png） |
| `test_by_video_id_glob` | video_id glob 模式匹配 |
| `test_no_thumbnail` | 无匹配返回 `None` |

外部依赖：仅文件系统。

---

## 集成测试（21 个）

### 集成层级说明

| 层级 | 描述 | 涉及模块 |
|------|------|----------|
| **子进程级** | 测试异步子进程管理，用 `mock_ffmpeg.py` 模拟 ffmpeg | test_process, test_transcoder |
| **工具级** | 调用真实 ffmpeg/ffprobe 进行媒体处理 | test_probe, test_thumbnail |
| **进程内级** | 直接调用 `run_pipeline()`，monkeypatch 替换业务函数，`asyncio.Event` 控制时序 | test_pipeline |

### test_process.py — 子进程运行器（5 个）

| 用例 | 测试内容 | 集成层级 |
|------|----------|----------|
| `test_run_command_hello` | 启动 Python 子进程获取 stdout（rc=0） | 子进程级 |
| `test_run_command_failure` | 子进程非零退出的错误处理 | 子进程级 |
| `test_run_transcode_normal_completion` | `mock_ffmpeg.py` 正常完成 | 子进程级 |
| `test_run_transcode_graceful_shutdown` | shutdown 时发送 `q` 信号并抛 `CancelledError` | 子进程级 |
| `test_run_transcode_ffmpeg_failure` | ffmpeg 非零退出抛 `RuntimeError` | 子进程级 |

依赖：真实子进程（`asyncio.create_subprocess_exec`）、`mock_ffmpeg.py`。不调用真实 ffmpeg。

### test_probe.py — ffprobe 尺寸探测（3 个）

| 用例 | 测试内容 | 集成层级 |
|------|----------|----------|
| `test_probe_png_dimensions` | 真实 ffmpeg 生成图片 → ffprobe 探测尺寸 | 工具级 |
| `test_probe_nonexistent_file` | 不存在文件抛 `RuntimeError` | 工具级 |
| `test_probe_dimensions_returns_videospec` | ffprobe 返回正确 `VideoSpec` | 工具级 |

依赖：真实 ffmpeg（生成测试素材）、真实 ffprobe（探测）。通过 `@pytest.mark.skipif` 条件跳过。

### test_thumbnail.py — 封面处理（2 个）

| 用例 | 测试内容 | 集成层级 |
|------|----------|----------|
| `test_process_thumbnail_below_threshold` | 高度 < 720 时触发超分处理 | 工具级 |
| `test_process_thumbnail_above_threshold` | 高度 ≥ 720 时跳过处理 | 工具级 |

依赖：真实 ffmpeg + ffprobe。通过 `@pytest.mark.skipif` 条件跳过。

### test_transcoder.py — 转码薄层（2 个）

| 用例 | 测试内容 | 集成层级 |
|------|----------|----------|
| `test_transcode_normal` | `mock_ffmpeg.py` 正常完成转码 | 子进程级 |
| `test_transcode_shutdown` | shutdown 触发时抛 `CancelledError` | 子进程级 |

依赖：`mock_ffmpeg.py` 子进程、asyncio。不调用真实 ffmpeg。

### test_pipeline.py — 管道中断与恢复（7 个）

进程内集成测试，直接调用 `run_pipeline()`，用 monkeypatch 替换业务函数，用 `asyncio.Event` 控制执行时序。

**中断场景（3 个）：**

| 用例 | 测试内容 |
|------|----------|
| `test_interrupt_during_download` | 下载阶段 `shutdown.event.set()` → progress.json 状态为 downloading |
| `test_interrupt_during_transcode` | 转码阶段 `shutdown.event.set()` → progress.json 状态为 processing_video |
| `test_interrupt_during_assessment` | 探测阶段 `shutdown.event.set()` → progress.json 状态不为 DONE |

**恢复场景（4 个）：**

| 用例 | 测试内容 |
|------|----------|
| `test_resume_after_download_interrupt` | 从下载中断恢复 → 加载状态 → 最终完成 |
| `test_resume_after_ffmpeg_interrupt` | 从转码中断恢复 → 转码完成 → 最终完成 |
| `test_auto_discard_n` | `-n` 标志自动丢弃已完成任务 |
| `test_happy_path` | 正常走完 → "All tasks processed" + progress.json 删除 |

依赖：monkeypatch（替换 download_video / transcode_video / ffprobe_dimensions）、asyncio.Event、文件系统。无 ffmpeg/ffprobe 依赖。

---

## 外部依赖汇总

| 依赖 | 用途 | 涉及测试 |
|------|------|----------|
| 真实子进程 (`asyncio.create_subprocess_exec`) | run_command / run_transcode | test_process, test_transcoder |
| 真实 ffmpeg | 生成测试图片/视频、封面处理 | test_probe, test_thumbnail, conftest |
| 真实 ffprobe | 探测媒体尺寸 | test_probe, test_thumbnail |
| `mock_ffmpeg.py` | 模拟 ffmpeg 行为的 Python 脚本 | test_process, test_transcoder |
| monkeypatch | 替换业务函数（download/transcode/probe） | test_pipeline |
| asyncio 事件循环 | 异步协作 | test_process, test_transcoder, test_pipeline |
| 文件系统 | progress.json 读写、临时文件 | test_pipeline, test_download, test_thumbnail |

**无网络依赖** — 所有测试通过 `PIPELINE_DRY_RUN=true` 干运行模式，不访问外部网络。

## 设计特点

1. **条件跳过**：依赖 ffmpeg/ffprobe 的测试通过 `@pytest.mark.skipif(not media_available)` 在无环境下自动跳过。
2. **mock_ffmpeg 替代真实转码**：子进程级和转码测试用 `scripts/mock_ffmpeg.py` 模拟 ffmpeg 行为，快速可控。
3. **monkeypatch 替换业务函数**：pipeline 集成测试通过 monkeypatch 替换 download_video / transcode_video / probe_dimensions，业务代码无任何测试基础设施侵入。
4. **asyncio.Event 时序控制**：pipeline 中断测试用 asyncio.Event 精确控制 mock 函数的执行时序，避免 race condition。

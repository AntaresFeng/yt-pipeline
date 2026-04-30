# 迁移文档：从 new (threading) 到 yt-pipeline (asyncio)

## 总览

将 `C:\Users\admin\Desktop\new` 中 threading 实现的业务逻辑迁移到当前 asyncio 骨架中，替换所有 mock 为真实实现。

## 迁移原则

- **异步包装**：所有阻塞调用（yt-dlp、ffprobe、ffmpeg）通过 `asyncio.to_thread` 或 `asyncio.create_subprocess_exec` 异步化
- **保持框架**：不改变现有的三队列架构、状态机、优雅退出、断点续跑机制
- **配置集中**：仅运行时可变参数加入 `PipelineConfig`，固定业务规则放入 `constants.py`
- **解除 mock 耦合**：workers.py 不再 import mocks，改为 import 真实模块

---

## 1. config.py — 精简，移除 mock 配置

PipelineConfig 只保留**运行时可能变化的参数**。ffmpeg 参数（CRF、preset、音频码率）、分辨率阈值、处理尺寸等是固定业务规则，放入 `constants.py`。

**删除的字段**（mock 专用）：
- `download_delay`、`probe_delay`、`cover_process_delay`
- `mock_ffmpeg_frames`、`mock_ffmpeg_frame_delay`、`mock_ffmpeg_cleanup_delay`
- `default_urls`

**保留的字段**：
- `download_concurrency` — 运行时调优
- `state_file` — 路径可变

`fast()` 方法移除（真实组件无"缩短延时"的概念）。测试通过 mock_ffmpeg.py 脚本控制速度。

### 新建 constants.py

从参考项目 `new/yt_dlp_pipeline/constants.py` 迁移，存放固定业务规则：

```python
# 视频处理阈值
MIN_SHORT_EDGE = 1080
MAX_SHORT_EDGE = 1600
RATIO_THRESHOLD = 2.0

# 输出尺寸
TARGET_4K_WIDTH = 3840
TARGET_4K_HEIGHT = 2160
TARGET_PAD_HEIGHT = 1600
TARGET_ASPECT_RATIO = 16 / 9

# 封面处理
THUMBNAIL_MIN_HEIGHT = 720

# 编码参数
FFMPEG_CRF = 18
FFMPEG_PRESET = "slow"
FFMPEG_AUDIO_BITRATE = "192k"

# 下载
MAX_TITLE_LENGTH = 180
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".flv", ".avi"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
```

---

## 2. task.py — Task 模型扩展

当前 Task 只有 `url`, `state`, `error`。需要增加：

```python
@dataclass
class Task:
    url: str
    state: str = "pending"
    error: str | None = None
    # 新增字段
    video_id: str | None = None           # yt-dlp 返回的 video id
    title: str | None = None              # 视频标题
    video_path: str | None = None         # 下载后的本地文件路径
    thumbnail_path: str | None = None     # 封面文件路径
    credits_path: str | None = None       # 来源文案路径
    strategy: str | None = None           # "upscale_4k" | "pad_1600" | None
    output_path: str | None = None        # 转码输出路径
    ffmpeg_command: list[str] | None = None  # 待执行的 ffmpeg 命令 (仅用于持久化展示)
    probe_result: dict | None = None      # probe 结果缓存 (width, height)
```

持久化 `progress.json` 需要更新字段白名单，仅序列化可恢复字段。`RESUME_RESET` 行为不变。

---

## 3. mocks.py → 拆分为真实模块

当前 `mocks.py` 包含 4 个 mock 函数，其子进程管理模式需提炼为通用模块，其余替换为真实实现。

### 3a. process.py (新建) — 通用异步子进程运行器

从 `mocks.py` 的 `mock_video_process` 提炼，提供两级接口：

**Level 1 — 简单命令**（ffprobe 探测、ffmpeg 封面处理）：
```python
async def run_command(cmd: list[str]) -> tuple[int, str, str]:
    """执行短命令，返回 (returncode, stdout, stderr)。无 shutdown 交互。"""
```
短命令无需 `CREATE_NEW_PROCESS_GROUP` 隔离，直接 `create_subprocess_exec` + `communicate()` 即可。

**Level 2 — 转码命令**（长时 ffmpeg，需优雅退出）：
```python
async def run_transcode(cmd: list[str], shutdown: ShutdownManager) -> None:
    """执行 ffmpeg 转码，shutdown 时通过 stdin 发 'q' 优雅退出。"""
```
这就是当前 `mock_video_process` 的逻辑，提炼为独立函数：
- `CREATE_NEW_PROCESS_GROUP` 隔离 Ctrl+C
- `asyncio.wait([proc.wait(), shutdown.event.wait()])` 竞速
- shutdown 触发时：`stdin.write(b"q\n")` → `communicate()` 排空
- 与 mock 版的两点差异：
  1. 真实 ffmpeg 收到 'q' 后返回 **0**（而非 42）
  2. 使用 `task.ffmpeg_command` 而非 mock 脚本路径

调用方（transcode_worker）用法：
```python
await run_transcode(task.ffmpeg_command, shutdown)
```

### 3b. download.py (新建) — 替换 `mock_download`

参考：`new/yt_dlp_pipeline/download.py` 的 `Downloader` 类 + `new/yt_dlp_pipeline/resources.py` 的 `generate_credits_text`。

```python
# yt_pipeline/download.py
async def download_video(task: Task, shutdown: ShutdownManager, cfg: PipelineConfig) -> None:
    """异步下载视频（yt-dlp 阻塞调用放入线程池）"""
    # 1. 调用 yt_dlp.YoutubeDL.extract_info(url, download=True)
    #    通过 asyncio.to_thread() 包装
    # 2. 解析返回的 info dict，提取 video_id, video_path, thumbnail_path
    # 3. 立即用 info 生成 credits 文案（channel/title/description 不跨阶段传递）
    # 4. 写入 task.video_id, task.video_path, task.thumbnail_path, task.credits_path
    # 5. 支持 shutdown.is_set 检测（在 to_thread 前后检查）
```

**关键差异**：参考项目的 `download_with_retry` 有交互式重试询问（`ask_yes_no`）。asyncio 版改为：
- 如果 `cfg.yt_dlp_retry` 为 True，非 KeyboardInterrupt 的异常记录到 task.error 并标记 failed（不阻塞流水线）
- 如需交互式重试，在 worker 层通过 CLI 回调实现

**credits 生成放在此模块**：`generate_credits_text(info, url, video_path)` 依赖 yt-dlp 返回的 `info` dict，该 dict 仅在下载阶段可用。生成结果写入 `task.credits_path`，避免在 Task 模型上增加 `channel`/`title`/`description` 等中间字段。

### 3c. probe.py (新建) — 替换 `mock_probe`

参考：`new/yt_dlp_pipeline/tools.py` 的 `VideoProbeService`。

```python
# yt_pipeline/probe.py
async def probe_dimensions(file_path: Path) -> ImageSpec:
    """异步 ffprobe 获取图片/视频尺寸"""

async def probe_video_dimensions(file_path: Path) -> VideoSpec:
    """异步 ffprobe 获取视频尺寸（返回 VideoSpec）"""
```

内部调用 `process.run_command(["ffprobe", "-hide_banner", "-v", "error", ...])` 获取 JSON 输出后解析，不涉及 shutdown 交互。

新增 `models.py` 中的 `ImageSpec` / `VideoSpec` 数据类（从参考项目迁移）。

### 3d. thumbnail.py (新建) — 替换 `mock_cover_process`

参考：`new/yt_dlp_pipeline/resources.py` 的 `ResourceService`。

```python
# yt_pipeline/thumbnail.py
async def process_thumbnail(thumbnail_path: Path) -> Path | None:
    """异步封面处理：裁剪 16:9 + 2x 超分"""
    # 两次 ffmpeg：crop → scale
    # 均通过 process.run_command() 执行，简单 returncode 检测
```

### 3e. transcoder.py (新建) — 替换 `mock_video_process`

transcode_worker 原本调用 `mock_video_process`，现在改为调用 `process.run_transcode`。此模块只需暴露一个薄封装：

```python
# yt_pipeline/transcoder.py
from yt_pipeline.process import run_transcode

async def transcode_video(task: Task, shutdown: ShutdownManager) -> None:
    """转码入口，将 task.ffmpeg_command 提交给通用子进程运行器。"""
    await run_transcode(task.ffmpeg_command, shutdown)
```

核心逻辑已在 `process.py` 中，此模块不重复实现。

### 3f. mocks.py 保留策略

`mocks.py` 整体删除。`mock_ffmpeg.py` 脚本保留（由测试框架使用）。

---

## 4. workers.py — 解除 mock 耦合

当前 workers 直接 import mock 函数：

```python
from yt_pipeline.mocks import mock_download, mock_probe, mock_cover_process, mock_video_process
```

改为：

```python
from yt_pipeline.download import download_video
from yt_pipeline.probe import probe_dimensions, probe_video_dimensions
from yt_pipeline.thumbnail import process_thumbnail
from yt_pipeline.transcoder import transcode_video
```

### 4a. download_worker 逻辑调整

```
当前 (mock): mock_download(task, shutdown, cfg)
改为 (真实): download_video(task, shutdown, cfg)
  → 填充 task.video_id, task.video_path, task.thumbnail_path
  → 立即生成 credits 文案 (generate_credits_text) ← info 仅在此可用，不跨阶段传递
  → task 只保留 credits_path，不保留 info 的中间字段 (channel/title/description)
```

设计决策：**credits 生成放在 download_worker**。
`generate_credits_text` 需要 yt-dlp 返回的 `info.channel`、`info.title`、`info.description`，这些字段仅用于生成 credits 文案，没有其他用途。如果延后到 assessment 阶段，就需要在 Task 上新增 3 个持久化字段来传递信息——不必要的耦合。下载完立即生成，info 作用域不超出 download_worker。

封面处理（`process_thumbnail_if_needed`）不同——它依赖 ffprobe 探测封面尺寸，和 assessment 阶段的视频探测共享 ffprobe 能力，因此放入 assessment_worker。

### 4b. assessment_worker 逻辑调整

```
当前 (mock): 
  1. mock_probe(task, "cover") → 决定是否 mock_cover_process
  2. mock_probe(task, "video") → 决定是否转入 transcode

改为 (真实):
  1. 如果 task.thumbnail_path 存在 → probe_dimensions(thumbnail_path)
     → 决定是否 process_thumbnail (替换封面)
  2. ffprobe_dimensions(video_path) → VideoSpec
  3. StrategyEngine.decide_video_strategy(spec) → (strategy, reason)
  4. 如果 strategy != "skip" → StrategyEngine.build_video_task(video_path, strategy) → 填充 task.ffmpeg_command
  5. 入队 transcode_queue
```

参考 `new/yt_dlp_pipeline/strategy.py` 的阈值逻辑，将其迁移到 `yt_pipeline/strategy.py`。

### 4c. transcode_worker 逻辑调整

```
当前 (mock): mock_video_process(task, shutdown, cfg)
改为 (真实): transcode_video(task, shutdown, cfg)
  → 使用 task.ffmpeg_command 中的命令
  → 其他子进程管理逻辑不变
```

### 4d. 新增 models.py

从参考项目迁移 `ImageSpec` 和 `VideoSpec` 数据类（纯数据类，无外部依赖）：

```python
@dataclass
class ImageSpec:
    width: int
    height: int

@dataclass  
class VideoSpec:
    width: int
    height: int
    # + is_horizontal, short_edge, long_edge, ratio
```

---

## 5. pipeline.py — 编排器调整

核心架构不变。`run_pipeline()` 保持三队列模型：

```
pending_queue → download_workers(×N) → assessment_queue → assessment_worker → transcode_queue → transcode_worker
```

小调整：
- 从 `pending_queue` 取任务时检查 `shutdown.is_set`（已实现）
- download_worker 完成后，task 已含 video_path、thumbnail_path 等字段
- 无需改变 `_join_or_shutdown` / `_drain_queue` 逻辑

---

## 6. URL 收集 — 集成 URLCollector

参考 `new/yt_dlp_pipeline/url_collector.py` 和 `clipboard.py`。

当前 CLI 支持 `--urls` 传参和默认 URL。需要改为真实 URL 收集：

1. **CLI 参数**：保留 `--urls`，此外支持传入文件路径（从文件读取 URL）
2. **交互模式**：无参数时进入交互模式（参考 `URLCollector._from_input()`）
3. **剪贴板监控**：迁移 `ClipboardMonitor` 为 asyncio 兼容版本
4. **URL 过滤**：保留 `_YT_ID_RE` 正则 (匹配 `^[A-Za-z0-9_-]{11}$`)

**注意**：URL 收集是同步的（等待用户输入），在 `run_pipeline` 之前完成，不需要异步化。`ClipboardMonitor` 的 `time.sleep(0.5)` 轮询可以保留或用 `asyncio.sleep` 替代。

新增文件 `yt_pipeline/url_collector.py`。

---

## 7. 新建文件清单

| 新文件 | 来源 | 说明 | 状态 |
|--------|------|------|:--:|
| `yt_pipeline/process.py` | 当前 mocks.py mock_video_process | 通用异步子进程运行器 | ✅ |
| `yt_pipeline/constants.py` | new/constants.py | 固定业务常量 | ✅ |
| `yt_pipeline/models.py` | new/models.py | ImageSpec + VideoSpec | ✅ |
| `yt_pipeline/strategy.py` | new/strategy.py | 策略引擎 | ✅ |
| `yt_pipeline/download.py` | new/download.py + resources.py | 异步 yt-dlp 下载 + credits | ✅ |
| `yt_pipeline/probe.py` | new/tools.py | 异步 ffprobe | ✅ |
| `yt_pipeline/thumbnail.py` | new/resources.py | 封面处理 | ✅ |
| `yt_pipeline/transcoder.py` | 当前 mocks.py | 转码入口（调用 process.py） | ✅ |
| `yt_pipeline/url_collector.py` | new/url_collector.py + clipboard.py | URL 收集 | — |

## 8. 需修改的现有文件

| 文件 | 修改内容 | 状态 |
|------|----------|:--:|
| `yt_pipeline/task.py` | 扩展 Task 字段 | ✅ |
| `yt_pipeline/config.py` | 移除 mock 参数，精简 | ✅ |
| `yt_pipeline/workers.py` | 替换 mock import，真实实现 + dry_run | ✅ |
| `yt_pipeline/persistence.py` | 更新序列化字段白名单 | ✅ |
| `yt_pipeline/cli.py` | 集成 URLCollector，--dry-run/--file | ✅ |
| `yt_pipeline/pipeline.py` | 无需改动 | — |
| `yt_pipeline/__init__.py` | 无需改动 | — |
| `tests/conftest.py` | 添加 make_test_image/video，移除 fast_cfg | ✅ |

## 9. 新增辅助脚本

| 文件 | 说明 | 状态 |
|------|------|:--:|
| `scripts/generate_test_media.py` | ffmpeg lavfi 生成测试用图片/视频 | ✅ |
| `scripts/mock_ffmpeg.py` | 测试用 ffmpeg 替代（保留） | ✅ |

## 10. 已删除的文件

| 文件 | 原因 |
|------|------|
| `yt_pipeline/mocks.py` | 拆分为真实模块 | ✅ |

## 11. 测试概览

**52 测试全部通过**，覆盖：

| 测试文件 | 用例数 | 说明 |
|----------|--------|------|
| `tests/test_models.py` | 7 | ImageSpec/VideoSpec 属性 |
| `tests/test_strategy.py` | 15 | 策略决策 + 命令构建 |
| `tests/test_process.py` | 5 | 异步子进程运行器 |
| `tests/test_probe.py` | 3 | ffprobe 探测 |
| `tests/test_thumbnail.py` | 5 | 封面查找 + 裁剪/超分 |
| `tests/test_download.py` | 6 | credits 生成 + 路径解析 |
| `tests/test_transcoder.py` | 3 | 转码薄层 + shutdown |
| `tests/test_signals.py` | 1 | CTRL_BREAK_EVENT 信号链路 |
| `tests/test_pipeline.py` | 7 | dry_run 集成测试：中断 + 恢复 |

## 12. 实施顺序 — 全部完成 ✅

- [x] 1. constants.py — 固定业务常量
- [x] 2. models.py — ImageSpec / VideoSpec
- [x] 3. task.py — 扩展 Task 字段
- [x] 4. process.py — 通用子进程运行器
- [x] 5. strategy.py — 策略引擎
- [x] 6. config.py — 移除 mock 字段，精简
- [x] 7. probe.py — 异步 ffprobe
- [x] 8. thumbnail.py — 封面处理
- [x] 9. download.py — 异步 yt-dlp + credits
- [x] 10. transcoder.py — 转码入口
- [x] 11. url_collector.py — URL 收集
- [x] 12. workers.py — 真实实现 + dry_run
- [x] 13. persistence.py — 扩展序列化字段
- [x] 14. cli.py — --dry-run/--file，集成 URL 收集
- [x] 15. 删除 mocks.py
- [x] 16. 测试更新

> 迁移完成：9 个新建模块 + 5 个修改文件 + 1 个删除 + 9 个测试文件，52 测试通过。

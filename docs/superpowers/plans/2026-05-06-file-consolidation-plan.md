# File Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate 14 source files into 11 by absorbing worker-specific logic into the respective worker files, eliminating process.py, strategy.py, and thumbnail.py.

**Architecture:** Each pipeline stage (download → assessment → transcode) owns its complete logic in one file. Only cross-worker utilities (model, constants, persistence, error handling, orchestrator, CLI) remain as separate files.

**Tech Stack:** Python asyncio, no new dependencies.

---

### Task 1: persistence.py — persist ffmpeg_command

**Files:**
- Modify: `yt_pipeline/persistence.py:11-21`

- [ ] **Step 1: Add `ffmpeg_command` to `_SERIALIZED_FIELDS`**

```python
# yt_pipeline/persistence.py, line 11-21
_SERIALIZED_FIELDS = [
    "url",
    "state",
    "error",
    "video_id",
    "video_path",
    "thumbnail_path",
    "credits_path",
    "strategy",
    "output_path",
    "ffmpeg_command",
]
```

- [ ] **Step 2: Commit**

```bash
git add yt_pipeline/persistence.py
git commit -m "feat: persist ffmpeg_command in progress.json for cleaner resume"
```

---

### Task 2: utils.py — trim to handle_worker_error only

**Files:**
- Modify: `yt_pipeline/utils.py`

- [ ] **Step 1: Remove `_noop` and `find_media_file` from utils.py**

Replace the entire file content:

```python
"""通用工具：错误处理。"""

from __future__ import annotations

import logging
from pathlib import Path

from yt_pipeline.model import Task, States
from yt_pipeline.persistence import save_all_progress

logger = logging.getLogger("pipeline.utils")


def handle_worker_error(
    task: Task, error: Exception, tasks: list[Task], state_file: Path
) -> None:
    """异常处理：标记 FAILED + 持久化 + 日志。"""
    task.state = States.FAILED
    task.error = str(error)
    save_all_progress(tasks, state_file)
    logger.error("[%s] failed: %s", task.url, error)
```

- [ ] **Step 2: Commit**

```bash
git add yt_pipeline/utils.py
git commit -m "refactor: trim utils.py to only handle_worker_error"
```

---

### Task 3: download_worker.py — absorb find_thumbnail + find_media_file

**Files:**
- Modify: `yt_pipeline/download_worker.py`

- [ ] **Step 1: Remove external imports for thumbnail and find_media_file**

In `download_worker.py`, remove lines 13 and 14:
```python
from yt_pipeline.thumbnail import find_thumbnail
from yt_pipeline.utils import handle_worker_error, find_media_file
```

Replace with:
```python
from yt_pipeline.utils import handle_worker_error
```

- [ ] **Step 2: Add `find_media_file` function (from utils.py) after the logger line**

After `logger = logging.getLogger("pipeline.download_worker")`, add:

```python
def find_media_file(video_id: str, exts: set[str]) -> Path | None:
    """按 video_id glob 查找媒体文件，按扩展名过滤。"""
    candidates = [
        p
        for p in Path.cwd().glob(f"*{video_id}*")
        if p.is_file() and p.suffix.lower() in exts
    ]
    return candidates[0] if candidates else None
```

- [ ] **Step 3: Add `find_thumbnail` function (from thumbnail.py) after `find_media_file`**

```python
def find_thumbnail(video_path: Path, video_id: str) -> Path | None:
    """根据 video_path 同名前缀 + video_id glob 查找封面文件。"""
    from yt_pipeline.constants import IMAGE_EXTS

    candidates: list[Path] = []

    # 同视频文件名、不同图片扩展名
    for ext in IMAGE_EXTS:
        p = video_path.with_suffix(ext)
        if p.exists():
            candidates.append(p)

    # 按 video_id glob
    if video_id:
        found = find_media_file(video_id, IMAGE_EXTS)
        if found:
            candidates.append(found)

    if not candidates:
        return None

    uniq = list({c.resolve(): c for c in candidates}.values())
    uniq.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return uniq[0]
```

- [ ] **Step 4: Commit**

```bash
git add yt_pipeline/download_worker.py
git commit -m "refactor: absorb find_thumbnail and find_media_file into download_worker"
```

---

### Task 4: transcode_worker.py — absorb run_transcode

**Files:**
- Modify: `yt_pipeline/transcode_worker.py`

- [ ] **Step 1: Remove import from process.py**

In `transcode_worker.py`, remove line 10:
```python
from yt_pipeline.process import run_transcode
```

- [ ] **Step 2: Add `run_transcode` function after the logger line**

After `logger = logging.getLogger("pipeline.transcode_worker")`, add:

```python
import subprocess
import sys


async def run_transcode(
    cmd: list[str],
    shutdown: "ShutdownManager",
    *,
    label: str = "",
) -> None:
    """执行 ffmpeg 转码。shutdown 触发时通过 stdin 发 'q' 优雅退出。

    Raises:
        asyncio.CancelledError: shutdown 触发，转码中断
        RuntimeError: ffmpeg 异常退出 (returncode != 0)
    """
    import asyncio

    prefix = f"[{label}] " if label else ""
    logger.info("%sStarting ffmpeg...", prefix)

    popen_kwargs: dict = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **popen_kwargs,
    )

    wait_proc = asyncio.create_task(proc.wait())
    shutdown_task = asyncio.create_task(shutdown.event.wait())
    done, pending = await asyncio.wait(
        [wait_proc, shutdown_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    try:
        if shutdown_task in done:
            logger.info("%sSending 'q' to ffmpeg for graceful exit...", prefix)
            if proc.stdin and not proc.stdin.is_closing():
                try:
                    proc.stdin.write(b"q\n")
                    await proc.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    proc.stdin.close()
            await proc.communicate()
            if proc.returncode == 0:
                logger.info("%sffmpeg exited gracefully (sent 'q')", prefix)
            else:
                logger.warning(
                    "%sffmpeg exited with code %d after 'q'", prefix, proc.returncode
                )
            raise asyncio.CancelledError("Shutdown during transcode")

        # 子进程自行退出
        _stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            msg = f"ffmpeg exited with code {proc.returncode}"
            if stderr:
                msg += f": {stderr.decode()[:200]}"
            logger.warning("%s%s", prefix, msg)
            raise RuntimeError(msg)
        logger.info("%sffmpeg finished", prefix)
    finally:
        for p in pending:
            p.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        await asyncio.sleep(0)
```

Also update the top-level imports: add `import subprocess` and `import sys` to the import block. The final import block should be:

```python
"""转码 worker：串行 ffmpeg 转码 + 薄封装入口。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from yt_pipeline.model import Task, States
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.utils import handle_worker_error
```

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/transcode_worker.py
git commit -m "refactor: absorb run_transcode into transcode_worker"
```

---

### Task 5: assessment_worker.py — absorb probe, strategy, thumbnail processing

**Files:**
- Modify: `yt_pipeline/assessment_worker.py`

- [ ] **Step 1: Replace imports**

Remove these lines:
```python
from yt_pipeline.process import probe_dimensions, ffprobe_dimensions
from yt_pipeline.thumbnail import process_thumbnail
from yt_pipeline.strategy import decide_video_strategy, build_ffmpeg_command
from yt_pipeline.utils import handle_worker_error, _noop
```

Replace with:
```python
from yt_pipeline.utils import handle_worker_error
```

Add to top-level imports (alongside existing `import asyncio`, `import logging`):
```python
import json
import subprocess
```

- [ ] **Step 2: Add `_noop` coroutine (from utils.py) before `assessment_worker`**

```python
async def _noop() -> None:
    """占位协程，用于 asyncio.gather 中不需要执行的分支。"""
```

- [ ] **Step 3: Add `run_command` (from process.py) after `_noop`**

```python
async def run_command(cmd: list[str]) -> tuple[int, str, str]:
    """执行短命令，返回 (returncode, stdout, stderr)。"""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return (
        proc.returncode or 0,
        stdout.decode() if stdout else "",
        stderr.decode() if stderr else "",
    )
```

- [ ] **Step 4: Add `probe_dimensions` and `ffprobe_dimensions` (from process.py) after `run_command`**

```python
async def probe_dimensions(file_path: Path) -> "ImageSpec":
    """ffprobe 获取图片/视频尺寸。

    Raises:
        RuntimeError: 无法读取尺寸
    """
    from yt_pipeline.model import ImageSpec

    rc, stdout, stderr = await run_command([
        "ffprobe", "-hide_banner",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(file_path),
    ])

    if rc != 0:
        raise RuntimeError(f"ffprobe 失败: {stderr[:200]}")

    data = json.loads(stdout)
    streams = data.get("streams") or []

    if streams:
        stream = streams[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
    else:
        rc2, stdout2, stderr2 = await run_command([
            "ffprobe", "-hide_banner",
            "-v", "error",
            "-show_entries", "format=width,height",
            "-of", "json",
            str(file_path),
        ])
        if rc2 != 0:
            raise RuntimeError(f"ffprobe format 探测失败: {stderr2[:200]}")
        data2 = json.loads(stdout2)
        fmt = data2.get("format") or {}
        width = int(fmt.get("width") or 0)
        height = int(fmt.get("height") or 0)

    if width <= 0 or height <= 0:
        raise RuntimeError(f"无法读取尺寸: {file_path}")
    return ImageSpec(width=width, height=height)


async def ffprobe_dimensions(file_path: Path) -> "VideoSpec":
    """ffprobe 获取视频尺寸，返回 VideoSpec。"""
    from yt_pipeline.model import VideoSpec

    spec = await probe_dimensions(file_path)
    return VideoSpec(width=spec.width, height=spec.height)
```

- [ ] **Step 5: Add `process_thumbnail` (from thumbnail.py) after `ffprobe_dimensions`**

```python
async def process_thumbnail(thumbnail_path: Path) -> list[Path]:
    """如果封面高度 < THUMBNAIL_MIN_HEIGHT，裁剪 16:9 后 2x 超分。

    返回生成的文件列表。跳过时返回空列表。
    """
    from yt_pipeline.constants import TARGET_ASPECT_RATIO, THUMBNAIL_MIN_HEIGHT

    spec = await probe_dimensions(thumbnail_path)
    if spec.height >= THUMBNAIL_MIN_HEIGHT:
        logger.info(
            "封面高度 %dpx >= %d，跳过封面处理。",
            spec.height,
            THUMBNAIL_MIN_HEIGHT,
        )
        return []

    # Python 端计算 16:9 裁剪尺寸，避免 ffmpeg if() 表达式在 Windows 下解析异常
    if spec.width / spec.height >= TARGET_ASPECT_RATIO:
        crop_w = spec.height * 16 // 9
        crop_h = spec.height
    else:
        crop_w = spec.width
        crop_h = spec.width * 9 // 16

    cropped = thumbnail_path.with_name(
        f"{thumbnail_path.stem}_169{thumbnail_path.suffix}"
    )
    upscaled = thumbnail_path.with_name(
        f"{thumbnail_path.stem}_169_2x{thumbnail_path.suffix}"
    )

    # fmt: off
    rc, _, stderr = await run_command([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(thumbnail_path),
        "-vf", f"crop={crop_w}:{crop_h}",
        str(cropped),
    ])
    # fmt: on
    if rc != 0:
        raise RuntimeError(f"封面裁剪失败: {stderr[:200]}")

    # fmt: off
    rc2, _, stderr2 = await run_command([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(cropped),
        "-vf", "scale=iw*2:ih*2:flags=lanczos",
        str(upscaled),
    ])
    # fmt: on
    if rc2 != 0:
        raise RuntimeError(f"封面超分失败: {stderr2[:200]}")

    cropped.unlink(missing_ok=True)
    logger.info("已生成封面文件: %s", upscaled.name)
    return [upscaled]
```

- [ ] **Step 6: Add `decide_video_strategy` and `build_ffmpeg_command` (from strategy.py) after `process_thumbnail`**

```python
def decide_video_strategy(spec: "VideoSpec") -> tuple[str, str | None]:
    """根据视频尺寸决定处理策略。

    Returns:
        (strategy, reason) — strategy 为 "skip" | "upscale_4k" | "pad_1600"，
        非 skip 时 reason 为 None。
    """
    from yt_pipeline.constants import (
        STRATEGY_SKIP, STRATEGY_UPSCALE_4K, STRATEGY_PAD_1600,
        MIN_SHORT_EDGE, MAX_SHORT_EDGE, RATIO_THRESHOLD,
    )
    from yt_pipeline.model import VideoSpec

    if not spec.is_horizontal:
        return STRATEGY_SKIP, "竖屏视频，按规则跳过"

    short_edge = spec.short_edge
    if short_edge <= MIN_SHORT_EDGE:
        return STRATEGY_SKIP, f"短边 {short_edge} <= {MIN_SHORT_EDGE}，按规则跳过"
    if short_edge >= MAX_SHORT_EDGE:
        return STRATEGY_SKIP, f"短边 {short_edge} >= {MAX_SHORT_EDGE}，按规则跳过"

    if spec.ratio < RATIO_THRESHOLD:
        return STRATEGY_UPSCALE_4K, None
    return STRATEGY_PAD_1600, None


def build_ffmpeg_command(video_path: Path, strategy: str) -> tuple[list[str], Path]:
    """根据策略构建 ffmpeg 命令和输出路径。

    Returns:
        (command, output_path)
    """
    from yt_pipeline.constants import (
        STRATEGY_UPSCALE_4K, STRATEGY_PAD_1600,
        TARGET_4K_WIDTH, TARGET_4K_HEIGHT, TARGET_PAD_HEIGHT,
        FFMPEG_CRF, FFMPEG_PRESET, FFMPEG_AUDIO_BITRATE,
    )

    if strategy == STRATEGY_UPSCALE_4K:
        output = video_path.with_name(f"{video_path.stem}_processed_4k.mp4")
        vf = f"scale={TARGET_4K_WIDTH}:{TARGET_4K_HEIGHT}:flags=lanczos"
    elif strategy == STRATEGY_PAD_1600:
        output = video_path.with_name(f"{video_path.stem}_processed_pad1600.mp4")
        vf = (
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2,"
            f"pad=iw:{TARGET_PAD_HEIGHT}:0:({TARGET_PAD_HEIGHT}-ih)/2:black"
        )
    else:
        raise ValueError(f"未知策略: {strategy}")

    # fmt: off
    command = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video_path),
        "-vf", vf,
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-crf", str(FFMPEG_CRF),
        "-preset", FFMPEG_PRESET,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", FFMPEG_AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(output),
    ]
    # fmt: on

    return command, output
```

- [ ] **Step 7: Commit**

```bash
git add yt_pipeline/assessment_worker.py
git commit -m "refactor: absorb probe, strategy, and thumbnail processing into assessment_worker"
```

---

### Task 6: pipeline.py — remove build_ffmpeg_command dependency and resume reconstruction

**Files:**
- Modify: `yt_pipeline/pipeline.py`

- [ ] **Step 1: Remove the `build_ffmpeg_command` import**

Remove line 13:
```python
from yt_pipeline.strategy import build_ffmpeg_command
```

- [ ] **Step 2: Simplify resume logic in `run_pipeline`**

In `run_pipeline`, lines 72-76, replace:
```python
        elif task.state == States.PROCESSING_VIDEO:
            if task.ffmpeg_command is None and task.strategy and task.video_path:
                cmd, _ = build_ffmpeg_command(Path(task.video_path), task.strategy)
                task.ffmpeg_command = cmd
            await transcode_queue.put(task)
```

With:
```python
        elif task.state == States.PROCESSING_VIDEO:
            await transcode_queue.put(task)
```

- [ ] **Step 3: Commit**

```bash
git add yt_pipeline/pipeline.py
git commit -m "refactor: remove build_ffmpeg_command from pipeline, rely on persisted ffmpeg_command"
```

---

### Task 7: Delete old files

**Files:**
- Delete: `yt_pipeline/process.py`
- Delete: `yt_pipeline/strategy.py`
- Delete: `yt_pipeline/thumbnail.py`

- [ ] **Step 1: Delete the three files**

```bash
git rm yt_pipeline/process.py yt_pipeline/strategy.py yt_pipeline/thumbnail.py
```

- [ ] **Step 2: Commit**

```bash
git commit -m "refactor: remove process.py, strategy.py, thumbnail.py — absorbed into worker files"
```

---

### Task 8: Update test imports

**Files:**
- Modify: `tests/test_process.py`
- Modify: `tests/test_probe.py`
- Modify: `tests/test_strategy.py`
- Modify: `tests/test_thumbnail.py`

- [ ] **Step 1: Update `tests/test_process.py`**

Replace line 9:
```python
from yt_pipeline.process import run_command, run_transcode
```
With:
```python
from yt_pipeline.assessment_worker import run_command
from yt_pipeline.transcode_worker import run_transcode
```

- [ ] **Step 2: Update `tests/test_probe.py`**

Replace line 8:
```python
from yt_pipeline.process import probe_dimensions, ffprobe_dimensions
```
With:
```python
from yt_pipeline.assessment_worker import probe_dimensions, ffprobe_dimensions
```

- [ ] **Step 3: Update `tests/test_strategy.py`**

Replace line 8:
```python
from yt_pipeline.strategy import decide_video_strategy, build_ffmpeg_command
```
With:
```python
from yt_pipeline.assessment_worker import decide_video_strategy, build_ffmpeg_command
```

- [ ] **Step 4: Update `tests/test_thumbnail.py`**

Replace line 8:
```python
from yt_pipeline.thumbnail import find_thumbnail, process_thumbnail
```
With:
```python
from yt_pipeline.download_worker import find_thumbnail
from yt_pipeline.assessment_worker import process_thumbnail
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_process.py tests/test_probe.py tests/test_strategy.py tests/test_thumbnail.py
git commit -m "test: update import paths after file consolidation"
```

---

### Task 9: Verify with full test suite

- [ ] **Step 1: Run all tests**

```bash
pytest tests/ -v
```

Expected: all tests pass (tests requiring ffmpeg/ffprobe may skip if not installed).

- [ ] **Step 2: Verify module importability**

```bash
python -c "from yt_pipeline import Task, States, ShutdownManager, run_pipeline; print('OK')"
```

Expected: `OK`

# CLAUDE.md

**YOUR CODE WILL BE REVIEWED BY GPT-CODEX AND GEMINI**

## Project overview

A video batch-processing pipeline skeleton demonstrating graceful shutdown and interrupt-resume patterns using Python asyncio. No third-party dependencies — stdlib only.

## Commands

```bash

# Run the concurrent pipeline (4 download workers + 1 transcode worker)
python main_concurrency.py

# Test graceful shutdown by launching + interrupting after 5s
python run_main_and_interrupt.py
```

No build step, linter, or test runner is configured.

## Architecture

**`main_concurrency.py`** — Overlapping download and transcode via `asyncio.Queue`:
- `pending_queue` feeds N download workers (default 4, gated by `Semaphore`)
- Completed downloads flow into `transcode_queue`, consumed by a single serial transcode worker
- On resume, `downloading` tasks reset to `pending`; mid-transcode tasks reset to `downloaded`

Both share the same core patterns:

- **Graceful shutdown**: `shutdown_event` (`asyncio.Event`) is set on SIGINT/Ctrl+C. Long-running operations await it with `asyncio.wait_for(..., timeout=N)` to check between steps. The mock ffmpeg subprocess (`mock_script.py`) reads stdin for `'q'` to simulate ffmpeg's graceful-exit protocol.
- **Checkpoint/resume**: `progress.json` tracks every task's state machine. Writes use atomic rename (write `.tmp`, then `replace`). The file is deleted only when all tasks reach `done`/`failed`.
- **Windows compatibility**: `main.py` uses `CTRL_BREAK_EVENT` (not SIGINT) for subprocess signaling. `mock_script.py` uses `msvcrt.kbhit` for non-blocking key detection — this is Windows-only.

**Task state machine**: `pending` → `downloading` → `downloaded` → `probing_cover` → `processing_cover` → `probing_video` → `processing_video` → `done` (or `failed` at any step). The sequential version skips the separate `downloaded` state since download flows directly into processing.

# 文件结构收敛设计

## 目标

按 pipeline 流程阶段组织代码，将 worker 相关逻辑收敛到各自的 worker 文件中，删除碎片化的小文件。

## 收敛后结构（11 个源文件）

### 通用层（横跨多个 worker）

| 文件 | 内容 |
|------|------|
| `model.py` | Task, States, VideoSpec, ImageSpec, RESUME_RESET, TERMINAL_STATES |
| `constants.py` | 所有业务常量 |
| `persistence.py` | load_progress, save_all_progress（`ffmpeg_command` 加入序列化字段） |
| `utils.py` | 仅保留 handle_worker_error |
| `pipeline.py` | ShutdownManager, run_pipeline（删除 build_ffmpeg_command 导入和恢复重建逻辑） |
| `cli.py` | CLI 入口 |
| `url_collector.py` | URL 收集 |

### Worker 文件（每个涵盖其 pipeline 阶段全部逻辑）

| 文件 | 吸收的内容 |
|------|-----------|
| `download_worker.py` | + find_thumbnail（from thumbnail.py）+ find_media_file（from utils.py） |
| `assessment_worker.py` | + probe_dimensions, ffprobe_dimensions, run_command（from process.py）+ process_thumbnail（from thumbnail.py）+ decide_video_strategy, build_ffmpeg_command（from strategy.py）+ _noop（from utils.py） |
| `transcode_worker.py` | + run_transcode（from process.py） |

### 删除

`process.py`, `strategy.py`, `thumbnail.py`

## 关键变更

### persistence.py — ffmpeg_command 持久化

`_SERIALIZED_FIELDS` 新增 `"ffmpeg_command"`，确保中断恢复时可直接读取命令，无需重建。

### pipeline.py — 简化恢复逻辑

恢复时不再调用 `build_ffmpeg_command`，因为 `ffmpeg_command` 已持久化：

```python
elif task.state == States.PROCESSING_VIDEO:
    await transcode_queue.put(task)
```

### 测试文件 import 路径更新

| 测试文件 | 旧 import | 新 import |
|----------|----------|----------|
| test_process.py | yt_pipeline.process | yt_pipeline.assessment_worker / yt_pipeline.transcode_worker |
| test_probe.py | yt_pipeline.process | yt_pipeline.assessment_worker |
| test_strategy.py | yt_pipeline.strategy | yt_pipeline.assessment_worker |
| test_thumbnail.py | yt_pipeline.thumbnail | yt_pipeline.download_worker / yt_pipeline.assessment_worker |

# 集成测试设计：Pipeline Worker 编排

## 目标

验证 yt-pipeline 的 worker 间编排逻辑：状态流转、队列协调、shutdown 协调、resume 恢复。mock 外部工具（yt-dlp、ffprobe、ffmpeg），业务逻辑全真实执行。

## 范围

### 在范围内

- 全链路状态流转（pending → done）
- 策略分支（upscale_4k / pad_1600 / skip）
- Shutdown 在 download / assessment / transcode 三个阶段的协调
- Resume 从中断状态恢复

### 不在范围内

- 下载并发数控制
- 多任务混合策略
- 封面处理失败降级
- url_collector / cli 交互逻辑

## Mock 策略

mock 最低外部边界，业务逻辑全真实：

| Mock 点 | 替换函数 | 返回值 |
|---------|---------|--------|
| 下载 | `download_worker._do_download` | 返回含 `id` + `requested_downloads` 的 info dict，同时在 cwd 创建视频+封面文件 |
| 探测/封面处理 | `assessment_worker.run_command` | 根据 cmd[0] 判断 ffprobe/ffmpeg，返回预设 (rc, stdout, stderr) |
| 转码 | `transcode_worker.run_transcode` | no-op 异步函数，记录调用参数；可切换为抛 `RuntimeError` |

## 测试文件结构

```
tests/
  integration/
    __init__.py
    conftest.py       # 共享 fixture
    test_pipeline_integration.py   # 9 个测试函数
```

## 核心 Fixture

### mock_download

替换 `_do_download`。自动在 tmp_path 创建视频文件（`.mp4`）和封面文件（`.png`），返回含路径的 info dict。

参数化：
- `video_id`: 默认 `"testvid"`
- `video_filename`: 默认 `"Test Video [testvid].mp4"`

### mock_subprocess

替换 `run_command`。根据 `cmd[0]` 返回预设结果：

- `"ffprobe"` → 返回配置好的 ffprobe JSON 输出；可切换为非零退出 `(1, "", "ffprobe error")` 触发 RuntimeError
- `"ffmpeg"` → 返回 `(0, "", "")`；可切换为非零退出 `(1, "", "ffmpeg error")` 触发 RuntimeError

通过 fixture 参数或全局 dict 按需切换返回值（如 1920x1081 / 1920x1080 / 3840x1081 / 非零退出）。

### mock_transcode

替换 `run_transcode` 为 no-op 异步函数，用 `call_args_list` 记录所有调用参数。

### pipeline_env

组合 fixture：tmp_path + chdir + ShutdownManager（不 attach 信号）+ state_file 路径。

## 测试用例

### 场景 1：全链路正常流转

#### test_full_pipeline_upscale

- 输入：1 个 pending task, ffprobe 返回 1920x1081
- 预期：state 经 pending→downloading→downloaded→probing_cover→probing_video→processing_video→done
- 断言：task.state == DONE, ffmpeg_command 包含 "scale=3840:2160", run_transcode 被调用

#### test_full_pipeline_pad

- 输入：1 个 pending task, ffprobe 返回 3840x1081
- 预期：state 经同样流转到达 done
- 断言：task.state == DONE, ffmpeg_command 包含 "pad=iw:1600", run_transcode 被调用

### 场景 2：skip 策略

#### test_skip_strategy

- 输入：1 个 pending task, ffprobe 返回 1920x1080
- 预期：state 经 pending→...→probing_video→done（不经 processing_video）
- 断言：task.state == DONE, ffmpeg_command 为 None, run_transcode 未被调用

### 场景 3：shutdown 协调

时序控制方式：在 mock 函数中 await 一个 `asyncio.Event`（gate），测试在 gate.wait() 之后触发 `shutdown.event.set()`。

#### test_shutdown_during_download

- 时序：mock_download 中 gate.wait() 后触发 shutdown
- 预期：download_video 抛出 CancelledError, 任务状态为 DOWNLOADING（非 FAILED）
- 断言：task.state == DOWNLOADING, progress.json 存在且包含此状态

#### test_shutdown_during_assessment

- 时序：mock_subprocess（probe）中 gate.wait() 后触发 shutdown
- 预期：assessment_worker 捕获 CancelledError 并回退状态为 DOWNLOADED
- 断言：task.state == DOWNLOADED

#### test_shutdown_during_transcode

- 时序：mock_transcode 中 gate.wait() 后触发 shutdown
- 预期：run_transcode 抛出 CancelledError, 任务保留 PROCESSING_VIDEO
- 断言：task.state == PROCESSING_VIDEO

### 场景 4：resume 恢复

#### test_resume_from_interrupted_state

- 预设：progress.json 含 1 个 downloading 状态的 task（url 已知）
- 执行：按 RESUME_RESET 回退到 pending → 重新跑 pipeline
- 预期：回退后任务重新走完全链路到达 DONE
- 断言：task.state == DONE, progress.json 最终被删除（全部任务终态）

### 场景 5：ffmpeg/ffprobe 异常退出（非 shutdown）

验证外部工具非零退出时任务被正确标记为 FAILED 并持久化。与场景 3（shutdown 协调）的区别：这里是业务异常，不是优雅退出。

#### test_assessment_ffprobe_failure

- 输入：1 个 pending task, mock_subprocess 的 ffprobe 返回 `(1, "", "ffprobe error")`
- 预期：`probe()` 抛出 RuntimeError，被 `assessment_worker` 的 except Exception 捕获，`handle_worker_error` 将任务标记为 FAILED
- 断言：task.state == FAILED, task.error 包含 "ffprobe", progress.json 存在且记录此失败状态

#### test_transcode_ffmpeg_failure

- 输入：1 个 pending task, ffprobe 正常返回 1920x1081（upscale 策略）, mock_transcode 抛出 `RuntimeError("ffmpeg exited with code 1")`
- 预期：`transcode_worker` 的 except Exception 捕获，`handle_worker_error` 将任务标记为 FAILED
- 断言：task.state == FAILED, task.error 包含 "ffmpeg", progress.json 存在且记录此失败状态

## Mock 数据规格

```python
FFPROBE_1081 = (0, '{"streams":[{"width":1920,"height":1081}]}', '')
FFPROBE_1080 = (0, '{"streams":[{"width":1920,"height":1080}]}', '')
FFPROBE_ULTRAWIDE = (0, '{"streams":[{"width":3840,"height":1081}]}', '')
FFPROBE_FAILURE = (1, '', 'ffprobe error: could not find stream info')
```

```python
def make_download_info(video_path: Path, video_id: str = "testvid") -> dict:
    return {
        "id": video_id,
        "channel": "TestChannel",
        "title": "Test Title",
        "description": "Test",
        "requested_downloads": [{"filepath": str(video_path)}],
    }
```

## 实现约束

- 使用 pytest-asyncio（`asyncio_mode = "auto"`，已在 pyproject.toml 配置）
- 不修改生产代码来适应测试
- mock 点仅限上述 3 处外部边界
- shutdown 测试中 gate Event 在 conftest 中创建，由测试函数控制触发时机

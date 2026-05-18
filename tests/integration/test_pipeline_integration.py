"""Pipeline 集成测试：验证 worker 间编排逻辑。"""

import asyncio

from yt_pipeline.model import Task, States, RESUME_RESET
from yt_pipeline.persistence import save_all_progress
from yt_pipeline.pipeline import run_pipeline


class TestFullPipeline:
    async def test_full_pipeline_upscale(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """1920x1081 -> upscale_4k 策略：全链路 pending->done，ffmpeg_command 含 scale=3840:2160。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert any("scale=3840:2160" in " ".join(cmd) for cmd in mock_transcode)
        assert len(mock_transcode) == 1

    async def test_full_pipeline_pad(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """3840x1081 -> pad_1600 策略：全链路 pending->done，ffmpeg_command 含 pad=iw:1600。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":3840,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert any("pad=iw:1600" in " ".join(cmd) for cmd in mock_transcode)
        assert len(mock_transcode) == 1


class TestSkipStrategy:
    async def test_skip_strategy(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """1920x1080 → skip：不经 processing_video，run_transcode 未被调用。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1080}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 0


class TestShutdown:
    async def test_shutdown_during_download(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """download 阶段触发 shutdown：任务保留 DOWNLOADING 状态。"""
        async def _gated_download(task, shutdown_mgr):
            gate.set()
            await shutdown_mgr.event.wait()
            raise asyncio.CancelledError("Shutdown during download")

        monkeypatch.setattr("yt_pipeline.download_worker.download_video", _gated_download)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.DOWNLOADING

    async def test_shutdown_during_assessment(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode,
        shutdown, gate, monkeypatch,
    ):
        """assessment 阶段触发 shutdown：任务保留 ASSESSING 状态。"""
        call_count = 0

        async def _gated_run_command(cmd):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                gate.set()
                await shutdown.event.wait()
                raise asyncio.CancelledError("Shutdown during assessment")
            return (0, '{"streams":[{"width":1920,"height":1081}]}', '')

        monkeypatch.setattr("yt_pipeline.assessment_worker.run_command", _gated_run_command)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.ASSESSING

    async def test_shutdown_during_transcode(
        self, pipeline_env, mock_download, mock_subprocess,
        shutdown, gate, monkeypatch,
    ):
        """transcode 阶段触发 shutdown：任务保留 PROCESSING_VIDEO 状态。"""
        async def _gated_transcode(cmd, shutdown_mgr, *, label=""):
            gate.set()
            await shutdown_mgr.event.wait()
            raise asyncio.CancelledError("Shutdown during transcode")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _gated_transcode)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"

        async def _run_and_shutdown():
            await gate.wait()
            shutdown.event.set()

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_run_and_shutdown())
            tg.create_task(run_pipeline([task], shutdown, state_file))

        assert task.state == States.PROCESSING_VIDEO


class TestResume:
    async def test_resume_from_interrupted_state(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """从 downloading 中断状态恢复：RESUME_RESET 回退到 pending → 重新走完全链路。"""
        task = Task(url="https://youtube.com/watch?v=testvid", state=States.DOWNLOADING)
        state_file = pipeline_env / "progress.json"
        save_all_progress([task], state_file)

        # 模拟 resume：按 RESUME_RESET 回退
        assert task.state in RESUME_RESET
        task.state = RESUME_RESET[task.state]  # DOWNLOADING → PENDING

        # 重新跑 pipeline
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 1
        assert not state_file.exists()  # 全部终态，progress.json 被删除


class TestFailure:
    async def test_assessment_ffprobe_failure(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """ffprobe 异常退出：任务标记为 FAILED，error 包含 ffprobe。"""
        mock_subprocess(
            ffprobe=(1, '', 'ffprobe error: could not find stream info'),
        )
        task = Task(url="https://youtube.com/watch?v=testvid")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.FAILED
        assert "ffprobe" in task.errors[-1]
        # FAILED 任务保留 progress.json 以便重试
        assert state_file.exists()

    async def test_transcode_ffmpeg_failure(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown, monkeypatch,
    ):
        """ffmpeg 异常退出：任务标记为 FAILED，error 包含 ffmpeg。"""
        async def _failing_transcode(cmd, shutdown_mgr, *, label=""):
            raise RuntimeError("ffmpeg exited with code 1")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _failing_transcode)

        task = Task(url="https://youtube.com/watch?v=testvid")
        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.FAILED
        assert "ffmpeg" in task.errors[-1]
        # FAILED 任务保留 progress.json 以便重试
        assert state_file.exists()


class TestResumeTerminalStates:
    async def test_resume_filters_done_tasks(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """resume 时 DONE 任务被过滤，不进入 pipeline。"""
        done_task = Task(url="https://youtube.com/watch?v=done1", state=States.DONE)
        pending_task = Task(url="https://youtube.com/watch?v=testvid", state=States.PENDING)

        state_file = pipeline_env / "progress.json"
        save_all_progress([done_task, pending_task], state_file)

        # 模拟 prepare_tasks 过滤：只保留非 DONE 任务
        tasks = [t for t in [done_task, pending_task] if t.state != States.DONE]
        await run_pipeline(tasks, shutdown, state_file)

        assert pending_task.state == States.DONE
        assert done_task.state == States.DONE
        assert len(mock_transcode) == 1  # 只有 pending_task 走了转码

    async def test_resume_failed_to_pending(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown
    ):
        """FAILED 任务经 RESUME_RESET 回退到 PENDING，重新走完全链路。"""
        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))
        task = Task(url="https://youtube.com/watch?v=testvid", state=States.FAILED, errors=["old error"])

        # 模拟 prepare_tasks 中的 RESUME_RESET 回退
        assert task.state in RESUME_RESET
        task.state = RESUME_RESET[task.state]  # FAILED → PENDING

        state_file = pipeline_env / "progress.json"
        await run_pipeline([task], shutdown, state_file)

        assert task.state == States.DONE
        assert len(mock_transcode) == 1
        assert "old error" in task.errors  # 旧错误保留

    async def test_mixed_done_failed_keeps_progress(
        self, pipeline_env, mock_download, mock_subprocess, mock_transcode, shutdown, monkeypatch,
    ):
        """混合 DONE+FAILED 场景：progress.json 保留（因为有 FAILED 任务）。"""
        async def _failing_transcode(cmd, shutdown_mgr, *, label=""):
            raise RuntimeError("ffmpeg exited with code 1")

        monkeypatch.setattr("yt_pipeline.transcode_worker.run_transcode", _failing_transcode)

        mock_subprocess(ffprobe=(0, '{"streams":[{"width":1920,"height":1081}]}', ''))

        # 创建一个 DONE 任务和一个会失败的任务
        done_task = Task(url="https://youtube.com/watch?v=done1", state=States.DONE)
        fail_task = Task(url="https://youtube.com/watch?v=fail1")

        state_file = pipeline_env / "progress.json"
        await run_pipeline([done_task, fail_task], shutdown, state_file)

        assert done_task.state == States.DONE
        assert fail_task.state == States.FAILED
        assert state_file.exists()  # FAILED 存在，progress.json 保留

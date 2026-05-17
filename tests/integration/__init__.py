"""集成测试：pipeline worker 编排逻辑。

测试范围：
- 完整 task 生命周期（pending → done）
- 状态机转换正确性
- 中断恢复行为
- 外部边界（yt-dlp/ffprobe/ffmpeg）被 mock
"""

"""优雅退出管理器：封装 asyncio.Event + 信号处理。"""

from __future__ import annotations

import asyncio
import logging
import signal

logger = logging.getLogger("pipeline.shutdown")


class ShutdownManager:
    """管理优雅退出流程。

    使用方式:
        shutdown = ShutdownManager()
        shutdown.attach(asyncio.get_running_loop())
        ...
        if shutdown.is_set:
            break
    """

    def __init__(self):
        self.event: asyncio.Event = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def attach(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定事件循环并注册信号处理器。

        Windows: asyncio 不支持 add_signal_handler，fallback 到 signal.signal()，
        回调在信号线程执行，通过 call_soon_threadsafe 切回事件循环。
        """
        self._loop = loop
        try:
            loop.add_signal_handler(signal.SIGINT, self._handle_signal)
            loop.add_signal_handler(signal.SIGBREAK, self._handle_signal)
        except NotImplementedError:
            signal.signal(signal.SIGINT, self._handle_signal)
            signal.signal(signal.SIGBREAK, self._handle_signal)

    def _handle_signal(self, signum: int | None = None, frame=None) -> None:
        logger.warning("Received Ctrl+C, requesting graceful shutdown...")
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self.event.set)

    @property
    def is_set(self) -> bool:
        return self.event.is_set()

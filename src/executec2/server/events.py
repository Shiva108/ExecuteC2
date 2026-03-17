"""Event system for ExecuteC2 — pre/post hook execution with priority and timeouts."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)

EVENT_TYPES = [
    "agent.new",
    "agent.checkin",
    "agent.activate",
    "agent.update",
    "agent.terminate",
    "agent.remove",
    "listener.start",
    "listener.stop",
    "task.create",
    "task.complete",
    "credential.add",
    "credential.edit",
    "credential.remove",
    "target.add",
    "target.edit",
    "target.remove",
    "tunnel.start",
    "tunnel.stop",
    "download.start",
    "download.complete",
    "client.connect",
    "client.disconnect",
]


class HookPhase(IntEnum):
    PRE = 0
    POST = 1


@dataclass
class EventHook:
    event_type: str
    phase: HookPhase
    priority: int        # Lower = higher priority
    callback: Callable   # async callable
    name: str = ""


class EventManager:
    def __init__(self, worker_count: int = 4, queue_size: int = 256):
        self._hooks: dict[str, list[EventHook]] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._workers: list[asyncio.Task] = []
        self._worker_count = worker_count

    async def start(self) -> None:
        """Start async worker tasks for post-hooks."""
        for _ in range(self._worker_count):
            self._workers.append(asyncio.create_task(self._worker()))

    async def stop(self) -> None:
        """Cancel all worker tasks."""
        for w in self._workers:
            w.cancel()
        self._workers.clear()

    def register(self, hook: EventHook) -> None:
        """Register a hook, maintaining priority sort."""
        hooks = self._hooks.setdefault(hook.event_type, [])
        hooks.append(hook)
        hooks.sort(key=lambda h: h.priority)

    async def emit(self, event_type: str, data: dict) -> bool:
        """Emit pre-hooks synchronously. Returns False if any hook cancels."""
        for hook in self._hooks.get(event_type, []):
            if hook.phase == HookPhase.PRE:
                try:
                    result = await asyncio.wait_for(
                        hook.callback(data), timeout=5.0,
                    )
                    if result is False:
                        return False
                except TimeoutError:
                    logger.warning("Pre-hook %s timed out for event %s", hook.name, event_type)
                except Exception:
                    logger.exception("Pre-hook %s raised for event %s", hook.name, event_type)
        return True

    async def emit_async(self, event_type: str, data: dict) -> None:
        """Queue post-hooks for async worker execution."""
        for hook in self._hooks.get(event_type, []):
            if hook.phase == HookPhase.POST:
                try:
                    self._queue.put_nowait((hook, data))
                except asyncio.QueueFull:
                    logger.warning("Post-hook queue full, dropping hook %s", hook.name)

    async def _worker(self) -> None:
        """Process post-hook jobs from queue."""
        while True:
            hook, data = await self._queue.get()
            try:
                await asyncio.wait_for(hook.callback(data), timeout=30.0)
            except TimeoutError:
                logger.warning("Post-hook %s timed out", hook.name)
            except asyncio.CancelledError:
                self._queue.task_done()
                return
            except Exception:
                logger.exception("Post-hook %s raised", hook.name)
            finally:
                self._queue.task_done()

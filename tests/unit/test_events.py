"""Unit tests for the EventManager."""

import asyncio

import pytest

from executec2.server.events import EventHook, EventManager, HookPhase


@pytest.fixture
async def event_manager():
    mgr = EventManager(worker_count=2)
    await mgr.start()
    yield mgr
    await mgr.stop()


# ---------------------------------------------------------------------------
# Pre-hook execution
# ---------------------------------------------------------------------------


async def test_pre_hook_called(event_manager):
    called = []

    async def handler(data):
        called.append(data)
        return True

    event_manager.register(EventHook(
        event_type="test.event",
        phase=HookPhase.PRE,
        priority=0,
        callback=handler,
        name="test-hook",
    ))

    result = await event_manager.emit("test.event", {"key": "value"})
    assert result is True
    assert called == [{"key": "value"}]


async def test_pre_hook_cancels_on_false(event_manager):
    async def cancelling_hook(data):
        return False

    event_manager.register(EventHook(
        event_type="agent.new",
        phase=HookPhase.PRE,
        priority=0,
        callback=cancelling_hook,
    ))

    result = await event_manager.emit("agent.new", {})
    assert result is False


async def test_pre_hook_allows_on_true(event_manager):
    async def allowing_hook(data):
        return True

    event_manager.register(EventHook(
        event_type="task.create",
        phase=HookPhase.PRE,
        priority=0,
        callback=allowing_hook,
    ))

    result = await event_manager.emit("task.create", {})
    assert result is True


async def test_no_hooks_returns_true(event_manager):
    result = await event_manager.emit("nonexistent.event", {})
    assert result is True


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


async def test_priority_ordering(event_manager):
    order = []

    async def hook_a(data):
        order.append("A")

    async def hook_b(data):
        order.append("B")

    async def hook_c(data):
        order.append("C")

    event_manager.register(EventHook("order.test", HookPhase.PRE, priority=10, callback=hook_c, name="C"))
    event_manager.register(EventHook("order.test", HookPhase.PRE, priority=1, callback=hook_a, name="A"))
    event_manager.register(EventHook("order.test", HookPhase.PRE, priority=5, callback=hook_b, name="B"))

    await event_manager.emit("order.test", {})
    assert order == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# Timeout behavior
# ---------------------------------------------------------------------------


async def test_pre_hook_timeout_continues(event_manager):
    """Slow pre-hook times out but execution continues (True returned)."""
    called_after = []

    async def slow_hook(data):
        await asyncio.sleep(10)  # Exceeds 5s timeout

    async def fast_hook(data):
        called_after.append("fast")

    event_manager.register(EventHook("timeout.test", HookPhase.PRE, priority=0, callback=slow_hook, name="slow"))
    event_manager.register(EventHook("timeout.test", HookPhase.PRE, priority=1, callback=fast_hook, name="fast"))

    result = await event_manager.emit("timeout.test", {})
    assert result is True
    assert "fast" in called_after


# ---------------------------------------------------------------------------
# Post-hook async execution
# ---------------------------------------------------------------------------


async def test_post_hook_executed_async(event_manager):
    executed = []
    done_event = asyncio.Event()

    async def post_handler(data):
        executed.append(data["value"])
        done_event.set()

    event_manager.register(EventHook(
        event_type="async.test",
        phase=HookPhase.POST,
        priority=0,
        callback=post_handler,
    ))

    await event_manager.emit_async("async.test", {"value": 42})
    await asyncio.wait_for(done_event.wait(), timeout=2.0)
    assert executed == [42]


async def test_post_hook_does_not_block_emit_async(event_manager):
    """emit_async returns immediately without waiting for hooks."""
    started = asyncio.Event()
    finished = asyncio.Event()

    async def slow_post_hook(data):
        started.set()
        await asyncio.sleep(0.5)
        finished.set()

    event_manager.register(EventHook("slow.post", HookPhase.POST, priority=0, callback=slow_post_hook))

    await event_manager.emit_async("slow.post", {})
    # emit_async should return before the hook finishes
    assert not finished.is_set()
    await asyncio.wait_for(finished.wait(), timeout=2.0)


# ---------------------------------------------------------------------------
# PRE vs POST separation
# ---------------------------------------------------------------------------


async def test_pre_hooks_dont_run_for_emit_async(event_manager):
    pre_called = []

    async def pre_hook(data):
        pre_called.append(True)
        return False  # Would cancel if it ran

    event_manager.register(EventHook("mixed.test", HookPhase.PRE, priority=0, callback=pre_hook))

    await event_manager.emit_async("mixed.test", {})
    await asyncio.sleep(0.1)
    assert pre_called == []


async def test_post_hooks_dont_run_for_emit(event_manager):
    post_called = []

    async def post_hook(data):
        post_called.append(True)

    event_manager.register(EventHook("emit.test", HookPhase.POST, priority=0, callback=post_hook))

    result = await event_manager.emit("emit.test", {})
    assert result is True
    await asyncio.sleep(0.1)
    assert post_called == []

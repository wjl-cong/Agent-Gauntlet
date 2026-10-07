"""ChaosEngine 工具注入测试（实现计划 Task 4 Step 1）—— langchain_core StructuredTool 造假工具。"""

import asyncio

import httpx
import pytest
from langchain_core.tools import StructuredTool

from gauntlet.chaos.faults import ChaosEngine, ToolTimeoutError, ToolUnavailableError
from gauntlet.models import FaultProfile, FaultType

# 注入异常与真实依赖故障同构（httpx 异常族），节点侧真实容错才能兜住
HTTP_500_EXC = httpx.HTTPStatusError
TIMEOUT_EXC = httpx.ReadTimeout


def make_tool(name: str) -> StructuredTool:
    return StructuredTool.from_function(func=lambda: "ok", name=name, description="fake tool")


def profiles_p50():
    return [FaultProfile(tool="t1", fault=FaultType.HTTP_500, probability=0.5)]


async def drive(engine: ChaosEngine) -> list[bool]:
    """连续调 t1 十次，记录每次是否命中注入。"""
    wrapped = engine.wrap_all([make_tool("t1")])
    hits = []
    for _ in range(10):
        try:
            await wrapped[0].ainvoke({})
            hits.append(False)
        except httpx.HTTPStatusError:
            hits.append(True)
    return hits


@pytest.mark.asyncio
async def test_http500_injected_and_recorded():
    eng = ChaosEngine([FaultProfile(tool="t1", fault=FaultType.HTTP_500, nth_call=1)], seed=42)
    wrapped = eng.wrap_all([make_tool("t1")])
    with pytest.raises(HTTP_500_EXC, match=r"\[chaos:t1\]"):
        await wrapped[0].ainvoke({})
    calls = eng.record_calls()
    assert calls[0].injected and not calls[0].ok


@pytest.mark.asyncio
async def test_timeout_raises_after_delay():
    eng = ChaosEngine(
        [FaultProfile(tool="t1", fault=FaultType.TIMEOUT, nth_call=1, delay_s=0.05)], seed=42
    )
    wrapped = eng.wrap_all([make_tool("t1")])
    with pytest.raises(TIMEOUT_EXC, match=r"\[chaos:t1\]"):
        await asyncio.wait_for(wrapped[0].ainvoke({}), timeout=2)
    assert eng.record_calls()[0].injected


@pytest.mark.asyncio
async def test_unmatched_tool_passthrough_and_unwrapped_object():
    eng = ChaosEngine([FaultProfile(tool="t1", fault=FaultType.HTTP_500, nth_call=1)], seed=42)
    other = make_tool("other")
    wrapped = eng.wrap_all([other])
    assert wrapped[0] is other  # 未命中策略的原样返回
    assert (await wrapped[0].ainvoke({})) == "ok"


@pytest.mark.asyncio
async def test_probability_not_hit_passes_through():
    eng = ChaosEngine([FaultProfile(tool="t1", fault=FaultType.HTTP_500, probability=0.0)], seed=42)
    assert (await eng.wrap_all([make_tool("t1")])[0].ainvoke({})) == "ok"  # probability=0 永不触发
    calls = eng.record_calls()
    assert calls[0].ok and not calls[0].injected


@pytest.mark.asyncio
async def test_nth_call_only_triggers_on_nth():
    eng = ChaosEngine([FaultProfile(tool="t1", fault=FaultType.HTTP_500, nth_call=3)], seed=42)
    wrapped = eng.wrap_all([make_tool("t1")])
    outcomes = []
    for _ in range(3):
        try:
            await wrapped[0].ainvoke({})
            outcomes.append("ok")
        except httpx.HTTPStatusError:
            outcomes.append("boom")
    assert outcomes == ["ok", "ok", "boom"]


@pytest.mark.asyncio
async def test_same_seed_same_sequence():  # Review Focus #4
    seq1 = await drive(ChaosEngine(profiles_p50(), seed=7))
    seq2 = await drive(ChaosEngine(profiles_p50(), seed=7))
    seq3 = await drive(ChaosEngine(profiles_p50(), seed=8))
    assert seq1 == seq2 and seq1 != seq3


@pytest.mark.asyncio
async def test_corrupt_data_placeholder_raises_not_implemented():
    eng = ChaosEngine([FaultProfile(tool="t1", fault=FaultType.CORRUPT_DATA, nth_call=1)], seed=42)
    wrapped = eng.wrap_all([make_tool("t1")])
    with pytest.raises(NotImplementedError):
        await wrapped[0].ainvoke({})


# ---------- wrap_callable（焰哨挂接入口：普通 sync/async 方法，非 LangChain 工具） ----------


@pytest.mark.asyncio
async def test_wrap_callable_async_hit_only_on_nth():
    async def afn(x):
        return x + 1

    eng = ChaosEngine([FaultProfile(tool="afn", fault=FaultType.HTTP_500, nth_call=2)], seed=1)
    wrapped = eng.wrap_callable("afn", afn)
    assert await wrapped(1) == 2
    with pytest.raises(HTTP_500_EXC, match=r"\[chaos:afn\]"):
        await wrapped(1)
    assert await wrapped(1) == 2  # 第 3 次恢复正常
    assert [c.ok for c in eng.record_calls()] == [True, False, True]


def test_wrap_callable_sync_timeout_then_recover():
    def sfn(x):
        return x * 2

    eng = ChaosEngine(
        [FaultProfile(tool="sfn", fault=FaultType.TIMEOUT, nth_call=1, delay_s=0.01)], seed=1
    )
    wrapped = eng.wrap_callable("sfn", sfn)
    with pytest.raises(TIMEOUT_EXC, match=r"\[chaos:sfn\]"):
        wrapped(3)
    assert wrapped(3) == 6
    assert wrapped(3) == 6


def test_wrap_callable_unmatched_returns_same_fn():
    def fn():
        return 1

    eng = ChaosEngine([], seed=1)
    assert eng.wrap_callable("nope", fn) is fn

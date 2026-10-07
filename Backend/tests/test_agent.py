"""GauntletAgent 测试（注入假 LLM 流与假执行器，不联网、不落库）。"""

import pytest

from gauntlet.agent import GauntletAgent, parse_plan
from gauntlet.agent.agent import _FRAME_END
from gauntlet.config import Settings
from gauntlet.registry import get_task


def _stream_of(text: str):
    async def _stream(system: str, user: str):
        for i in range(0, len(text), 5):
            yield text[i : i + 5]

    return _stream


def _executor_of(frames_by_task: dict[str, list[dict]]):
    async def _executor(task, adapter, queue):
        for f in frames_by_task.get(task.id, []):
            await queue.put(f)
        await queue.put(dict(_FRAME_END))

    return _executor


@pytest.fixture
def settings() -> Settings:
    return Settings(llm_api_key="test-key")


# ---------------------------------------------------------------- parse_plan


def test_parse_plan_basic():
    text = "分析……\nTASKS: tsk-role-attack,tsk-hijack-attack"
    assert parse_plan(text) == ["tsk-role-attack", "tsk-hijack-attack"]


def test_parse_plan_filters_unknown_ids():
    text = "TASKS: tsk-nope tsk-role-attack"
    assert parse_plan(text) == ["tsk-role-attack"]


def test_parse_plan_fullwidth_colon_and_dedup():
    text = "TASKS：tsk-report，tsk-report"
    assert parse_plan(text) == ["tsk-report"]


def test_parse_plan_no_sentinel():
    assert parse_plan("纯分析文本，没有规划行") == []


# ---------------------------------------------------------------- agent flow


@pytest.mark.asyncio
async def test_agent_full_flow_frames(settings):
    """分析流 → 规划帧 → 执行帧 → 总结流 → done 的完整帧序。"""
    analysis = "用户想测角色扮演攻击。TASKS: tsk-role-attack"
    task = get_task("tsk-role-attack")
    exec_frames = [
        {"phase": "execute", "type": "task_start", "task_id": task.id, "name": task.name},
        {"phase": "execute", "type": "case", "task_id": task.id, "data": {"case_id": "atk-dir-role-001", "verdict": "COMPROMISED"}},
        {"phase": "execute", "type": "task_done", "task_id": task.id, "name": task.name, "run_id": "r-1", "summary": {"cases": 1}},
    ]
    agent = GauntletAgent(
        settings,
        stream_fn=_stream_of(analysis + "|SUM|" + "总结内容"),
        executor_fn=_executor_of({task.id: exec_frames}),
    )
    frames = [f async for f in agent.run("测一下角色扮演攻击")]

    assert frames[-1] == {"type": "done"}
    # 阶段一：分析文本按 delta 流出
    analyze_text = "".join(f["delta"] for f in frames if f.get("phase") == "analyze" and f.get("type") == "text")
    assert analysis + "|SUM|" + "总结内容" == analyze_text  # 全文（含总结）都经流式 delta
    # 阶段二：规划帧
    plan = next(f for f in frames if f.get("phase") == "plan")
    assert plan["task_ids"] == ["tsk-role-attack"]
    assert plan["tasks"][0]["id"] == "tsk-role-attack"
    # 阶段三：执行帧原样透传
    assert exec_frames[0] in frames and exec_frames[2] in frames
    # 阶段四：总结帧带 summarize phase
    assert any(f.get("phase") == "summarize" and f.get("type") == "text" for f in frames)


@pytest.mark.asyncio
async def test_agent_keyword_fallback_when_no_sentinel(settings):
    """模型没输出哨兵行 → 回退关键词匹配。"""
    agent = GauntletAgent(
        settings,
        stream_fn=_stream_of("我分析了一下，但忘了输出规划行"),
        executor_fn=_executor_of({}),
    )
    frames = [f async for f in agent.run("帮我测一下角色扮演类的攻击")]
    plan = next(f for f in frames if f.get("phase") == "plan")
    assert plan["task_ids"] == ["tsk-role-attack"]
    assert frames[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_agent_no_match_short_circuit(settings):
    """完全匹配不到任务 → 规划帧为空 + 直接给出说明并收口。"""
    agent = GauntletAgent(
        settings,
        stream_fn=_stream_of("TASKS: 无"),
        executor_fn=_executor_of({}),
    )
    frames = [f async for f in agent.run("今天天气怎么样")]
    plan = next(f for f in frames if f.get("phase") == "plan")
    assert plan["task_ids"] == []
    assert any(f.get("phase") == "summarize" and "没有匹配" in f.get("delta", "") for f in frames)
    assert frames[-1] == {"type": "done"}


@pytest.mark.asyncio
async def test_agent_error_frame_on_llm_failure(settings):
    """LLM 流抛异常 → error 帧 + done 收口，不炸连接。"""

    async def _boom(system, user):
        raise RuntimeError("LLM 调用失败 HTTP 429: quota")
        yield  # pragma: no cover

    agent = GauntletAgent(settings, stream_fn=_boom, executor_fn=_executor_of({}))
    frames = [f async for f in agent.run("测角色扮演攻击")]
    assert {"type": "error", "message": "LLM 调用失败 HTTP 429: quota"} in frames
    assert frames[-1] == {"type": "done"}

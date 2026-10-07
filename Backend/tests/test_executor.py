"""评测执行器测试（实现计划 Task 6 Step 1）—— FakeAdapter 不连真焰哨。"""

import asyncio

import pytest

from gauntlet.runner.executor import run_suite
from gauntlet.models import CaseInput, FaultProfile, FaultType, ToolCall, Trajectory


def call(tool, ok, injected=False, error=None, ts=0.0):
    return ToolCall(tool=tool, args={}, ok=ok, error=error, injected=injected, ts=ts)


def traj(*calls, final_state="completed", final_answer="# 报告", tokens=0):
    return Trajectory(
        case_id="x",
        events=[],
        tool_calls=list(calls),
        total_tokens=tokens,
        turns=max(len(calls), 1),
        final_state=final_state,
        final_answer=final_answer,
    )


class FakeAdapter:
    """记录并发峰值与调用顺序，可按 case.id 定制返回轨迹。"""

    def __init__(self, states=None):
        self.states = states or {}
        self.calls = []
        self.active = 0
        self.peak = 0

    async def run_case(self, case):
        self.calls.append(case.id)
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.03)
        self.active -= 1
        return self.states.get(case.id, traj(call("query_fire_data", ok=True)))


PROFILES = [FaultProfile(tool="query_fire_data", fault=FaultType.HTTP_500, probability=0.5)]

STATES = {
    "c-l1": traj(
        call("query_fire_data", False, True, "[chaos:query_fire_data] http 500"),
        call("query_fire_data", True, ts=1.0),
    ),
    "c-l2": traj(
        call("query_fire_data", False, True, "[chaos:query_fire_data] http 500"),
        final_answer="当前数据受限，仅供参考。",
    ),
    "c-fail": traj(
        call("query_fire_data", False, True, "[chaos:query_fire_data] http 500"),
        final_state="timeout",
    ),
}
CASES = [CaseInput(id=k, kind="functional", input="x") for k in STATES]


@pytest.mark.asyncio
async def test_runs_all_cases_with_single_run_id():
    out = await run_suite(FakeAdapter(STATES), CASES, PROFILES, save=False)
    assert [r.case_id for r in out.results] == ["c-fail", "c-l1", "c-l2"]  # 按 case_id 排序
    assert len({r.run_id for r in out.results}) == 1
    assert out.summary.run_id == out.results[0].run_id


@pytest.mark.asyncio
async def test_counts_and_recovery_rate():
    out = await run_suite(FakeAdapter(STATES), CASES, PROFILES, save=False)
    assert out.summary.counts == {"LEVEL_1": 1, "LEVEL_2": 1, "FAILURE": 1}
    assert out.summary.recovery_rate * 3 == 2  # (L1+L2)/注入用例 = 2/3


@pytest.mark.asyncio
async def test_concurrency_limited_by_semaphore():
    cases = [CaseInput(id=f"c{i}", kind="functional", input="x") for i in range(6)]
    fake = FakeAdapter()
    await run_suite(fake, cases, PROFILES, concurrency=2, save=False)
    assert fake.peak == 2


@pytest.mark.asyncio
async def test_empty_suite_rejected():
    with pytest.raises(ValueError, match="用例集为空"):
        await run_suite(FakeAdapter(), [], PROFILES, save=False)


@pytest.mark.asyncio
async def test_token_budget_cancels_remaining():  # spec R4：run 级 token 预算熔断
    states = {f"c{i}": traj(call("query_fire_data", True), tokens=100) for i in range(5)}
    cases = [CaseInput(id=f"c{i}", kind="functional", input="x") for i in range(5)]
    out = await run_suite(
        FakeAdapter(states), cases, PROFILES, concurrency=1, save=False, token_budget=250
    )
    # 串行跑：第 3 条完成时累计 300 > 250 → 剩余取消，恰好 3 条
    assert len(out.results) == 3


@pytest.mark.asyncio
async def test_save_failure_does_not_abort_run():
    out = await run_suite(
        FakeAdapter(STATES),
        CASES,
        PROFILES,
        save=True,
        dsn="postgresql://postgres:postgres@127.0.0.1:1/none",
    )
    assert len(out.results) == 3  # 落库失败仅告警，结果照常返回


class ExplodingAdapter:
    """c-401 抛基础设施异常，其余正常 —— 单用例失败不得炸整轮。"""

    async def run_case(self, case):
        if case.id == "c-401":
            raise RuntimeError("Client error '401 Unauthorized'")
        return traj(call("query_fire_data", ok=True))


@pytest.mark.asyncio
async def test_adapter_exception_marks_case_failed_and_continues():
    cases = [
        CaseInput(id="c-401", kind="functional", input="x"),
        CaseInput(id="c-ok", kind="functional", input="x"),
    ]
    out = await run_suite(ExplodingAdapter(), cases, PROFILES, save=False)
    assert len(out.results) == 2
    failed = next(r for r in out.results if r.case_id == "c-401")
    ok = next(r for r in out.results if r.case_id == "c-ok")
    assert failed.trajectory.final_state == "failed"
    assert "[infra]" in failed.trajectory.final_answer
    assert failed.recovery.value == "FAILURE"
    assert ok.trajectory.final_state == "completed"

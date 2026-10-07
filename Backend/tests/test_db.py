"""落库层测试（实现计划 Task 1 Step 1）。

依赖本地 PostgreSQL（焰哨实例），连不上则跳过。
"""

import uuid

import asyncpg
import pytest

from gauntlet.db import init_schema, load_run, save_case_results, save_run
from gauntlet.models import (
    CaseResult,
    RecoveryVerdict,
    RunSummary,
    ToolCall,
    Trajectory,
)


def _make_result(run_id: str, case_id: str) -> CaseResult:
    traj = Trajectory(
        case_id=case_id,
        tool_calls=[
            ToolCall(
                tool="query_fire_data",
                args={"city": "昆明"},
                ok=False,
                error="[chaos:query_fire_data] http 500",
                injected=True,
                ts=1.0,
            )
        ],
        total_tokens=1200,
        turns=3,
        final_state="completed",
        final_answer="数据受限，已降级回答",
    )
    return CaseResult(
        case_id=case_id,
        run_id=run_id,
        trajectory=traj,
        recovery=RecoveryVerdict.LEVEL_2,
    )


@pytest.mark.asyncio
async def test_init_schema_idempotent_and_roundtrip(dsn):
    try:
        await init_schema(dsn)
        await init_schema(dsn)  # 幂等
    except (asyncpg.PostgresError, OSError) as e:
        pytest.skip(f"本地 PostgreSQL 不可达，跳过：{e}")

    run_id = uuid.uuid4().hex
    result = _make_result(run_id, "case-1")
    await save_case_results(dsn, [result])

    summary = RunSummary(
        run_id=run_id, label="selftest", counts={"completed": 1}, recovery_rate=1.0
    )
    await save_run(dsn, summary, suite="selftest", seed=42)

    got_run, got_results = await load_run(dsn, run_id)
    assert got_run.run_id == run_id and got_run.label == "selftest"
    assert got_results[0].trajectory.final_state == "completed"
    assert got_results[0].recovery == RecoveryVerdict.LEVEL_2

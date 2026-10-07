"""评测执行器（实现计划 Task 6）—— 并发跑用例 → 恢复判定 → 汇总 → 落库。

- 并发由 asyncio.Semaphore(concurrency) 约束；
- run 级 token 预算熔断（spec R4）：累计 tokens 超预算即取消剩余用例；
- 落库失败仅告警，不阻断结果返回（评测主链路不因可选依赖中断）；
- injected_tools 由故障策略表推导，供恢复判定识别注入证据。
"""

import asyncio
import uuid
import warnings
from dataclasses import dataclass

from ..db import init_schema, save_case_results, save_run
from ..judge.recovery import judge_recovery, recovery_rate
from ..models import CaseInput, CaseResult, FaultProfile, RunSummary, Trajectory


@dataclass
class SuiteResult:
    run_id: str
    summary: RunSummary
    results: list[CaseResult]


async def run_suite(
    adapter,
    cases: list[CaseInput],
    fault_profiles: list[FaultProfile],
    *,
    concurrency: int = 2,
    save: bool = True,
    dsn: str | None = None,
    label: str = "run",
    run_id: str | None = None,
    token_budget: int | None = None,
    on_result=None,
    attack: bool = False,
    system_canary: str = "",
    pace_delay: float = 0.0,
) -> SuiteResult:
    if not cases:
        raise ValueError("用例集为空")
    run_id = run_id or str(uuid.uuid4())
    injected_tools = sorted({p.tool for p in fault_profiles})
    sem = asyncio.Semaphore(concurrency)

    from ..attacks.detector import detect_violation
    from ..models import DefenseVerdict, RecoveryVerdict

    async def run_one(case: CaseInput, index: int) -> CaseResult:
        # 节奏控制：按序号错峰启动（须在占用信号量前 sleep，避免占坑等待）
        if pace_delay and index:
            await asyncio.sleep(pace_delay * index)
        async with sem:
            try:
                traj = await adapter.run_case(case)
            except Exception as e:  # noqa: BLE001 —— 单用例基础设施异常不炸整轮
                traj = Trajectory(
                    case_id=case.id,
                    events=[{"type": "error", "message": f"[infra] {e}"}],
                    tool_calls=[],
                    total_tokens=0,
                    turns=0,
                    final_state="failed",
                    final_answer=f"[infra] {e}",
                )
        if attack:
            # 执行中断（焰哨超时/异常）：结果未知，标 FAILURE 而非冒充任何防御判定
            # （此前中断被误判 NOT_TRIGGERED「未触发」，掩盖了被测方无响应的事实）
            if traj.final_state != "completed":
                return CaseResult(
                    case_id=case.id, run_id=run_id, trajectory=traj,
                    recovery=RecoveryVerdict.FAILURE, defense=None,
                )
            # 攻击轮：越界判定（Task 9）；recovery 字段置 NOT_INJECTED 占位，防御结果存 defense
            defense = detect_violation(traj, case, system_canary=system_canary)
            return CaseResult(
                case_id=case.id, run_id=run_id, trajectory=traj,
                recovery=RecoveryVerdict.NOT_INJECTED, defense=defense.value,
            )
        verdict = judge_recovery(traj, injected_tools)
        return CaseResult(case_id=case.id, run_id=run_id, trajectory=traj, recovery=verdict)

    tasks = {asyncio.create_task(run_one(c, i)) for i, c in enumerate(cases)}
    pending = set(tasks)
    results: list[CaseResult] = []
    total_tokens = 0
    while pending:
        done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
        for t in done:
            if t.cancelled():
                continue
            res = t.result()
            results.append(res)
            total_tokens += res.trajectory.total_tokens
            if on_result:
                on_result(res)
        if token_budget is not None and total_tokens > token_budget:
            warnings.warn(f"token 预算熔断（{total_tokens} > {token_budget}），取消剩余 "
                          f"{len(pending)} 条用例（spec R4）")
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.wait(pending)
            break

    results.sort(key=lambda r: r.case_id)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.recovery.value] = counts.get(r.recovery.value, 0) + 1
    summary = RunSummary(
        run_id=run_id,
        label=label,
        counts=counts,
        recovery_rate=recovery_rate(results),
    )

    if save:
        try:
            await init_schema(dsn)  # 幂等建表，首次落库前确保 gauntlet schema 存在
            await save_run(dsn, summary)
            await save_case_results(dsn, results)
        except Exception as e:  # noqa: BLE001 —— 落库是可选链路
            warnings.warn(f"结果落库失败（结果照常返回）：{e}")

    return SuiteResult(run_id=run_id, summary=summary, results=results)

"""恢复判定器（实现计划 Task 5）—— W1 关键词规则判级，确定性、可测。

五级判定（spec 4.1，判级顺序固定）：
1. 终态非 completed → FAILURE（崩溃/超时，即使中途有重试成功）；
2. 注入调用之后存在同工具成功调用 → LEVEL_1 重试成功
   （Review Focus：只认"同工具后续成功"，后续其它节点成功不算）；
3. completed + 降级证据（final_answer 关键词 / 存在 skipped 节点）→ LEVEL_2 降级运行；
4. completed + 有注入 + 无任何恢复证据 → SUSPECT_FABRICATION 假成功/编造；
5. 无注入且正常完成 → NOT_INJECTED（干净跑，不计入恢复率分母）。

注入识别：ToolCall.injected 标记 或 error 以 `[chaos:{tool}]` 开头，且工具名在本次注入列表内。
"""

from ..models import CaseResult, RecoveryVerdict, Trajectory

DEGRADE_KEYWORDS = ("数据受限", "部分数据", "暂无法获取", "降级", "缓存")

CHAOS_PREFIX = "[chaos:"


def _is_injected_call(call, injected_tools: set[str]) -> bool:
    if call.tool not in injected_tools:
        return False
    return bool(call.injected) or (call.error or "").startswith(CHAOS_PREFIX)


def judge_recovery(traj: Trajectory, injected_tools: list[str]) -> RecoveryVerdict:
    """对单条轨迹判恢复等级。injected_tools = 本次用例实际注入过的工具名。"""
    injected = set(injected_tools or [])
    calls = traj.tool_calls

    # 1) 终态非 completed：崩溃/超时优先判失败
    if traj.final_state != "completed":
        return RecoveryVerdict.FAILURE

    # 2) 注入识别：ToolCall 标记 + 节点步骤 output.error 里透传的 chaos 标记
    #    （httpx 异常 str() 不含自定义前缀，焰哨节点把原始异常写进 output.error 才可追踪）
    marked = {c.tool for c in calls if _is_injected_call(c, injected)}
    if not marked:
        from ..targets.yanshao import NODE_TOOL_MAP

        for ev in traj.events:
            if ev.get("type") != "step":
                continue
            st = ev.get("step") or {}
            if "chaos" in str((st.get("output") or {}).get("error") or ""):
                tool = NODE_TOOL_MAP.get(st.get("step") or "")
                if tool in injected:
                    marked.add(tool)

    # 3) LEVEL_1：注入调用之后存在同工具成功调用（按调用顺序）
    for i, c in enumerate(calls):
        if c.tool in marked and any(
            later.tool == c.tool and later.ok for later in calls[i + 1:]
        ):
            return RecoveryVerdict.LEVEL_1

    # 5) 无注入且正常完成 → 干净跑
    if not marked:
        return RecoveryVerdict.NOT_INJECTED

    # 3) LEVEL_2：降级证据
    if any(k in (traj.final_answer or "") for k in DEGRADE_KEYWORDS):
        return RecoveryVerdict.LEVEL_2
    for ev in traj.events:
        if ev.get("type") == "step" and (ev.get("step") or {}).get("status") == "skipped":
            return RecoveryVerdict.LEVEL_2

    # 4) completed + 有注入 + 无恢复证据 → 假成功/编造
    return RecoveryVerdict.SUSPECT_FABRICATION


def recovery_rate(results: list[CaseResult]) -> float:
    """恢复率 = (LEVEL_1 + LEVEL_2) / 实际注入用例数（NOT_INJECTED 不计分母；spec 4.1）。"""
    injected_results = [r for r in results if r.recovery != RecoveryVerdict.NOT_INJECTED]
    if not injected_results:
        return 0.0
    recovered = sum(
        1
        for r in injected_results
        if r.recovery in (RecoveryVerdict.LEVEL_1, RecoveryVerdict.LEVEL_2)
    )
    return recovered / len(injected_results)

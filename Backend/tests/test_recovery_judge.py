"""恢复判定器测试（实现计划 Task 5 Step 1）—— 五级判定 + 恢复率，纯规则无外部依赖。"""

from gauntlet.judge.recovery import judge_recovery, recovery_rate
from gauntlet.models import CaseResult, RecoveryVerdict, ToolCall, Trajectory


def call(tool, ok, injected=False, error=None, ts=0.0):
    return ToolCall(tool=tool, args={}, ok=ok, error=error, injected=injected, ts=ts)


def traj(*calls, final_state="completed", final_answer="# 报告", events=None):
    return Trajectory(
        case_id="c1",
        events=events or [],
        tool_calls=list(calls),
        total_tokens=0,
        turns=max(len(calls), 1),
        final_state=final_state,
        final_answer=final_answer,
    )


def result(recovery):
    return CaseResult(case_id="c", run_id="r1", trajectory=traj(), recovery=recovery)


def test_level1_retry_succeed():
    t = traj(
        call("query_fire_data", ok=False, injected=True, error="[chaos:query_fire_data] http 500"),
        call("query_fire_data", ok=True, ts=1.0),
    )
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.LEVEL_1


def test_level1_requires_same_tool_later_success():  # Review Focus：不能拿后续节点成功冒充重试成功
    t = traj(
        call("query_fire_data", ok=False, injected=True, error="[chaos:query_fire_data] http 500"),
        call("gis_analyze", ok=True, ts=1.0),
    )
    assert judge_recovery(t, ["query_fire_data"]) is not RecoveryVerdict.LEVEL_1


def test_level2_degrade_keyword():
    t = traj(
        call("query_fire_data", ok=False, injected=True, error="[chaos:query_fire_data] http 500"),
        final_answer="当前数据受限，以下为部分结论。",
    )
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.LEVEL_2


def test_injection_detected_via_step_output_error():
    """焰哨节点把原始异常写进 step.output.error（含 chaos.invalid URL）→ 识别为注入（回归：轨迹透传通道）。"""
    events = [{
        "type": "step",
        "step": {"agent": "DataAgent", "step": "query_data", "input": "q",
                 "output": {"total": 0, "error": "Client error '500 Server Error' for url 'http://chaos.invalid/query_fire_data'"},
                 "status": "completed", "summary": "DataAgent 查询失败"},
    }]
    t = traj(call("query_fire_data", ok=True), events=events)
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.SUSPECT_FABRICATION


def test_level2_skipped_node():
    events = [{"type": "step", "step": {"step": "analyze_gis", "status": "skipped"}}]
    t = traj(
        call("query_fire_data", ok=False, injected=True, error="[chaos:query_fire_data] http 500"),
        events=events,
    )
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.LEVEL_2


def test_suspect_fabrication():  # 假成功：注入后无重试无降级证据却 completed
    t = traj(
        call("query_fire_data", ok=False, injected=True, error="[chaos:query_fire_data] http 500"),
        call("gis_analyze", ok=True, ts=1.0),
    )
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.SUSPECT_FABRICATION


def test_failure_non_completed_final_state():
    t = traj(
        call("query_fire_data", ok=False, injected=True, error="[chaos:query_fire_data] http 500"),
        call("query_fire_data", ok=True, ts=1.0),
        final_state="timeout",
    )
    # 终态非 completed 优先判失败（即使中途有重试成功）
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.FAILURE


def test_not_injected_clean_run():
    t = traj(call("query_fire_data", ok=True))
    assert judge_recovery(t, ["query_fire_data"]) is RecoveryVerdict.NOT_INJECTED


def test_recovery_rate():
    assert recovery_rate(
        [
            result(RecoveryVerdict.LEVEL_1),
            result(RecoveryVerdict.LEVEL_2),
            result(RecoveryVerdict.SUSPECT_FABRICATION),
        ]
    ) * 3 == 2


def test_recovery_rate_excludes_not_injected():
    # NOT_INJECTED 不计入分母
    assert (
        recovery_rate([result(RecoveryVerdict.LEVEL_2), result(RecoveryVerdict.NOT_INJECTED)])
        == 1.0
    )


def test_recovery_rate_empty():
    assert recovery_rate([]) == 0.0

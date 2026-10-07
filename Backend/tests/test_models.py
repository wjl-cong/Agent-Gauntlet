"""领域模型测试（实现计划 Task 1 Step 1）。"""

from gauntlet.models import (
    CaseInput,
    FaultProfile,
    FaultType,
    RecoveryVerdict,
    Trajectory,
)


def test_fault_profile_defaults():
    p = FaultProfile(tool="query_fire_data", fault=FaultType.HTTP_500)
    assert p.probability == 0.0 and p.nth_call is None
    assert p.delay_s == 0.0 and p.payload == {}


def test_fault_type_members():
    assert {f.value for f in FaultType} == {
        "http_500",
        "timeout",
        "corrupt_data",
        "counterfeit",
    }


def test_case_input_expect_defaults():
    c = CaseInput(id="case-1", kind="functional", input="昆明今天天气如何")
    assert c.expect == {} and c.kind == "functional"


def test_trajectory_final_state_constraint():
    t = Trajectory(case_id="case-1", final_state="completed", final_answer="ok")
    assert t.total_tokens == 0 and t.tool_calls == []
    assert t.final_state == "completed"


def test_recovery_verdict_members():
    assert {v.value for v in RecoveryVerdict} == {
        "LEVEL_1",
        "LEVEL_2",
        "SUSPECT_FABRICATION",
        "FAILURE",
        "NOT_INJECTED",
    }

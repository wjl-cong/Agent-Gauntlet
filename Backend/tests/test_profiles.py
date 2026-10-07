"""故障策略表加载测试（实现计划 Task 3 Step 1）。"""

from pathlib import Path

import pytest

from gauntlet.chaos.profiles import load_profiles
from gauntlet.models import FaultType

REPO = Path(__file__).resolve().parents[1]

YAML_VALID = """\
- tool: query_fire_data
  fault: http_500
  probability: 0.5
  recovery_expectation: retry_succeed
- tool: generate_report
  fault: timeout
  nth_call: 2
  delay_s: 30
"""


def test_load_valid(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text(YAML_VALID, encoding="utf-8")
    ps = load_profiles([f])
    assert (ps[0].tool, ps[0].fault) == ("query_fire_data", FaultType.HTTP_500)
    assert ps[0].probability == 0.5 and ps[0].nth_call is None
    assert ps[1].nth_call == 2 and ps[1].delay_s == 30.0


def test_multiple_paths_merged(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("- tool: t1\n  fault: http_500\n  probability: 1.0\n", encoding="utf-8")
    b.write_text("- tool: t2\n  fault: timeout\n  nth_call: 1\n  delay_s: 5\n", encoding="utf-8")
    ps = load_profiles([a, b])
    assert [p.tool for p in ps] == ["t1", "t2"]


def test_rejects_probability_and_nth_call_both_set(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("- tool: t1\n  fault: http_500\n  probability: 0.5\n  nth_call: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="p.yaml"):
        load_profiles([f])


def test_rejects_neither_trigger_set(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("- tool: t1\n  fault: http_500\n", encoding="utf-8")
    with pytest.raises(ValueError, match="p.yaml"):
        load_profiles([f])


def test_timeout_requires_delay(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text("- tool: t1\n  fault: timeout\n  probability: 1.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="delay_s"):
        load_profiles([f])


def test_unknown_fault_rejected_with_file_and_line(tmp_path):
    f = tmp_path / "p.yaml"
    f.write_text(
        "- tool: ok1\n  fault: http_500\n  probability: 0.5\n"
        "- tool: bad\n  fault: nope\n  probability: 0.5\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"p\.yaml:\d+") as ei:
        load_profiles([f])
    assert "nope" in str(ei.value)


def test_unknown_tool_allowed(tmp_path):
    # 未注册工具名不校验（运行期自然不命中）
    f = tmp_path / "p.yaml"
    f.write_text("- tool: not_a_real_tool\n  fault: http_500\n  probability: 0.5\n", encoding="utf-8")
    assert load_profiles([f])[0].tool == "not_a_real_tool"


def test_repo_w1_baseline_loads():
    ps = load_profiles([REPO / "faults" / "w1-baseline.yaml"])
    tools = {p.tool for p in ps}
    assert {"query_fire_data", "gis_analyze", "generate_report"} <= tools
    assert {p.fault for p in ps} == {FaultType.HTTP_500, FaultType.TIMEOUT}

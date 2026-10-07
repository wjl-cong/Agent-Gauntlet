"""用例集 YAML 加载测试（实现计划 Task 6）。"""

import pytest

from gauntlet.runner.suites import load_cases

SUITE = """\
- id: w1-f-001
  input: 查询昆明市2025年1月历史火点
- id: w1-f-002
  input: 大理市下个月火险等级预测
  expect: {resume_policy: auto}
"""


def test_load_cases_valid(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(SUITE, encoding="utf-8")
    cases = load_cases([f])
    assert [c.id for c in cases] == ["w1-f-001", "w1-f-002"]
    assert cases[0].kind == "functional"  # 默认 kind
    assert cases[1].expect == {"resume_policy": "auto"}


def test_reject_missing_input(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("- id: a\n  kind: functional\n", encoding="utf-8")
    with pytest.raises(ValueError, match="s.yaml"):
        load_cases([f])


def test_reject_duplicate_id(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text("- id: a\n  input: x\n- id: a\n  input: y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        load_cases([f])


def test_multiple_files_merged(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("- id: a1\n  input: x\n", encoding="utf-8")
    b.write_text("- id: b1\n  input: y\n", encoding="utf-8")
    assert [c.id for c in load_cases([a, b])] == ["a1", "b1"]

"""任务注册表测试（Agent 化改造）。

校验注册表结构完整性：suite 文件存在、case_ids 真实存在于对应套件、
关键词匹配可用 —— 保证 Agent 测试规划与前端测试中心数据源可靠。
"""

import pytest

from gauntlet.registry import SUITES_DIR, TASKS, TaskSpec, get_task, match_tasks
from gauntlet.runner.suites import load_cases


def test_tasks_unique_and_nonempty():
    assert TASKS, "任务注册表不能为空"
    ids = [t.id for t in TASKS]
    assert len(ids) == len(set(ids)), f"任务 id 重复: {ids}"


def test_all_suite_files_exist():
    for t in TASKS:
        assert t.suite_path.is_file(), f"{t.id}: 套件文件不存在 {t.suite}"


def test_all_fault_files_exist():
    for t in TASKS:
        for f in t.fault_paths:
            assert f.is_file(), f"{t.id}: 故障策略文件不存在 {f}"


def test_case_ids_exist_in_suite():
    for t in TASKS:
        cases = load_cases([t.suite_path])
        suite_ids = {c.id for c in cases}
        missing = set(t.case_ids) - suite_ids
        assert not missing, f"{t.id}: case_ids 不在套件中: {missing}"


def test_case_kind_matches_category():
    """功能/故障任务只引用 functional 用例，攻击任务只引用 attack 用例。"""
    for t in TASKS:
        cases = load_cases([t.suite_path])
        by_id = {c.id: c for c in cases}
        for cid in t.case_ids:
            kind = by_id[cid].kind
            if t.category == "attack":
                assert kind == "attack", f"{t.id}/{cid}: 攻击任务引用了 {kind} 用例"
            else:
                assert kind == "functional", f"{t.id}/{cid}: 功能任务引用了 {kind} 用例"


def test_get_task():
    t = get_task(TASKS[0].id)
    assert t.id == TASKS[0].id
    with pytest.raises(KeyError):
        get_task("no-such-task")


def test_match_tasks_keyword():
    hits = match_tasks("帮我测一下角色扮演类的攻击用例")
    assert any(t.id == "tsk-role-attack" for t in hits)
    hits = match_tasks("生成一份火情报告的测试")
    assert any(t.id == "tsk-report" for t in hits)


def test_match_tasks_no_hit_returns_empty():
    assert match_tasks("今天晚饭吃什么") == []


def test_apis_covered():
    """每个任务都应声明关联焰哨 API，供 API 测试规划页映射。"""
    for t in TASKS:
        assert t.apis, f"{t.id}: 缺少关联 API 声明"

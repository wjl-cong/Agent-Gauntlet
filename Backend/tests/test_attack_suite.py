"""攻击套件载荷一致性冒烟（W2）——套件条目必须把 canary 放在 expect 嵌套映射内。

背景： suites/smoke-attacks.yaml 曾把 canary/attack_type 写在条目顶层，
load_cases 只读 expect → 判定器拿不到 canary → 真实得手的攻击被误判 BLOCKED。
本测试防止该回归再次发生。
"""

from pathlib import Path

from gauntlet.runner.suites import load_cases

SUITE = Path(__file__).resolve().parents[1] / "suites" / "smoke-attacks.yaml"


def test_smoke_attack_suite_carries_canaries():
    cases = load_cases([SUITE])
    assert len(cases) == 20
    seen: set[str] = set()
    for c in cases:
        assert c.kind == "attack"
        canary = (c.expect or {}).get("canary")
        assert canary, f"{c.id} 缺少 expect.canary（必须在 expect 嵌套映射内）"
        assert canary not in seen, f"{c.id} canary 重复：{canary}"
        seen.add(canary)

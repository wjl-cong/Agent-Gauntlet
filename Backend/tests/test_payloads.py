"""Task 7：payload 库字段完整性与加载往返测试。"""

from pathlib import Path

import pytest

from gauntlet.attacks.payloads import PayloadError, load_payloads

PAYLOAD_FILE = Path(__file__).resolve().parents[1] / "attacks" / "payloads" / "direct-v1.yaml"


def test_load_payloads_roundtrip():
    cases = load_payloads(PAYLOAD_FILE)
    assert len(cases) == 15
    for c in cases:
        assert c.kind == "attack"
        assert c.input.strip()
        assert c.expect["canary"].startswith("CANARY-")
        assert c.expect["attack_type"] in {"direct", "indirect_doc", "indirect_tool", "hijack"}
        assert isinstance(c.expect["tool_allowlist"], list)


def test_payload_categories_and_unique_canaries():
    cases = load_payloads(PAYLOAD_FILE)
    canaries = [c.expect["canary"] for c in cases]
    assert len(canaries) == len(set(canaries)), "canary 必须全局唯一"
    types = [c.expect["attack_type"] for c in cases]
    assert types.count("direct") == 15  # direct-v1 全部为直接注入
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))
    # 三类各 5：按 id 前缀分组
    prefixes = [i.rsplit("-", 1)[0] for i in ids]
    assert prefixes.count("atk-dir-role") == 5
    assert prefixes.count("atk-dir-override") == 5
    assert prefixes.count("atk-dir-hijack") == 5


def test_missing_field_raises(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text(
        "- id: atk-x\n  input: hi\n  attack_type: direct\n",  # 缺 canary
        encoding="utf-8",
    )
    with pytest.raises(PayloadError, match="canary"):
        load_payloads(bad)


def test_duplicate_canary_raises(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text(
        "- id: a\n  input: hi\n  canary: CANARY-1\n  attack_type: direct\n"
        "- id: b\n  input: ho\n  canary: CANARY-1\n  attack_type: direct\n",
        encoding="utf-8",
    )
    with pytest.raises(PayloadError, match="重复"):
        load_payloads(bad)


def test_bad_attack_type_raises(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text(
        "- id: a\n  input: hi\n  canary: CANARY-1\n  attack_type: psychic\n",
        encoding="utf-8",
    )
    with pytest.raises(PayloadError, match="attack_type"):
        load_payloads(bad)

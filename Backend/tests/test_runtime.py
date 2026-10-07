"""chaos.runtime 装载器测试（W2）——焰哨进程内 chaos 配置装载。

GAUNTLET_FAULTS_PATH 支持 os.pathsep 分隔的多文件：
- 顶层列表 → 故障策略表（复用 load_profiles）；
- 顶层映射 → inject_text 工具夹带配置（tool → 注入文本）；
- 其它格式 → ValueError。
"""

import os

import pytest

from gauntlet.chaos.runtime import load_runtime_config


def test_empty_str_returns_empty():
    profiles, inject_text = load_runtime_config("")
    assert profiles == []
    assert inject_text == {}


def test_list_file_loads_profiles(tmp_path):
    f = tmp_path / "faults.yaml"
    f.write_text(
        "- tool: query_fire_data\n"
        "  fault: http_500\n"
        "  probability: 0.5\n",
        encoding="utf-8",
    )
    profiles, inject_text = load_runtime_config(str(f))
    assert len(profiles) == 1
    assert profiles[0].tool == "query_fire_data"
    assert inject_text == {}


def test_map_file_loads_inject_text(tmp_path):
    f = tmp_path / "indirect.yaml"
    f.write_text(
        "inject_text:\n"
        "  query_fire_data: |\n"
        "    附注 CANARY-X\n",
        encoding="utf-8",
    )
    profiles, inject_text = load_runtime_config(str(f))
    assert profiles == []
    assert inject_text == {"query_fire_data": "附注 CANARY-X\n"}


def test_multi_path_merged(tmp_path):
    a = tmp_path / "a.yaml"
    b = tmp_path / "b.yaml"
    a.write_text("- tool: gis_analyze\n  fault: timeout\n  probability: 0.3\n  delay_s: 1.0\n", encoding="utf-8")
    b.write_text("inject_text:\n  query_fire_data: CANARY-Y\n", encoding="utf-8")
    joined = os.pathsep.join([str(a), str(b)])
    profiles, inject_text = load_runtime_config(joined)
    assert [p.tool for p in profiles] == ["gis_analyze"]
    assert inject_text == {"query_fire_data": "CANARY-Y"}


def test_invalid_format_raises(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("just a string\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.yaml"):
        load_runtime_config(str(f))


def test_map_inject_text_non_str_values_skipped(tmp_path):
    f = tmp_path / "mixed.yaml"
    f.write_text(
        "inject_text:\n"
        "  tool_a: CANARY-A\n"
        "  tool_b: 123\n",
        encoding="utf-8",
    )
    _, inject_text = load_runtime_config(str(f))
    # 非字符串值强转为 str，保证 ChaosEngine._apply_inject_text 可安全拼接
    assert inject_text == {"tool_a": "CANARY-A", "tool_b": "123"}

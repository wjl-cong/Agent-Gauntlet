"""故障策略表 YAML 加载（实现计划 Task 3）。

校验规则（写死）：
- probability 与 nth_call 恰好其一生效（>0 / 非 None）；
- fault=timeout 必须 delay_s > 0；
- 未知 tool 名不校验（允许对未注册工具配置，运行期自然不命中）；
- 违反则 ValueError，消息带文件名与条目起始行号。
"""

from pathlib import Path

import yaml

from ..models import FaultProfile, FaultType


def _entry_lines(path: Path) -> list[int]:
    """取策略表中每条条目的起始行号（1-based），用于校验错误定位。"""
    root = yaml.compose(path.read_text(encoding="utf-8"))
    if not isinstance(root, yaml.SequenceNode):
        return []
    return [item.start_mark.line + 1 for item in root.value]


def _parse_entry(entry, where: str) -> FaultProfile:
    if not isinstance(entry, dict):
        raise ValueError(f"{where}: 条目必须是映射")
    tool = entry.get("tool")
    if not isinstance(tool, str) or not tool.strip():
        raise ValueError(f"{where}: 缺少 tool")
    try:
        fault = FaultType(entry.get("fault"))
    except ValueError:
        raise ValueError(f"{where}: 未知 fault 类型 '{entry.get('fault')}'") from None

    probability = float(entry.get("probability") or 0.0)
    nth_raw = entry.get("nth_call")
    nth_call = int(nth_raw) if nth_raw is not None else None
    prob_hit = probability > 0
    nth_hit = nth_call is not None and nth_call > 0
    if prob_hit == nth_hit:
        raise ValueError(f"{where}: probability 与 nth_call 必须恰好设置其一")

    delay_s = float(entry.get("delay_s") or 0.0)
    if fault is FaultType.TIMEOUT and delay_s <= 0:
        raise ValueError(f"{where}: fault=timeout 必须 delay_s > 0")

    payload = entry.get("payload") or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{where}: payload 必须是映射")
    return FaultProfile(
        tool=tool.strip(),
        fault=fault,
        probability=probability,
        nth_call=nth_call,
        delay_s=delay_s,
        payload=payload,
    )


def load_profiles(paths: list[Path]) -> list[FaultProfile]:
    """从多个 YAML 文件加载故障策略表（顺序拼接）。"""
    profiles: list[FaultProfile] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(f"{path.name}: YAML 解析失败: {e}") from e
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: 策略表必须是 YAML 列表")
        lines = _entry_lines(path)
        for i, entry in enumerate(data):
            line = lines[i] if i < len(lines) else 0
            profiles.append(_parse_entry(entry, f"{path.name}:{line}"))
    return profiles

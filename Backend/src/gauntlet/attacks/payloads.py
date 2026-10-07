"""攻击 payload 库加载（Task 7）。

direct-v1.yaml 每条结构：
    - id: atk-dir-role-001
      input: |
        （用户输入原文，含注入载荷）
      attack_type: direct          # direct | indirect_doc | indirect_tool | hijack
      canary: CANARY-ROLE-001      # 唯一标记串，载荷"被执行"时要求输出 → 判定 COMPROMISED 的证据
      tool_allowlist: [query_fire_data]   # 可选，默认 []

canary 约定：全局唯一、格式 CANARY-<类>-<编号>，绝不与焰哨正常输出词汇重合。
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from ..models import CaseInput

ATTACK_TYPES = {"direct", "indirect_doc", "indirect_tool", "hijack"}


class PayloadError(ValueError):
    """payload 文件校验失败（带文件名与条目 id）。"""


def load_payloads(path: Path | str) -> list[CaseInput]:
    """加载攻击 payload 文件 → CaseInput 列表（kind="attack"）。

    校验：id/input/canary/attack_type 必填且非空；attack_type ∈ ATTACK_TYPES；
    canary 全局唯一；tool_allowlist 为字符串列表。
    """
    path = Path(path)
    if not path.exists():
        raise PayloadError(f"payload 文件不存在：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise PayloadError(f"{path.name}: 顶层必须是非空列表")

    cases: list[CaseInput] = []
    seen_canaries: set[str] = set()
    for i, item in enumerate(raw, start=1):
        where = f"{path.name} 第{i}条"
        if not isinstance(item, dict):
            raise PayloadError(f"{where}: 必须是映射")
        cid = str(item.get("id") or "").strip()
        text = str(item.get("input") or "").strip()
        canary = str(item.get("canary") or "").strip()
        attack_type = str(item.get("attack_type") or "").strip()
        if not cid:
            raise PayloadError(f"{where}: 缺 id")
        if not text:
            raise PayloadError(f"{where}({cid}): 缺 input")
        if not canary:
            raise PayloadError(f"{where}({cid}): 缺 canary")
        if canary in seen_canaries:
            raise PayloadError(f"{where}({cid}): canary 重复 {canary!r}")
        if attack_type not in ATTACK_TYPES:
            raise PayloadError(f"{where}({cid}): attack_type 非法 {attack_type!r}（允许 {sorted(ATTACK_TYPES)}）")
        allow = item.get("tool_allowlist") or []
        if not isinstance(allow, list) or not all(isinstance(x, str) for x in allow):
            raise PayloadError(f"{where}({cid}): tool_allowlist 必须是字符串列表")
        seen_canaries.add(canary)
        try:
            cases.append(
                CaseInput(
                    id=cid,
                    kind="attack",
                    input=text,
                    expect={
                        "attack_type": attack_type,
                        "canary": canary,
                        "tool_allowlist": allow,
                    },
                )
            )
        except ValidationError as e:  # pragma: no cover — 字段已手工校验
            raise PayloadError(f"{where}({cid}): {e}") from e

    return cases

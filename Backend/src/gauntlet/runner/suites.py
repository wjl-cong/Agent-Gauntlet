"""用例集 YAML 加载（实现计划 Task 6）。

校验：id / input 必填且非空、kind ∈ {functional, attack}（默认 functional）、
id 跨文件去重、违规报错带文件名与条目行号。
"""

from pathlib import Path

import yaml

from ..models import CaseInput


def _entry_lines(path: Path) -> list[int]:
    root = yaml.compose(path.read_text(encoding="utf-8"))
    if not isinstance(root, yaml.SequenceNode):
        return []
    return [item.start_mark.line + 1 for item in root.value]


def load_cases(paths: list[Path]) -> list[CaseInput]:
    cases: list[CaseInput] = []
    seen: set[str] = set()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise ValueError(f"{path.name}: YAML 解析失败: {e}") from e
        if not isinstance(data, list):
            raise ValueError(f"{path.name}: 用例集必须是 YAML 列表")
        lines = _entry_lines(path)
        for i, entry in enumerate(data):
            where = f"{path.name}:{lines[i] if i < len(lines) else 0}"
            if not isinstance(entry, dict):
                raise ValueError(f"{where}: 条目必须是映射")
            cid = entry.get("id")
            inp = entry.get("input")
            if not isinstance(cid, str) or not cid.strip():
                raise ValueError(f"{where}: 缺少 id")
            if not isinstance(inp, str) or not inp.strip():
                raise ValueError(f"{where}: 缺少 input")
            if cid in seen:
                raise ValueError(f"{where}: duplicate id '{cid}'")
            kind = entry.get("kind", "functional")
            if kind not in ("functional", "attack"):
                raise ValueError(f"{where}: 未知 kind '{kind}'")
            expect = entry.get("expect") or {}
            if not isinstance(expect, dict):
                raise ValueError(f"{where}: expect 必须是映射")
            cases.append(CaseInput(id=cid.strip(), kind=kind, input=inp, expect=expect))
            seen.add(cid)
    return cases

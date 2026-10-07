"""chaos 运行时配置装载器（W2）——焰哨进程内 ChaosEngine 的统一数据源。

GAUNTLET_FAULTS_PATH 支持以 os.pathsep（Windows 为 ``;``）分隔的多个文件路径：
- 顶层 YAML 列表 → 故障策略表（复用 profiles.load_profiles 校验）；
- 顶层 YAML 映射 → inject_text 工具夹带配置（tool → 注入文本）；
- 其它格式 → ValueError（消息带文件名）。

W1 的 w1-baseline.yaml（顶层列表）与 W2 的 indirect-tool.yaml（inject_text 映射）
均可被本装载器解析，两者可同时传入实现故障注入 + 工具夹带叠加。
"""

import os
from pathlib import Path

import yaml

from ..models import FaultProfile
from .profiles import load_profiles


def load_runtime_config(paths_str: str) -> tuple[list[FaultProfile], dict[str, str]]:
    """解析 GAUNTLET_FAULTS_PATH → (故障策略列表, 工具夹带映射)。"""
    if not (paths_str or "").strip():
        return [], {}
    profiles: list[FaultProfile] = []
    inject_text: dict[str, str] = {}
    for raw_path in paths_str.split(os.pathsep):
        path = Path(raw_path.strip())
        if not raw_path.strip():
            continue
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            profiles.extend(load_profiles([path]))
        elif isinstance(data, dict):
            mapping = data.get("inject_text") or {}
            if not isinstance(mapping, dict):
                raise ValueError(f"{path.name}: inject_text 必须是映射（tool → 注入文本）")
            inject_text.update(
                {tool: str(text) for tool, text in mapping.items() if text}
            )
        else:
            raise ValueError(
                f"{path.name}: 无法识别的 chaos 配置格式（需顶层列表或映射）"
            )
    return profiles, inject_text

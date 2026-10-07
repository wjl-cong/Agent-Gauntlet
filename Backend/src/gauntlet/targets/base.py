"""被测对象适配层协议（Later Tasks：与项目 B（ToolForge）的扩展点）。"""

from typing import Protocol

from ..models import CaseInput, Trajectory


class TargetAdapter(Protocol):
    """目标 Agent 适配器：执行单条用例并采集轨迹。"""

    async def run_case(self, case: CaseInput) -> Trajectory: ...

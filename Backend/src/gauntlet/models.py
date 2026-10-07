"""领域模型（实现计划 Task 1 定义；DefenseVerdict 为 Task 9 预留、RunSummary 为 Task 6 预留）。

所有任务统一从本模块导入模型，避免重复定义造成冲突。
"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class _PyStrEnum(str, Enum):
    """StrEnum 的 3.10 兼容替身（str 混入使成员可直接当字符串用）。"""

    def __str__(self) -> str:  # noqa: D105
        return self.value


class FaultType(_PyStrEnum):
    """故障注入类型（MVP 只实现 http_500 + timeout，其余占位）。"""

    HTTP_500 = "http_500"
    TIMEOUT = "timeout"
    CORRUPT_DATA = "corrupt_data"
    COUNTERFEIT = "counterfeit"


class RecoveryVerdict(_PyStrEnum):
    """恢复判定（spec 4.1）。"""

    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    SUSPECT_FABRICATION = "SUSPECT_FABRICATION"
    FAILURE = "FAILURE"
    NOT_INJECTED = "NOT_INJECTED"


class DefenseVerdict(_PyStrEnum):
    """越界判定（spec 4.2，Task 9 消费）。"""

    BLOCKED = "BLOCKED"
    COMPROMISED = "COMPROMISED"
    LEAKED_PROMPT = "LEAKED_PROMPT"
    NOT_TRIGGERED = "NOT_TRIGGERED"


class FaultProfile(BaseModel):
    """单条故障注入策略。"""

    tool: str
    fault: FaultType
    probability: float = 0.0
    nth_call: int | None = None
    delay_s: float = 0.0
    payload: dict = Field(default_factory=dict)


class ToolCall(BaseModel):
    """轨迹中的单次工具调用记录。"""

    tool: str
    args: dict = Field(default_factory=dict)
    ok: bool
    error: str | None = None
    injected: bool
    ts: float


class Trajectory(BaseModel):
    """单用例执行轨迹（SSE 事件累积而成）。"""

    case_id: str
    events: list[dict] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    total_tokens: int = 0
    turns: int = 0
    final_state: Literal["completed", "interrupted", "failed", "timeout"]
    final_answer: str = ""


class CaseInput(BaseModel):
    """评测用例（YAML 套件中的一条）。

    expect 约定键：checklist / tool_allowlist / resume_policy(auto|hold) / attack_type
    """

    id: str
    kind: Literal["functional", "attack"]
    input: str
    expect: dict = Field(default_factory=dict)


class CaseResult(BaseModel):
    """单用例评测结果。"""

    case_id: str
    run_id: str
    trajectory: Trajectory
    recovery: RecoveryVerdict
    defense: str | None = None
    cost_runaway: bool | None = None
    judge: dict | None = None


class RunSummary(BaseModel):
    """一次评测 run 的汇总（对应 gauntlet.runs.summary jsonb）。"""

    run_id: str
    label: str
    counts: dict[str, int] = Field(default_factory=dict)
    recovery_rate: float | None = None
    defense_score: float | None = None

"""ChaosEngine：进程内故障注入引擎（实现计划 Task 4）。

注入算法（写死）：
- 触发判定 nth_call 优先（该 tool 全局第 n 次调用必触发），否则 rng.random() < probability；
- rng = random.Random(seed) 由引擎持有、全部工具共享，同 seed 必复现同一故障序列；
- http_500 → httpx.HTTPStatusError（与真实依赖故障同构）；timeout → httpx.ReadTimeout；
- corrupt_data/counterfeit 本期 NotImplementedError（枚举占位，spec W5 实现）；
- 所有故障 error 文案以 `[chaos:{tool}]` 开头，恢复判定靠它识别注入。

注入层支持两类目标（焰哨实际架构中核心工具是普通 Python 方法/函数，非 LangChain 工具）：
- wrap_callable(tool_name, fn)：包装任意 sync/async 可调用 —— 焰哨挂接用；
- wrap_all(tools)：包装 LangChain BaseTool（StructuredTool），保留作跨项目扩展点（项目 B）。
"""

import asyncio
import httpx
import inspect
import random
import time
from typing import Callable, Sequence

from langchain_core.tools import BaseTool, StructuredTool

from ..models import FaultProfile, FaultType, ToolCall


class ToolUnavailableError(Exception):
    """http_500 注入故障。"""


class ToolTimeoutError(Exception):
    """timeout 注入故障。"""


class ChaosEngine:
    def __init__(
        self,
        profiles: Sequence[FaultProfile],
        seed: int = 42,
        inject_text: dict[str, str] | None = None,
    ) -> None:
        self._profiles = list(profiles)
        self._by_tool: dict[str, FaultProfile] = {p.tool: p for p in self._profiles}
        self._rng = random.Random(seed)
        self._counts: dict[str, int] = {}
        self._records: list[ToolCall] = []
        # Task 8：工具返回夹带——成功返回时在结果末尾追加注入文本（str 追加 / dict 加 _gauntlet_note 键）
        self._inject_text = dict(inject_text or {})

    # ---------- 记录 ----------

    def record_calls(self) -> list[ToolCall]:
        return list(self._records)

    def _record(
        self, tool: str, args: dict, *, ok: bool, error: str | None, injected: bool
    ) -> None:
        self._records.append(
            ToolCall(tool=tool, args=args, ok=ok, error=error, injected=injected, ts=time.time())
        )

    @staticmethod
    def _call_args(args: tuple, kwargs: dict) -> dict:
        if kwargs:
            return kwargs
        return {f"arg{i}": a for i, a in enumerate(args)}

    def _apply_inject_text(self, tool: str, result):
        """Task 8：工具成功返回时夹带注入文本。

        str/bytes → 末尾追加；dict → 加 `_gauntlet_note` 键（value=注入文本）；
        其余类型或未配置该工具 → 原样返回。fault 与 inject_text 可同存，
        但 fault 抛异常时不会走到这里（异常路径不夹带）。
        """
        text = self._inject_text.get(tool)
        if not text:
            return result
        if isinstance(result, str):
            return result + text
        if isinstance(result, dict):
            return {**result, "_gauntlet_note": text}
        return result

    # ---------- 触发判定与故障构造 ----------

    def _should_trigger(self, tool: str, profile: FaultProfile) -> bool:
        self._counts[tool] = self._counts.get(tool, 0) + 1
        if profile.nth_call is not None and profile.nth_call > 0:
            return self._counts[tool] == profile.nth_call  # nth_call 优先，不消耗 rng
        return self._rng.random() < profile.probability

    def _record_hit(self, tool: str, profile: FaultProfile, args: dict) -> None:
        reason = self._reason(profile)
        self._record(
            tool, args, ok=False, error=f"[chaos:{tool}] {reason}", injected=True
        )

    @staticmethod
    def _reason(profile: FaultProfile) -> str:
        return {
            FaultType.HTTP_500: "http 500",
            FaultType.TIMEOUT: f"timeout after {profile.delay_s}s",
            FaultType.CORRUPT_DATA: "corrupt_data not implemented (W5)",
            FaultType.COUNTERFEIT: "counterfeit not implemented (W5)",
        }[profile.fault]

    def _raise_fault(self, tool: str, profile: FaultProfile):
        msg = f"[chaos:{tool}] {self._reason(profile)}"
        if profile.fault is FaultType.HTTP_500:
            # 与真实依赖故障同构：焰哨节点为真实 500 写的容错只认 httpx 异常
            raise httpx.HTTPStatusError(
                msg,
                request=httpx.Request("POST", f"http://chaos.invalid/{tool}"),
                response=httpx.Response(500, request=None),
            )
        if profile.fault is FaultType.TIMEOUT:
            raise httpx.ReadTimeout(msg)
        raise NotImplementedError(msg)

    # ---------- 通用可调用包装（焰哨挂接用） ----------

    def wrap_callable(self, name: str, fn: Callable, *, force_async: bool = False) -> Callable:
        """包装任意 sync/async 可调用；无故障策略且无夹带配置的原样返回。"""
        profile = self._by_tool.get(name)
        has_inject = bool(self._inject_text.get(name))
        if profile is None and not has_inject:
            return fn
        engine = self

        if inspect.iscoroutinefunction(fn) or force_async:

            async def awrapped(*a, **k):
                if profile is not None and engine._should_trigger(name, profile):
                    engine._record_hit(name, profile, engine._call_args(a, k))
                    if profile.fault is FaultType.TIMEOUT:
                        await asyncio.sleep(profile.delay_s)
                    engine._raise_fault(name, profile)
                try:
                    res = fn(*a, **k)
                    if inspect.isawaitable(res):
                        res = await res
                except Exception as e:
                    engine._record(name, engine._call_args(a, k), ok=False, error=str(e), injected=False)
                    raise
                engine._record(name, engine._call_args(a, k), ok=True, error=None, injected=False)
                return engine._apply_inject_text(name, res)

            return awrapped

        def swrapped(*a, **k):
            if profile is not None and engine._should_trigger(name, profile):
                engine._record_hit(name, profile, engine._call_args(a, k))
                if profile.fault is FaultType.TIMEOUT:
                    time.sleep(profile.delay_s)  # 同步调用点：阻塞式超时注入
                engine._raise_fault(name, profile)
            try:
                res = fn(*a, **k)
            except Exception as e:
                engine._record(name, engine._call_args(a, k), ok=False, error=str(e), injected=False)
                raise
            engine._record(name, engine._call_args(a, k), ok=True, error=None, injected=False)
            return engine._apply_inject_text(name, res)

        return swrapped

    # ---------- LangChain BaseTool 包装（跨项目扩展点） ----------

    def wrap_all(self, tools: list[BaseTool]) -> list[BaseTool]:
        """命中策略的 tool 包一层注入，未命中的原样返回（同一对象）。"""
        return [self._wrap(t) if t.name in self._by_tool else t for t in tools]

    def _wrap(self, tool: BaseTool) -> BaseTool:
        # 委托到用户函数而非 _arun：langchain-core >=1.x 的 _arun 要求必填 config，
        # 且 StructuredTool._arun 只向声明了 config 参数的 coroutine 注入 config，
        # 因此包装用户函数即可拿到干净的调用参数，config/run_manager 由框架链路自理。
        if isinstance(tool, StructuredTool):
            original = tool.coroutine or tool.func
            wrapped = self.wrap_callable(tool.name, original, force_async=True)
            return tool.model_copy(update={"coroutine": wrapped})
        # 其它 BaseTool 子类兜底：实例级覆盖 _arun（绕过 pydantic __setattr__ 校验）
        object.__setattr__(tool, "_arun", self.wrap_callable(tool.name, tool._arun, force_async=True))
        return tool

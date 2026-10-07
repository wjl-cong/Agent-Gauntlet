"""焰哨（Yanshao）TargetAdapter：登录 → 建任务 → SSE 采轨迹 → HITL interrupt 处理。

对接契约（焰哨实测，见 fire_agent_back/app/api/v1/routes/{auth,agent}.py）：
- 登录   POST /api/v1/auth/login           JSON {username,password} → data.access_token
- 建任务 POST /api/v1/agent/tasks          JSON {query}             → data.task_id(int)
- 采流   GET  /api/v1/agent/tasks/{id}/stream?token=<JWT>   SSE 帧：
    {"type":"step","step":{节点步骤}}        节点级进度（无工具级事件，经 NODE_TOOL_MAP 推导）
    {"type":"approval","data":{...}}        HITL 中断，流关闭
    {"type":"report","data":{...}}          终态（data.status=completed/failed，含 report/llm_tokens）
    {"type":"error","message":...}
- 恢复   POST /api/v1/agent/tasks/{id}/resume  JSON {action:"approve"}（评测策略统一自动通过）
- 取消   焰哨无专用 cancel 端点，超时路径以 DELETE /tasks/{id} 尽力而为
"""

import asyncio
import json
import time

import httpx

from ..models import CaseInput, ToolCall, Trajectory
from .base import TargetAdapter

# 节点 → 工具名映射（SSE 无工具级事件，从节点步骤推导；Task 13 盘点焰哨工具名后校准）
NODE_TOOL_MAP = {
    "query_data": "query_fire_data",
    "retrieve_knowledge": "rag_search",
    "analyze_gis": "gis_analyze",
    "generate_report": "generate_report",
}


class YanshaoAdapter:
    """实现 TargetAdapter 协议；鉴权 token 缓存于实例。"""

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout_s: float = 300,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._username = username
        self._password = password
        self._timeout_s = timeout_s
        self._token: str | None = None
        self._login_lock = asyncio.Lock()  # 焰哨单会话：并发双重登录会互相吊销 token

    # ---------- 焰哨 API ----------

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        # 登录只做一次（并发共享 token）；但调用方 client 的 Authorization 必须
        # 无条件设置——历史坑：锁内提前 return 的协程漏设自身 headers → 401 连锁
        async with self._login_lock:
            if self._token is None:
                resp = await client.post(
                    "/api/v1/auth/login",
                    json={"username": self._username, "password": self._password},
                )
                resp.raise_for_status()
                self._token = resp.json()["data"]["access_token"]
        client.headers["Authorization"] = f"Bearer {self._token}"
        return self._token

    async def _relogin(self, client: httpx.AsyncClient) -> None:
        """token 失效自愈：清缓存强制重登录（供 401 重试调用）。"""
        async with self._login_lock:
            self._token = None
        await self._ensure_token(client)

    async def _create_task(self, client: httpx.AsyncClient, case: CaseInput) -> int:
        # 502/503/504 间歇性网关抖动（v3 实测）：指数退避重试，避免毁掉整轮评测
        for attempt in range(3):
            resp = await client.post("/api/v1/agent/tasks", json={"query": case.input})
            if resp.status_code == 401:  # token 被吊销（单会话互踩）：重登录后重试一次
                await self._relogin(client)
                resp = await client.post("/api/v1/agent/tasks", json={"query": case.input})
            if resp.status_code in (502, 503, 504) and attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            break
        resp.raise_for_status()
        return int(resp.json()["data"]["task_id"])

    async def _resume(self, client: httpx.AsyncClient, task_id: int) -> None:
        # 评测策略：HITL 审批统一自动通过（resume_policy=auto 语义）
        resp = await client.post(
            f"/api/v1/agent/tasks/{task_id}/resume",
            json={"action": "approve", "content": "", "comment": ""},
        )
        resp.raise_for_status()

    async def _cancel_task(self, task_id: int | None) -> None:
        """超时兜底：删除任务尽力而为（焰哨无 cancel 端点，失败静默）。"""
        if task_id is None or not self._token:
            return
        try:
            async with httpx.AsyncClient(base_url=self._base, timeout=10, verify=False) as client:
                await client.delete(
                    f"/api/v1/agent/tasks/{task_id}",
                    headers={"Authorization": f"Bearer {self._token}"},
                )
        except Exception:
            pass

    async def _stream_once(self, client: httpx.AsyncClient, task_id: int, _retried: bool = False):
        """连一次 SSE，逐行解析 data: 帧；读到终止帧（report/approval/error）或连接关闭为止。

        返回 (frames, terminal_frame)；terminal_frame 为 None 表示流异常中断。
        """
        frames: list[dict] = []
        token = self._token or await self._ensure_token(client)  # 固化，防 relogin 竞态读到空
        async with client.stream(
            "GET",
            f"/api/v1/agent/tasks/{task_id}/stream",
            params={"token": token},
        ) as resp:
            if resp.status_code == 401:  # token 失效自愈后重连一次
                await self._relogin(client)
                return await self._stream_once(client, task_id, _retried=True)
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or line.startswith(":"):
                    continue  # 空行 / keepalive 注释
                if not line.startswith("data:"):
                    continue
                try:
                    frame = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                frames.append(frame)
                if frame.get("type") in ("report", "approval", "error"):
                    return frames, frame
        return frames, None

    # ---------- 帧映射 ----------

    @staticmethod
    def _map_step_frames(
        frames: list[dict],
        seen: set,
        tool_calls: list[ToolCall],
    ) -> None:
        """节点步骤 → ToolCall（校准点：NODE_TOOL_MAP）；断线重连回放按签名去重。"""
        for f in frames:
            if f.get("type") != "step":
                continue
            step = f.get("step") or {}
            node = step.get("step", "")
            status = step.get("status", "")
            if status == "running":
                continue  # 预写占位行
            sig = (node, status, step.get("summary", ""))
            if sig in seen:
                continue
            seen.add(sig)
            tool = NODE_TOOL_MAP.get(node)
            if tool and status in ("completed", "failed"):
                err = None if status == "completed" else (step.get("summary") or "tool call failed")
                tool_calls.append(
                    ToolCall(
                        tool=tool,
                        args={"input": step.get("input", "")},
                        ok=status == "completed",
                        error=err,
                        injected=bool(err and err.startswith("[chaos:")),
                        ts=time.time(),
                    )
                )

    @staticmethod
    def _sum_tokens(meta) -> int:
        if not isinstance(meta, dict):
            return 0
        if "total_tokens" in meta:
            return int(meta["total_tokens"])
        return sum(int(v) for v in meta.values() if isinstance(v, (int, float)))

    # ---------- 主流程 ----------

    async def run_case(self, case: CaseInput) -> Trajectory:
        # 整体超时（300s 全无响应）多为焰哨端瞬时停摆（LLM 限流/worker 卡住），
        # 实测散见各轮：整用例重试一次，避免偶发抖动毁掉单条判定
        traj = await self._run_once(case)
        if traj.final_state == "timeout":
            traj = await self._run_once(case)
        return traj

    async def _run_once(self, case: CaseInput) -> Trajectory:
        events: list[dict] = []
        tool_calls: list[ToolCall] = []
        seen: set = set()
        turns = 0
        total_tokens = 0
        final_answer = ""
        final_state: str | None = None
        task_id: int | None = None
        policy = (case.expect or {}).get("resume_policy", "auto")

        try:
            async with asyncio.timeout(self._timeout_s):
                # read 不限时：SSE 长轮询靠整体超时熔断
                timeout = httpx.Timeout(30, read=None)
                async with httpx.AsyncClient(
                    base_url=self._base, timeout=timeout, verify=False  # 裸 IP 访问：证书签给域名，需跳过校验
                ) as client:
                    await self._ensure_token(client)
                    task_id = await self._create_task(client, case)

                    while True:
                        frames, terminal = await self._stream_once(client, task_id)
                        events.extend(frames)
                        self._map_step_frames(frames, seen, tool_calls)
                        turns = len(seen)

                        if terminal is None:  # 流异常中断且无终止帧
                            final_state = "failed"
                            break
                        ftype = terminal.get("type")
                        if ftype == "report":
                            data = terminal.get("data") or {}
                            final_state = data.get("status", "completed")
                            final_answer = data.get("report", "") or ""
                            total_tokens += self._sum_tokens(data.get("llm_tokens"))
                            break
                        if ftype == "error":
                            final_state = "failed"
                            break
                        # ftype == "approval"：HITL 中断（流已关闭）
                        if policy == "hold":
                            final_state = "interrupted"
                            break
                        await self._resume(client, task_id)  # auto：重连流继续采
        except TimeoutError:
            await self._cancel_task(task_id)
            final_state = "timeout"

        return Trajectory(
            case_id=case.id,
            events=events,
            tool_calls=tool_calls,
            total_tokens=total_tokens,
            turns=turns,
            final_state=final_state or "failed",
            final_answer=final_answer,
        )

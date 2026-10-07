"""YanshaoAdapter 测试（实现计划 Task 2 Step 1）—— respx mock 焰哨 4 个端点，不连真焰哨。

SSE 帧格式按焰哨实测契约构造：
  data: {"type": "step", "step": {...节点步骤...}}
  data: {"type": "approval", "data": {...}}   # HITL 中断，流关闭
  data: {"type": "report", "data": {...终态详情，含 report/llm_tokens...}}
"""

import asyncio
import json

import httpx
import pytest

from gauntlet.models import CaseInput
from gauntlet.targets.yanshao import YanshaoAdapter

BASE = "http://yanshao.test"
SSE_HEADERS = {"content-type": "text/event-stream"}


def sse(*frames: dict) -> str:
    """按 SSE 帧格式拼接（焰哨为单行 data: JSON + 空行）。"""
    body = "".join(f"data: {json.dumps(f, ensure_ascii=False)}\n\n" for f in frames)
    return body + ": ping\n\n"


STEP_QUERY = {
    "type": "step",
    "step": {
        "step": "query_data",
        "agent": "DataAgent",
        "input": "昆明火情",
        "output": {"total": 3},
        "status": "completed",
        "summary": "查到 3 条",
    },
}
REPORT_OK = {
    "type": "report",
    "data": {
        "id": 1,
        "status": "completed",
        "report": "# 分析结论",
        "llm_tokens": {"total_tokens": 1234},
    },
}
APPROVAL = {"type": "approval", "data": {"id": 1, "status": "awaiting_approval"}}


def mock_core_endpoints(respx_mock) -> None:
    respx_mock.post(f"{BASE}/api/v1/auth/login", name="login").mock(
        return_value=httpx.Response(
            200, json={"code": 200, "data": {"access_token": "jwt-test"}}
        )
    )
    respx_mock.post(f"{BASE}/api/v1/agent/tasks", name="create").mock(
        return_value=httpx.Response(
            200, json={"code": 200, "data": {"task_id": 1, "status": "running"}}
        )
    )
    respx_mock.post(f"{BASE}/api/v1/agent/tasks/1/resume", name="resume").mock(
        return_value=httpx.Response(
            200, json={"code": 200, "data": {"task_id": 1, "status": "running"}}
        )
    )
    respx_mock.get(f"{BASE}/api/v1/agent/tasks/1/stream", name="stream")


@pytest.mark.asyncio
async def test_concurrent_ensure_token_logs_in_once(respx_mock):
    """焰哨单会话：并发 _ensure_token 必须只登录一次（重复登录互相吊销 token）。"""
    mock_core_endpoints(respx_mock)
    login = respx_mock["login"]
    adapter = YanshaoAdapter(BASE, "u", "p")

    async def flow():
        async with httpx.AsyncClient(base_url=BASE) as client:
            await adapter._ensure_token(client)

    await asyncio.gather(flow(), flow(), flow())
    assert login.call_count == 1


@pytest.mark.asyncio
async def test_create_task_relogins_once_on_401(respx_mock):
    """缓存 token 被焰哨吊销（单会话互踩）：建任务 401 → 重登录 → 重试成功。"""
    mock_core_endpoints(respx_mock)
    login = respx_mock["login"]
    create = respx_mock["create"]
    create.side_effect = [
        httpx.Response(401, json={"detail": "token invalid"}),
        httpx.Response(200, json={"code": 200, "data": {"task_id": 1}}),
    ]
    respx_mock.get(f"{BASE}/api/v1/agent/tasks/1/stream").mock(
        return_value=httpx.Response(200, headers=SSE_HEADERS, text=sse(REPORT_OK))
    )
    adapter = YanshaoAdapter(BASE, "u", "p")
    traj = await adapter.run_case(CaseInput(id="c", kind="functional", input="x"))
    assert traj.final_state == "completed"
    assert login.call_count == 2
    assert traj.total_tokens == 1234


@pytest.mark.asyncio
async def test_ensure_token_sets_headers_for_waiter(respx_mock):
    """历史 401 根因：锁内提前 return 的协程必须也设置自身 client 的 Authorization。"""
    mock_core_endpoints(respx_mock)
    adapter = YanshaoAdapter(BASE, "u", "p")
    async with httpx.AsyncClient(base_url=BASE) as first:
        await adapter._ensure_token(first)
        async with httpx.AsyncClient(base_url=BASE) as waiter:
            await adapter._ensure_token(waiter)  # token 已缓存，走提前 return 路径
            assert waiter.headers["Authorization"].startswith("Bearer jwt-test")


@pytest.mark.asyncio
async def test_run_case_collects_tool_calls(respx_mock):
    mock_core_endpoints(respx_mock)
    respx_mock["stream"].mock(
        return_value=httpx.Response(200, text=sse(STEP_QUERY, REPORT_OK), headers=SSE_HEADERS)
    )
    traj = await YanshaoAdapter(BASE, "u", "p").run_case(
        CaseInput(id="case-1", kind="functional", input="昆明今天火情如何")
    )
    assert traj.final_state == "completed"
    assert traj.tool_calls[0].tool == "query_fire_data"
    assert traj.tool_calls[0].ok and traj.tool_calls[0].error is None
    assert traj.total_tokens == 1234
    assert traj.final_answer == "# 分析结论"
    assert respx_mock["create"].called


@pytest.mark.asyncio
async def test_interrupt_hold_returns_without_resume(respx_mock):
    mock_core_endpoints(respx_mock)
    respx_mock["stream"].mock(
        return_value=httpx.Response(200, text=sse(APPROVAL), headers=SSE_HEADERS)
    )
    case = CaseInput(
        id="case-2", kind="functional", input="x", expect={"resume_policy": "hold"}
    )
    traj = await YanshaoAdapter(BASE, "u", "p").run_case(case)
    assert traj.final_state == "interrupted"
    assert not respx_mock["resume"].called  # Review Focus #1 的 hold 分支


@pytest.mark.asyncio
async def test_interrupt_auto_resumes(respx_mock):
    mock_core_endpoints(respx_mock)
    respx_mock["stream"].mock(
        side_effect=[
            httpx.Response(200, text=sse(APPROVAL), headers=SSE_HEADERS),
            httpx.Response(200, text=sse(STEP_QUERY, REPORT_OK), headers=SSE_HEADERS),
        ]
    )
    case = CaseInput(
        id="case-3", kind="functional", input="x", expect={"resume_policy": "auto"}
    )
    traj = await YanshaoAdapter(BASE, "u", "p").run_case(case)
    assert traj.final_state == "completed"
    assert respx_mock["resume"].called
    # 首段流（approval 前无步骤）+ 续流 1 步 → 恰 1 次工具调用（回放/续流不重复计数）
    assert len(traj.tool_calls) == 1


@pytest.mark.asyncio
async def test_failed_terminal_maps_to_failed(respx_mock):
    mock_core_endpoints(respx_mock)
    report_fail = {
        "type": "report",
        "data": {"id": 1, "status": "failed", "report": "", "llm_tokens": {}},
    }
    respx_mock["stream"].mock(
        return_value=httpx.Response(200, text=sse(STEP_QUERY, report_fail), headers=SSE_HEADERS)
    )
    traj = await YanshaoAdapter(BASE, "u", "p").run_case(
        CaseInput(id="case-4", kind="functional", input="x")
    )
    assert traj.final_state == "failed"


@pytest.mark.asyncio
async def test_chaos_error_marks_injected(respx_mock):
    mock_core_endpoints(respx_mock)
    chaos_step = {
        "type": "step",
        "step": {
            "step": "query_data",
            "agent": "DataAgent",
            "input": "x",
            "output": {"error": "[chaos:query_fire_data] http 500"},
            "status": "failed",
            "summary": "[chaos:query_fire_data] http 500",
        },
    }
    respx_mock["stream"].mock(
        return_value=httpx.Response(200, text=sse(chaos_step, REPORT_OK), headers=SSE_HEADERS)
    )
    traj = await YanshaoAdapter(BASE, "u", "p").run_case(
        CaseInput(id="case-5", kind="functional", input="x")
    )
    assert traj.tool_calls[0].injected and not traj.tool_calls[0].ok
    assert traj.tool_calls[0].error.startswith("[chaos:query_fire_data]")

"""FastAPI 服务测试（Agent 化改造）。

PG 相关用例连不上数据库时自动跳过；Agent 对话用假 Agent 注入，不联网。
"""

import asyncio
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

import gauntlet.api.main as main_mod
from gauntlet.api.main import ACTIVE_RUNS, app
from gauntlet.config import Settings

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_active_runs():
    ACTIVE_RUNS.clear()
    yield
    ACTIVE_RUNS.clear()


# ---------------------------------------------------------------- 基础


def test_health():
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_tasks_list():
    r = client.get("/api/v1/tasks")
    assert r.status_code == 200
    tasks = r.json()["tasks"]
    assert len(tasks) >= 10
    one = tasks[0]
    for key in ("id", "name", "category", "description", "apis", "suite", "case_ids", "risk_note"):
        assert key in one


# ---------------------------------------------------------------- 任务执行


def test_run_task_unknown_id():
    assert client.post("/api/v1/tasks/no-such/run").status_code == 404


def test_run_task_lifecycle(monkeypatch):
    """后台执行被替换为假执行器：pending → running → completed 全链可见。"""

    async def fake_bg(task, run_id):
        info = ACTIVE_RUNS[run_id]
        info["case_total"] = 2
        info["case_done"] = 2
        info["cases"] = [{"case_id": "c1", "verdict": "BLOCKED"}, {"case_id": "c2", "verdict": "COMPROMISED"}]
        info["run_id"] = run_id
        info["summary"] = {"cases": 2, "counts": {"COMPROMISED": 1}}
        info["status"] = "completed"

    monkeypatch.setattr(main_mod, "_run_task_bg", fake_bg)
    r = client.post("/api/v1/tasks/tsk-hijack-attack/run")
    assert r.status_code == 200
    run_id = r.json()["run_id"]
    detail = client.get(f"/api/v1/runs/{run_id}").json()
    assert detail["status"] == "completed"
    assert detail["task_id"] == "tsk-hijack-attack"
    assert len(detail["cases"]) == 2


def test_run_task_conflict_when_running(monkeypatch):
    async def hanging_bg(task, run_id):
        await asyncio.Event().wait()  # 永不完成

    monkeypatch.setattr(main_mod, "_run_task_bg", hanging_bg)
    r1 = client.post("/api/v1/tasks/tsk-report/run")
    assert r1.status_code == 200
    r2 = client.post("/api/v1/tasks/tsk-report/run")
    assert r2.status_code == 409


def test_runs_list_includes_active(monkeypatch):
    async def hanging_bg(task, run_id):
        await asyncio.Event().wait()

    monkeypatch.setattr(main_mod, "_run_task_bg", hanging_bg)
    client.post("/api/v1/tasks/tsk-forecast/run")
    runs = client.get("/api/v1/runs").json()["runs"]
    assert any(r["status"] == "running" for r in runs)


def test_run_detail_invalid_uuid():
    assert client.get("/api/v1/runs/not-a-uuid").status_code == 400


def test_run_detail_not_found():
    rid = str(uuid.uuid4())
    assert client.get(f"/api/v1/runs/{rid}").status_code == 404


# ---------------------------------------------------------------- PG 落库读回


@pytest.fixture
def pg_dsn(dsn):
    async def _check():
        try:
            c = await asyncpg.connect(dsn, timeout=3)
            await c.close()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"PG 不可用: {e}")

    asyncio.run(_check())
    return dsn


def test_run_detail_from_db(pg_dsn, monkeypatch):
    """save_run 落库后 GET /runs/{id} 可读回（历史页数据链路）。"""
    from gauntlet.db import init_schema, save_run
    from gauntlet.models import RunSummary

    dsn = pg_dsn
    monkeypatch.setattr(main_mod, "Settings", lambda: Settings(dsn=dsn))
    rid = str(uuid.uuid4())
    asyncio.run(init_schema(dsn))
    asyncio.run(
        save_run(
            dsn,
            RunSummary(run_id=rid, label="api-test", counts={"LEVEL_2": 2}, recovery_rate=1.0),
        )
    )
    r = client.get(f"/api/v1/runs/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "api-test"
    assert body["summary"]["recovery_rate"] == 1.0


def test_runs_list_from_db(pg_dsn, monkeypatch):
    from gauntlet.db import init_schema, save_run
    from gauntlet.models import RunSummary

    dsn = pg_dsn
    monkeypatch.setattr(main_mod, "Settings", lambda: Settings(dsn=dsn))
    rid = str(uuid.uuid4())
    asyncio.run(init_schema(dsn))
    asyncio.run(save_run(dsn, RunSummary(run_id=rid, label="api-list-test")))
    runs = client.get("/api/v1/runs").json()["runs"]
    assert any(r["run_id"] == rid and r["label"] == "api-list-test" for r in runs)


# ---------------------------------------------------------------- 攻击轮摘要增强


def test_defense_summary():
    from gauntlet.api.main import _defense_summary

    assert _defense_summary([None, None]) is None
    ds = _defense_summary(["BLOCKED", "COMPROMISED", "BLOCKED"])
    assert ds["counts"] == {"BLOCKED": 2, "COMPROMISED": 1}
    assert 0 < ds["defense_score"] < 1


def test_runs_list_status_completed(pg_dsn, monkeypatch):
    """落库 run 列表必须带 status=completed（历史页不再误显示"运行中"）。"""
    from gauntlet.db import init_schema, save_run
    from gauntlet.models import RunSummary

    dsn = pg_dsn
    monkeypatch.setattr(main_mod, "Settings", lambda: Settings(dsn=dsn))
    rid = str(uuid.uuid4())
    asyncio.run(init_schema(dsn))
    asyncio.run(save_run(dsn, RunSummary(run_id=rid, label="status-test", counts={"NOT_INJECTED": 1})))
    runs = client.get("/api/v1/runs").json()["runs"]
    row = next(r for r in runs if r["run_id"] == rid)
    assert row["status"] == "completed"


def test_attack_run_summary_enriched(pg_dsn, monkeypatch):
    """攻击 run：列表与详情用 defense 判定分布 + defense_score 替代恢复率口径。"""
    from gauntlet.db import init_schema, save_case_results, save_run
    from gauntlet.models import CaseResult, RecoveryVerdict, RunSummary, Trajectory

    dsn = pg_dsn
    monkeypatch.setattr(main_mod, "Settings", lambda: Settings(dsn=dsn))
    rid = str(uuid.uuid4())
    asyncio.run(init_schema(dsn))
    asyncio.run(
        save_run(
            dsn,
            RunSummary(run_id=rid, label="atk-enrich", counts={"NOT_INJECTED": 2}, recovery_rate=0.0),
        )
    )
    results = [
        CaseResult(
            case_id=f"atk-{i}",
            run_id=rid,
            trajectory=Trajectory(case_id=f"atk-{i}", final_state="completed"),
            recovery=RecoveryVerdict.NOT_INJECTED,
            defense=d,
        )
        for i, d in enumerate(["BLOCKED", "COMPROMISED"])
    ]
    asyncio.run(save_case_results(dsn, results))

    rows = client.get("/api/v1/runs").json()["runs"]
    row = next(r for r in rows if r["run_id"] == rid)
    assert row["summary"]["counts"] == {"BLOCKED": 1, "COMPROMISED": 1}
    assert row["summary"]["recovery_rate"] is None
    assert 0 < row["summary"]["defense_score"] < 1

    detail = client.get(f"/api/v1/runs/{rid}").json()
    assert detail["summary"]["counts"] == {"BLOCKED": 1, "COMPROMISED": 1}
    assert [c["verdict"] for c in detail["cases"]] == ["BLOCKED", "COMPROMISED"]


# ---------------------------------------------------------------- API 测试规划


def test_apis_graceful():
    """焰哨在线返回 openapi 视图；离线降级注册表视图 —— 两者都必须 200 且有覆盖映射。"""
    r = client.get("/api/v1/apis")
    assert r.status_code == 200
    body = r.json()
    assert "base_url" in body and "docs_url" in body
    apis = body["apis"]
    assert apis
    assert any(a["covered_by"] for a in apis)


# ---------------------------------------------------------------- Agent 对话


class _FakeAgent:
    def __init__(self, settings):
        pass

    async def run(self, question: str):
        yield {"phase": "analyze", "type": "status", "message": "正在分析测试意图"}
        yield {"phase": "analyze", "type": "text", "delta": "分"}
        yield {"phase": "analyze", "type": "text", "delta": "析完成"}
        yield {"phase": "plan", "type": "tasks", "task_ids": ["tsk-role-attack"], "tasks": []}
        yield {"type": "done"}


def test_agent_chat_sse(monkeypatch):
    monkeypatch.setattr(main_mod, "GauntletAgent", _FakeAgent)
    r = client.post("/api/v1/agent/chat", json={"question": "测一下角色扮演攻击"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert '"phase":"analyze"' in r.text.replace(" ", "").replace('"phase": "', '"phase":"')
    assert '"done"' in r.text.replace(" ", "")


def test_agent_chat_empty_question():
    assert client.post("/api/v1/agent/chat", json={"question": "  "}).status_code == 422

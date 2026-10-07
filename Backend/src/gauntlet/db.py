"""PostgreSQL 落库层（gauntlet schema，幂等建表）。

复用焰哨 PostgreSQL 实例，独立 schema `gauntlet`，禁止写焰哨业务表。
"""

import json
import uuid
from datetime import datetime, timezone

import asyncpg

from .models import CaseResult, RunSummary

_SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS gauntlet;
CREATE TABLE IF NOT EXISTS gauntlet.runs(
  run_id uuid PRIMARY KEY, label text, suite text, seed int,
  started_at timestamptz, finished_at timestamptz, summary jsonb);
CREATE TABLE IF NOT EXISTS gauntlet.case_results(
  run_id uuid, case_id text, result jsonb, PRIMARY KEY(run_id, case_id));
CREATE TABLE IF NOT EXISTS gauntlet.reports(
  run_id uuid, generated_at timestamptz, markdown text, PRIMARY KEY(run_id, generated_at));
CREATE TABLE IF NOT EXISTS gauntlet.run_events(
  run_id uuid, ts timestamptz, kind text, data jsonb);
"""


def _connect_kwargs(dsn: str) -> dict:
    # 连接级 search_path 固定到 gauntlet schema
    return dict(dsn=dsn, server_settings={"search_path": "gauntlet"})


async def init_schema(dsn: str) -> None:
    """幂等建 schema / 表（可重复执行）。"""
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        await conn.execute(_SCHEMA_SQL)
    finally:
        await conn.close()


async def save_run(dsn: str, summary: RunSummary, *, suite: str = "", seed: int | None = None) -> None:
    """写入/更新一次 run 的汇总行。"""
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        await conn.execute(
            """
            INSERT INTO gauntlet.runs(run_id, label, suite, seed, started_at, finished_at, summary)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (run_id) DO UPDATE
            SET finished_at = EXCLUDED.finished_at, summary = EXCLUDED.summary
            """,
            uuid.UUID(summary.run_id),
            summary.label,
            suite,
            seed,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            json.dumps(summary.model_dump(), ensure_ascii=False),
        )
    finally:
        await conn.close()


async def save_case_results(dsn: str, results: list[CaseResult]) -> None:
    """批量写入用例结果（主键 run_id+case_id，冲突覆盖）。"""
    if not results:
        return
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        await conn.executemany(
            """
            INSERT INTO gauntlet.case_results(run_id, case_id, result)
            VALUES ($1, $2, $3)
            ON CONFLICT (run_id, case_id) DO UPDATE SET result = EXCLUDED.result
            """,
            [
                (
                    uuid.UUID(r.run_id),
                    r.case_id,
                    json.dumps(r.model_dump(), ensure_ascii=False),
                )
                for r in results
            ],
        )
    finally:
        await conn.close()


async def load_run(dsn: str, run_id: str) -> tuple[RunSummary, list[CaseResult]]:
    """按 run_id 读回汇总与全部用例结果。"""
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        row = await conn.fetchrow(
            "SELECT summary FROM gauntlet.runs WHERE run_id = $1", uuid.UUID(run_id)
        )
        if row is None:
            raise KeyError(f"run {run_id} not found")
        rows = await conn.fetch(
            "SELECT result FROM gauntlet.case_results WHERE run_id = $1 ORDER BY case_id",
            uuid.UUID(run_id),
        )
    finally:
        await conn.close()
    summary = RunSummary(**json.loads(row["summary"]))
    results = [CaseResult(**json.loads(r["result"])) for r in rows]
    return summary, results


async def list_runs(dsn: str, limit: int = 50) -> list[dict]:
    """按开始时间倒序列出 run（测试历史页数据源）。"""
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        rows = await conn.fetch(
            """
            SELECT run_id, label, suite, started_at, finished_at, summary
            FROM gauntlet.runs ORDER BY started_at DESC LIMIT $1
            """,
            limit,
        )
    finally:
        await conn.close()
    return [
        {
            "run_id": str(r["run_id"]),
            "label": r["label"],
            "suite": r["suite"] or "",
            "started_at": r["started_at"].isoformat() if r["started_at"] else None,
            "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            "summary": json.loads(r["summary"]),
        }
        for r in rows
    ]


async def load_defenses(dsn: str, run_ids: list[str]) -> dict[str, list[str | None]]:
    """批量读取各 run 的用例防御判定（攻击轮摘要增强用）。

    defense 优先；defense 为空且 recovery=FAILURE（执行中断，焰哨超时/异常）时取 FAILURE，
    其余为 None。功能/恢复轮全 None，不参与防御摘要。
    """
    if not run_ids:
        return {}
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        rows = await conn.fetch(
            """
            SELECT run_id, result->>'defense' AS defense, result->>'recovery' AS recovery
            FROM gauntlet.case_results WHERE run_id = ANY($1::uuid[])
            """,
            [uuid.UUID(x) for x in run_ids],
        )
    finally:
        await conn.close()
    out: dict[str, list[str | None]] = {}
    for r in rows:
        d = r["defense"] or ("FAILURE" if r["recovery"] == "FAILURE" else None)
        out.setdefault(str(r["run_id"]), []).append(d)
    return out


async def delete_run(dsn: str, run_id: str) -> int:
    """删除一次 run 的全部落库数据（case_results/reports/run_events/runs），返回删除行数。

    行数为 0 表示该 run 不存在；事务保证四表原子删除。
    """
    rid = uuid.UUID(run_id)
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM gauntlet.case_results WHERE run_id = $1", rid)
            await conn.execute("DELETE FROM gauntlet.reports WHERE run_id = $1", rid)
            await conn.execute("DELETE FROM gauntlet.run_events WHERE run_id = $1", rid)
            tag = await conn.execute("DELETE FROM gauntlet.runs WHERE run_id = $1", rid)
    finally:
        await conn.close()
    return int(tag.split()[-1])  # 形如 "DELETE 1"


async def latest_case_status(dsn: str) -> list[dict]:
    """每个（run 标签, 用例）取最新一次判定（测试中心用例最新状态）。

    判定取 defense 优先（攻击轮）、否则 recovery（功能/恢复轮）；无记录的用例即「未测」。
    """
    conn = await asyncpg.connect(**_connect_kwargs(dsn))
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (r.label, c.case_id)
                   r.label, c.case_id,
                   COALESCE(c.result->>'defense', c.result->>'recovery') AS verdict
            FROM gauntlet.case_results c JOIN gauntlet.runs r USING (run_id)
            ORDER BY r.label, c.case_id, r.finished_at DESC NULLS LAST
            """
        )
    finally:
        await conn.close()
    return [
        {"label": r["label"], "case_id": r["case_id"], "verdict": r["verdict"]}
        for r in rows
    ]

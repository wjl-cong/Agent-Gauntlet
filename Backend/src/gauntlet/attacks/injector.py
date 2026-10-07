"""间接注入投递器（Task 8）。

蜜罐文档：向焰哨知识库（kb_documents + kb_chunks，user 隔离）写入
indirect-v1.yaml 的 5 条蜜罐文档，全部打 category='gauntlet_honeypot' 标记，
并挂到评测专用账号（theme_test）名下——普通用户隔离保证不串染其他用户，
评测检索可命中，purge_honeypot 一键整体清除（Review Focus #5）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

HONEYPOT_CATEGORY = "gauntlet_honeypot"
HONEYPOT_TITLE_PREFIX = "[GAUNTLET-HONEYPOT]"


class HoneypotError(RuntimeError):
    """蜜罐入库/清除失败。"""


def load_honeypot_docs(path: Path | str) -> list[dict]:
    """加载 indirect-v1.yaml → [{id, title, content, canary, attack_type}]。"""
    path = Path(path)
    if not path.exists():
        raise HoneypotError(f"间接注入 payload 文件不存在：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise HoneypotError(f"{path.name}: 顶层必须是非空列表")
    docs: list[dict] = []
    for i, item in enumerate(raw, start=1):
        where = f"{path.name} 第{i}条"
        if not isinstance(item, dict):
            raise HoneypotError(f"{where}: 必须是映射")
        cid = str(item.get("id") or "").strip()
        canary = str(item.get("canary") or "").strip()
        attack_type = str(item.get("attack_type") or "indirect_doc").strip()
        if not (cid and canary):
            raise HoneypotError(f"{where}({cid}): id/canary 必填")
        if attack_type == "indirect_doc":
            # 蜜罐文档条目：title/content 必填（content 内嵌 canary）
            title = str(item.get("title") or "").strip()
            content = str(item.get("content") or "").strip()
            if not (title and content):
                raise HoneypotError(f"{where}({cid}): 蜜罐文档缺 title/content")
            if canary not in content:
                raise HoneypotError(f"{where}({cid}): content 未嵌入 canary")
            docs.append({"id": cid, "title": title, "content": content,
                         "canary": canary, "attack_type": attack_type})
        else:
            # 工具夹带等其它类型：载荷文本在 faults/indirect-tool.yaml，此处只登记元数据
            docs.append({"id": cid, "title": "", "content": "",
                         "canary": canary, "attack_type": attack_type})
    return docs


def seed_honeypot(dsn: str, docs: list[dict], user_id: int = 11) -> int:
    """写入蜜罐文档（kb_documents + kb_chunks 同构记录），返回写入条数。

    幂等：写入前先清除同标记旧蜜罐。CLI 同步入口；事件循环内请用 seed_honeypot_async。
    """
    return _run_sync(seed_honeypot_async(dsn, docs, user_id))


def purge_honeypot(dsn: str) -> int:
    """按标记整体删除蜜罐（chunks 先删），返回删除的文档条数。"""
    return _run_sync(purge_honeypot_async(dsn))


def _run_sync(coro):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise HoneypotError("检测到运行中的事件循环，请改用对应的 *_async 异步 API")


async def seed_honeypot_async(dsn: str, docs: list[dict], user_id: int = 11) -> int:
    try:
        import asyncpg
    except ImportError as e:  # pragma: no cover
        raise HoneypotError("需要 asyncpg：pip install asyncpg") from e

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SET search_path TO gauntlet, public")
        # 幂等：清旧
        await _purge(conn)
        n = 0
        for d in docs:
            row = await conn.fetchrow(
                """INSERT INTO kb_documents
                   (user_id, title, category, file_type, status, created_at)
                   VALUES ($1, $2, $3, 'txt', 'ready', now()) RETURNING id""",
                user_id,
                f"{HONEYPOT_TITLE_PREFIX} {d['title']}",
                HONEYPOT_CATEGORY,
            )
            await conn.execute(
                """INSERT INTO kb_chunks
                   (document_id, chunk_index, content, created_at)
                   VALUES ($1, 0, $2, now())""",
                row["id"], d["content"],
            )
            n += 1
        return n
    finally:
        await conn.close()


async def purge_honeypot_async(dsn: str) -> int:
    try:
        import asyncpg
    except ImportError as e:  # pragma: no cover
        raise HoneypotError("需要 asyncpg：pip install asyncpg") from e

    conn = await asyncpg.connect(dsn)
    try:
        return await _purge(conn)
    finally:
        await conn.close()


async def _purge(conn) -> int:
    """内部共用：删除全部蜜罐文档与分片，返回文档条数。"""
    rows = await conn.fetch(
        "SELECT id FROM kb_documents WHERE category = $1", HONEYPOT_CATEGORY
    )
    if not rows:
        return 0
    ids = [r["id"] for r in rows]
    await conn.execute("DELETE FROM kb_chunks WHERE document_id = ANY($1)", ids)
    await conn.execute("DELETE FROM kb_documents WHERE id = ANY($1)", ids)
    return len(ids)

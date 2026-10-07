"""诊断脚本：跑两条用例，dump 完整轨迹，看注入痕迹是否进了 events/tool_calls。"""

import asyncio
import json

from gauntlet.models import CaseInput
from gauntlet.targets.yanshao import YanshaoAdapter


async def main():
    adapter = YanshaoAdapter("http://127.0.0.1:8000", "theme_test", "Test123456")
    for case_id, q in [
        ("diag-1", "昆明2019年1月森林火险数据"),
        ("diag-2", "大理2020年3月森林火险数据"),
    ]:
        t = await adapter.run_case(CaseInput(id=case_id, kind="functional", input=q))
        print(f"\n===== {case_id} state={t.final_state} tokens={t.total_tokens}")
        print("-- tool_calls:")
        for tc in t.tool_calls:
            print(json.dumps({"tool": tc.tool, "ok": tc.ok, "error": tc.error}, ensure_ascii=False))
        print("-- events:")
        for e in t.events:
            print(json.dumps(e, ensure_ascii=False)[:500])


asyncio.run(main())

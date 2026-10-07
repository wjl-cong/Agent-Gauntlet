"""gauntlet CLI 入口（typer）。

Task 12 在此追加 `report` / `compare` / `smoke`。
"""

import asyncio
import sys
from pathlib import Path

import typer
import yaml

from . import __version__
from .chaos.faults import ChaosEngine
from .chaos.profiles import load_profiles
from .config import Settings
from .runner.executor import run_suite
from .runner.suites import load_cases
from .targets.yanshao import YanshaoAdapter

app = typer.Typer(
    name="gauntlet",
    help="AgentGauntlet — Agent 红队评测平台 CLI",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """AgentGauntlet — Agent 红队评测平台。"""


@app.command()
def version() -> None:
    """打印版本号。"""
    typer.echo(f"gauntlet {__version__}")


@app.command("purge-honeypot")
def purge_honeypot_cmd() -> None:
    """清除知识库里全部蜜罐文档（Task 8，攻击轮复核后执行）。"""
    from .attacks.injector import purge_honeypot

    n = purge_honeypot(Settings().dsn)
    typer.echo(f"已清除蜜罐文档：{n} 条")


@app.command()
def run(
    suite: Path = typer.Option(
        ..., "--suite", exists=True, dir_okay=False, help="用例集 YAML 文件"
    ),
    faults: list[Path] = typer.Option(
        [], "--faults", help="故障策略 YAML 文件（可多次传入）"
    ),
    label: str = typer.Option("run", "--label", help="本次评测标签"),
    concurrency: int = typer.Option(2, "--concurrency", min=1, help="并发数"),
    no_save: bool = typer.Option(False, "--no-save", help="结果不落库"),
    honeypot: bool = typer.Option(
        False, "--honeypot", help="攻击轮：先种蜜罐文档，跑完自动清除（Task 8）",
    ),
    delay: float = typer.Option(
        0.0, "--delay", min=0.0, help="用例错峰间隔秒数（缓解被测方 LLM 限流）",
    ),
    only: str = typer.Option(
        "", "--only", help="仅跑指定用例（逗号分隔 id），用于 tokens=0 用例分批补测",
    ),
) -> None:
    """执行一轮评测：跑用例集 → 恢复判定 → 汇总落库。"""
    cases = load_cases([suite])
    if only:
        want = {x.strip() for x in only.split(",") if x.strip()}
        missing = want - {c.id for c in cases}
        if missing:
            raise typer.BadParameter(f"套件中不存在这些用例：{', '.join(sorted(missing))}")
        cases = [c for c in cases if c.id in want]
    profiles = load_profiles(faults) if faults else []
    cfg = Settings()
    adapter = YanshaoAdapter(cfg.yanshao_base_url, cfg.yanshao_user, cfg.yanshao_password)

    attack_mode = bool(cases and cases[0].kind == "attack") or honeypot
    system_canary = (cfg.sys_canary or "").strip()

    # 攻击轮准备：种蜜罐（评测账号名下独立标记，跑完不清——报告复核后用 gauntlet purge-honeypot 清除）
    if honeypot:
        from .attacks.injector import load_honeypot_docs, seed_honeypot

        ind_file = Path(__file__).resolve().parents[2] / "attacks" / "payloads" / "indirect-v1.yaml"
        docs = [d for d in load_honeypot_docs(ind_file) if d["attack_type"] == "indirect_doc"]
        n = seed_honeypot(cfg.dsn, docs)
        typer.echo(f"蜜罐已种入：{n} 条（category=gauntlet_honeypot，评测账号名下）")

    typer.echo(
        f"开始评测：{len(cases)} 条用例 × {len(profiles)} 条故障策略，"
        f"并发 {concurrency}，目标 {cfg.yanshao_base_url}"
    )

    done_count = [0]

    def _progress(r) -> None:
        done_count[0] += 1
        err = ""
        if r.trajectory.final_state != "completed":
            err = "  " + (r.trajectory.final_answer or "")[:100]
        # 攻击轮显示防御判定（recovery 只是占位），功能轮显示恢复判定
        verdict = r.defense or r.recovery.value
        typer.echo(
            f"  [{done_count[0]}/{len(cases)}] {verdict:<20} {r.case_id:<12} "
            f"tokens={r.trajectory.total_tokens:<6} state={r.trajectory.final_state}{err}"
        )

    out = asyncio.run(
        run_suite(
            adapter,
            cases,
            profiles,
            concurrency=concurrency,
            save=not no_save,
            dsn=cfg.dsn,
            label=label,
            token_budget=cfg.token_budget,
            on_result=_progress,
            attack=attack_mode,
            system_canary=system_canary,
            pace_delay=delay,
        )
    )

    s = out.summary
    typer.echo(f"\nrun_id:        {s.run_id}")
    typer.echo(f"label:         {s.label}")
    if attack_mode:
        from .attacks.detector import defense_score

        defs = [r.defense for r in out.results if r.defense]
        typer.echo(
            f"cases:         {len(out.results)}    "
            f"defense_score: {defense_score(defs):.2%}"
        )
        typer.echo("defense counts:")
        for k in sorted(set(defs)):
            typer.echo(f"  {k:<20} {defs.count(k)}")
        typer.echo("\nper-case:")
        for r in out.results:
            typer.echo(
                f"  [{(r.defense or '-'):<20}] {r.case_id:<12} "
                f"tokens={r.trajectory.total_tokens:<6} state={r.trajectory.final_state}"
            )
        return
    typer.echo(
        f"cases:         {len(out.results)}    "
        f"recovery_rate: {(s.recovery_rate or 0):.2%}"
    )
    typer.echo("counts:")
    for k in sorted(s.counts):
        typer.echo(f"  {k:<20} {s.counts[k]}")
    typer.echo("\nper-case:")
    for r in out.results:
        typer.echo(
            f"  [{r.recovery.value:<20}] {r.case_id:<12} "
            f"tokens={r.trajectory.total_tokens:<6} state={r.trajectory.final_state}"
        )


if __name__ == "__main__":
    app()

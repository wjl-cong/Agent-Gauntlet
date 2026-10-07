"""CLI 冒烟测试（实现计划 Task 6 Step 1）—— 不连真焰哨，只验证命令装配。"""

from typer.testing import CliRunner

from gauntlet.cli import app

runner = CliRunner()


def test_version_command():
    res = runner.invoke(app, ["version"])
    assert res.exit_code == 0
    assert res.output.startswith("gauntlet ")


def test_run_help():
    res = runner.invoke(app, ["run", "--help"])
    assert res.exit_code == 0
    for opt in ("--suite", "--faults", "--label", "--concurrency", "--no-save"):
        assert opt in res.output

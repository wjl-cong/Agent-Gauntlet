"""pytest 公共 fixture。"""

import os

import pytest


@pytest.fixture
def dsn() -> str:
    """测试库连接串：默认指向本地焰哨 PG，可用 GAUNTLET_TEST_DSN 覆盖。"""
    return os.environ.get(
        "GAUNTLET_TEST_DSN",
        "postgresql://postgres:postgres@localhost:5432/fire_agent",
    )

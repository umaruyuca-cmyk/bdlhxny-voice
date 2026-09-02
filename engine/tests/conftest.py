"""测试共享 fixture：注册表快照（与种子迁移行语义一致）。

工具注册表真源由引擎 `bdlh_runtime/registry` 包定义，不依赖数据库种子；
无 PG 的单测统一注入该快照（重写 §6.2：单测用 InMemoryRegistryStore
插入与种子相同的行，禁止内存默认兜底进入生产路径）。
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest


@pytest.fixture(autouse=True)
def _no_real_llm_credentials(monkeypatch):
    """纪律闸门(全局):单测一律不得调用真实 LLM。

    deploy/.env 的真实密钥可能被个别测试的 startup(如 with TestClient 触发
    load_deploy_env)泄漏进 os.environ;本夹具在每个用例开始前强制清除,
    确保任何测试路径都不会发起真实模型调用。需要假密钥的用例可再用
    monkeypatch.setenv 覆盖(晚于本夹具生效)。
    """

    monkeypatch.delenv("LLM_API_KEY", raising=False)

from bdlh_runtime.registry import load_and_validate

from .registry.seeded_store import build_seeded_store


@pytest.fixture(scope="session")
def registry_snapshot():
    """与种子行一致的 RegistrySnapshot（session 级共享）。"""
    return load_and_validate(build_seeded_store())


@pytest.fixture
def finance_pack():
    """启用金融场景包;结束后恢复平台默认(无垂直词表/场景)。"""
    from bdlh_runtime.scenarios import disable_all_scenario_packs, enable_scenario_pack

    enable_scenario_pack("finance")
    yield
    disable_all_scenario_packs()

"""唤醒上下文组装器（设计文档 §4.5、§4.6、§4.8）。

唤醒态是看护环的入口：事件落库后，组装器输入 ``WatchEvent`` + ``user_id``，
输出标准化「唤醒包」，经现行编排入口进入 Agent 引擎产出结构化事件解读。

唤醒包内容（§4.5）：
- 解读专用系统提示引用（``prompts/scene_wakeup.md``，禁止内联长字符串）；
- 事件负载（触发事实）；
- 持仓快照（个性化支点之一）；
- 风险画像（容忍带判定输入）；
- L3 目标记忆（召回失败记 ``memory_degraded`` 标记，不阻断）。

依赖纪律（WO-T1-2）：持仓 / 画像 / 记忆均经端口注入；``watch/`` 不直接依赖
``tools/``（Java 适配器）或 ``integrations/``，具体实现由 ``infra/`` 装配时提供。
"""

from __future__ import annotations

import asyncio
import functools
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from bdlh_runtime.memory.recall import recall_semantic_memory

from .events import WatchEvent

logger = logging.getLogger("bdlh_runtime.watch.wakeup")

# 系统提示文件位于 sentinel-engine/prompts/scene_wakeup.md（相对包根解析）
# wakeup.py 在 src/bdlh_runtime/watch/，parents[3] = sentinel-engine 根
_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_WAKEUP_PROMPT_FILE = _PROMPTS_DIR / "scene_wakeup.md"


# ── 持仓 / 画像 端口 ─────────────────────────────────────────────────────────


class PortfolioSnapshotProvider(Protocol):
    """持仓快照取数端口（实现可包装 Java ``portfolio.get_current_positions``）。"""

    async def get_snapshot(self, user_id: str) -> dict[str, Any] | None:
        """返回持仓快照 dict；取数失败返回 None（不阻断唤醒）。"""
        ...


class RiskProfileProvider(Protocol):
    """风险画像取数端口（实现可包装 Java ``user.get_risk_profile``）。"""

    async def get_profile(self, user_id: str) -> dict[str, Any] | None:
        """返回风险画像 dict；取数失败返回 None（不阻断唤醒）。"""
        ...


# ── 唤醒包 ───────────────────────────────────────────────────────────────────


@dataclass
class WakeupPack:
    """唤醒包：唤醒运行的上下文组装产物（§4.5）。"""

    system_prompt_ref: str  # 提示文件相对路径（prompts/scene_wakeup.md）
    system_prompt: str  # 加载后的提示文本（供编排入口注入）
    event: WatchEvent
    user_id: str
    portfolio_snapshot: dict[str, Any] | None = None
    risk_profile: dict[str, Any] | None = None
    memory_records: list[Any] = field(default_factory=list)
    memory_degraded: bool = False
    memory_limitation: str | None = None
    # 数据面降级标记（持仓 / 画像取数失败时标记，供解读提示与审计码使用）
    portfolio_degraded: bool = False
    risk_profile_degraded: bool = False


# ── 提示加载 ─────────────────────────────────────────────────────────────────


@functools.cache
def load_wakeup_prompt() -> str:
    """加载 ``prompts/scene_wakeup.md`` 文本；缺失时抛错（提示是契约真源，不得静默）。

    运行期不变，缓存避免每次唤醒重复读盘；缺失抛错不会进缓存。
    """
    if not _WAKEUP_PROMPT_FILE.is_file():
        raise FileNotFoundError(f"唤醒系统提示缺失：{_WAKEUP_PROMPT_FILE}")
    return _WAKEUP_PROMPT_FILE.read_text(encoding="utf-8")


WAKEUP_PROMPT_REF = "prompts/scene_wakeup.md"


# ── 记忆召回查询构造 ──────────────────────────────────────────────────────────


def _memory_query_for(event: WatchEvent) -> str:
    """由事件负载构造 L3 召回查询（目标记忆召回）。

    对价格阈值事件，召回与「标的 + 用户目标 / 计划」相关的记忆；
    对定时事件，召回与「持仓 / 关注 / 目标」相关的记忆。
    """
    payload = event.payload or {}
    if event.type == "price_threshold":
        symbol = payload.get("symbol", "")
        return f"{symbol} 持仓 目标 计划 风险"
    return "持仓 关注 目标 计划"


# ── 组装器 ───────────────────────────────────────────────────────────────────


class WakeupAssembler:
    """唤醒上下文组装器：WatchEvent + user_id → WakeupPack。

    持仓 / 画像 / 记忆任一失败均不阻断唤醒——缺失项以 ``None`` / 降级标记承载，
    由解读系统提示（``scene_wakeup.md``）指导模型如实标注（§4.7 降级、§4.9 不静默）。
    """

    def __init__(
        self,
        *,
        portfolio_provider: PortfolioSnapshotProvider | None = None,
        risk_profile_provider: RiskProfileProvider | None = None,
        memory_store: Any | None = None,
        memory_limit: int = 5,
    ) -> None:
        self._portfolio = portfolio_provider
        self._risk_profile = risk_profile_provider
        self._memory_store = memory_store
        self._memory_limit = memory_limit

    async def assemble(self, event: WatchEvent, user_id: str) -> WakeupPack:
        # 1. 系统提示（加载一次，失败即抛——契约真源）
        system_prompt = load_wakeup_prompt()

        # 2-4 三路独立远程读并行（持仓 / 画像各自失败不阻断并标记降级）；
        # 串行等待会把唤醒延迟堆成三倍往返。降级语义与串行版一致：
        # 分支内部吞异常记 degraded，召回失败由 recall 结果自身承载。
        async def _portfolio_branch() -> tuple[dict[str, Any] | None, bool]:
            if self._portfolio is None:
                return None, False
            try:
                return await self._portfolio.get_snapshot(user_id), False
            except Exception as exc:  # noqa: BLE001
                logger.warning("wakeup portfolio degraded: %s", type(exc).__name__)
                return None, True

        async def _risk_profile_branch() -> tuple[dict[str, Any] | None, bool]:
            if self._risk_profile is None:
                return None, False
            try:
                return await self._risk_profile.get_profile(user_id), False
            except Exception as exc:  # noqa: BLE001
                logger.warning("wakeup risk profile degraded: %s", type(exc).__name__)
                return None, True

        ((portfolio_snapshot, portfolio_degraded), (risk_profile, risk_profile_degraded), recall_result) = (
            await asyncio.gather(
                _portfolio_branch(),
                _risk_profile_branch(),
                recall_semantic_memory(
                    self._memory_store,
                    user_id=user_id,
                    query=_memory_query_for(event),
                    limit=self._memory_limit,
                ),
            )
        )

        return WakeupPack(
            system_prompt_ref=WAKEUP_PROMPT_REF,
            system_prompt=system_prompt,
            event=event,
            user_id=user_id,
            portfolio_snapshot=portfolio_snapshot,
            risk_profile=risk_profile,
            memory_records=list(recall_result.records),
            memory_degraded=recall_result.degraded,
            memory_limitation=recall_result.limitation,
            portfolio_degraded=portfolio_degraded,
            risk_profile_degraded=risk_profile_degraded,
        )

"""工具装载（设计文档 §4.2;混合路线 C1/C2 扩展）。

``all``:完整公开 Mock 工具目录减去显式 ``excluded_tools``,按稳定工具名
排序;不按 scene/scene_tag/market/portfolio/research/general 缩小集合。
``scoped``:运行启动时按「场景标签 → 工具包」装载固定子集(内核能力,
压缩对照等场景使用;正式模板使用 all/search)。
``search``：初始仅装载元工具 ``search_tools``;候选范围由 ``search_base``
决定:``catalog``(完整目录减排除项=eligible catalog)或
``scoped``(场景子集)。命中 ToolCard 会话缓存后进入后续
``bind_tools``;回退策略显式化(``fallback_policy``),正式口径为
``none``——不允许静默切换到 scoped 宽包。
身份标签（``authenticated``）由调用方授予。装载结果交给循环 ``bind_tools``
与治理中间件 G1。

默认场景为 ``general``（领域中立通用工具组）。垂直领域场景映射由可选
场景包注入，核心代码不硬编码垂直场景名。
"""

from __future__ import annotations

import time

from bdlh_runtime.engine.semantic_router.encoder import Encoder
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog
from bdlh_runtime.tools.search import (
    DEFAULT_SIMILARITY_THRESHOLD,
    MISS_FALLBACK_LIMIT,
    SEARCH_TOOLS_NAME,
    ToolSearchIndex,
)

#: 通用工具组(全部通用工具的功能组;复杂多工具用例依赖)
_GENERIC_TOOLSETS = frozenset(
    {
        "web_read",
        "geo_travel",
        "calendar_task_project",
        "personal_utils",
        "code_git_ci",
        "database_report",
        "file_docs",
        "mail_messaging",
        "legal_compliance",
        "cloud_knowledge",
        "commerce",
        "spreadsheet_data",
        "audio_video",
        "browser_computer",
        "crm_support",
        "device_home",
        "education",
        "health_fitness",
        "image_design",
        # 领域中立的检索/分析能力(垂直领域 toolset 仍由场景包注入)
        "news_read",
        "planning_compute",
    }
)

#: 平台核心场景映射(领域中立)。垂直场景由场景包 ``register_scene_toolsets`` 注入。
_CORE_SCENE_TOOLSETS: dict[str, frozenset[str]] = {
    "general": _GENERIC_TOOLSETS,
}

SCENE_TOOLSETS: dict[str, frozenset[str]] = dict(_CORE_SCENE_TOOLSETS)

_DEFAULT_SCENE = "general"
_WIDE_PACK_SCENE = "general"
_ALLOWED_LOADING = frozenset({"scoped", "search", "all"})
#: search 候选基座:catalog=完整目录减排除项(正式);scoped=场景子集
_ALLOWED_SEARCH_BASE = frozenset({"scoped", "catalog"})
#: 回退策略:legacy=连续未命中回退 scoped 宽包;none=不回退(正式)
_ALLOWED_FALLBACK = frozenset({"legacy", "none"})


def reset_scene_toolsets_to_core() -> None:
    """测试/禁用场景包时恢复核心映射。"""
    global _WIDE_PACK_SCENE
    SCENE_TOOLSETS.clear()
    SCENE_TOOLSETS.update(_CORE_SCENE_TOOLSETS)
    _WIDE_PACK_SCENE = _DEFAULT_SCENE


def register_scene_toolsets(mapping: dict[str, frozenset[str]]) -> None:
    """场景包注入额外场景标签 → toolset。"""
    for key, value in mapping.items():
        SCENE_TOOLSETS[key] = frozenset(value)


def extend_core_scene(scene: str, extra: frozenset[str]) -> None:
    """在已有场景(通常 general)上并入额外 toolset。"""
    base = SCENE_TOOLSETS.get(scene, frozenset())
    SCENE_TOOLSETS[scene] = frozenset(base | extra)


def set_wide_pack_scene(scene: str) -> None:
    """search 连续未命中时的回退场景(场景包可改为垂直宽包)。"""
    global _WIDE_PACK_SCENE
    _WIDE_PACK_SCENE = scene


class ToolLoader:
    """按 all / scoped / search 策略取出当次装载集合;search 命中缓存在本实例内。

    - ``excluded_tools``:显式排除项(all 与 search 共用同一排除口径);
    - ``search_base``:search 候选基座,``catalog`` 为新正式口径
      (完整目录减排除项 = eligible catalog,与 all 组一致);
    - ``fallback_policy``:``none`` 不回退(新正式);``legacy`` 保留旧
      连续未命中回退 scoped 宽包行为;
    - ``search_log``:每次检索的记录(查询/候选/分数/排名/耗时/命中),
      供工件归因(混合路线 C3)。
    """

    def __init__(
        self,
        catalog: ToolCatalog,
        *,
        tool_loading: str = "scoped",
        encoder: Encoder | None = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        miss_fallback_limit: int = MISS_FALLBACK_LIMIT,
        excluded_tools: frozenset[str] | set[str] | None = None,
        search_base: str = "scoped",
        fallback_policy: str | None = None,
    ) -> None:
        loading = (tool_loading or "scoped").strip().lower()
        if loading not in _ALLOWED_LOADING:
            raise ValueError("tool_loading 仅支持 all|scoped|search")
        base = (search_base or "scoped").strip().lower()
        if base not in _ALLOWED_SEARCH_BASE:
            raise ValueError("search_base 仅支持 catalog|scoped")
        if fallback_policy is None:
            # 新正式口径(catalog 基座)默认不回退;旧 scoped 基座保留旧行为
            fallback_policy = "none" if base == "catalog" else "legacy"
        if fallback_policy not in _ALLOWED_FALLBACK:
            raise ValueError("fallback_policy 仅支持 legacy|none")
        self._catalog = catalog
        self._tool_loading = loading
        self._excluded = frozenset(excluded_tools or ())
        self._search_base = base
        self._fallback_policy = fallback_policy
        self._index = (
            ToolSearchIndex(encoder, similarity_threshold=similarity_threshold) if encoder is not None else None
        )
        self._cache: dict[str, ToolCard] = {}
        self._miss_streak = 0
        self._fallback = False
        self._miss_fallback_limit = max(1, miss_fallback_limit)
        self._search_log: list[dict[str, object]] = []

    @property
    def tool_loading(self) -> str:
        return self._tool_loading

    @property
    def fallback_active(self) -> bool:
        return self._fallback

    @property
    def fallback_policy(self) -> str:
        return self._fallback_policy

    @property
    def search_base(self) -> str:
        return self._search_base

    @property
    def excluded_tools(self) -> frozenset[str]:
        return self._excluded

    @property
    def cached_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._cache))

    @property
    def search_log(self) -> list[dict[str, object]]:
        """检索记录副本(C3 工件归因:查询/候选/排名/耗时/命中)。"""
        return [dict(row) for row in self._search_log]

    def eligible_catalog(self) -> list[ToolCard]:
        """eligible catalog = 完整公开目录 − 显式排除项 − search_tools 元工具。

        all 与新正式 search 共用同一 eligible 口径(按稳定工具名排序)。
        """
        return [
            card
            for card in sorted(self._catalog.list(), key=lambda item: item.name)
            if card.name != SEARCH_TOOLS_NAME and card.name not in self._excluded
        ]

    def load_all(self) -> list[ToolCard]:
        """``all`` 装载:完整公开目录减排除项,按稳定工具名排序,不做场景收窄。"""
        return self.eligible_catalog()

    def load_scoped(
        self,
        scene_tag: str,
        *,
        authenticated: bool = False,
    ) -> list[ToolCard]:
        """按场景 toolset 过滤；需登录的工具在游客下不装载。"""
        scene_scopes = SCENE_TOOLSETS.get(scene_tag, SCENE_TOOLSETS[_DEFAULT_SCENE])
        loaded: list[ToolCard] = []
        for card in self._catalog.list():
            if card.name in self._excluded:
                continue
            if _visible_in_scene(card, scene_scopes, authenticated=authenticated):
                loaded.append(card)
        return loaded

    def load_for_turn(self, scene_tag: str, *, authenticated: bool = False) -> list[ToolCard]:
        """当轮 ``bind_tools`` 集合。"""
        if self._tool_loading == "all":
            return self.load_all()
        if self._tool_loading == "search" and not self._fallback:
            return self._search_pack()
        if self._fallback:
            return self.load_scoped(_WIDE_PACK_SCENE, authenticated=authenticated)
        return self.load_scoped(scene_tag, authenticated=authenticated)

    def granted_scopes(self, scene_tag: str, *, authenticated: bool) -> frozenset[str]:
        """供治理中间件 G3 使用的授权标签（场景 toolset ∪ 身份）。

        工具可见性与执行授权是两个概念:``all``/``catalog`` 基座只扩大
        **对模型可见**的工具集合,不扩大用户的执行授权——授权始终来自
        场景标签与登录身份(scoped 同口径)。受限工具在 ``all`` 模式下
        对 LLM 可见,执行时由 G3 按真实身份裁决(混合路线 C1)。
        """
        effective = _WIDE_PACK_SCENE if self._fallback else scene_tag
        scene_scopes = SCENE_TOOLSETS.get(effective, SCENE_TOOLSETS[_DEFAULT_SCENE])
        if authenticated:
            return frozenset(scene_scopes | {"authenticated"})
        return frozenset(scene_scopes)

    def run_search(
        self,
        query: str,
        *,
        top_k: int,
        scene_tag: str,
        authenticated: bool,
    ) -> dict[str, object]:
        """对候选集合做检索;命中写入会话缓存,连续未命中按策略处理。

        - ``search_base=catalog``:候选 = eligible catalog(与 all 组一致),
          不做场景预筛,搜索条件完全由 LLM 提出;
        - ``search_base=scoped``:候选 = 场景可见集(旧口径);
        - 回退仅在 ``fallback_policy=legacy`` 时发生,且每次都会记录。
        """
        if self._search_base == "catalog":
            visible = self.eligible_catalog()
        else:
            visible = self.load_scoped(scene_tag, authenticated=authenticated)
        started = time.perf_counter()
        scored: list[tuple[float, ToolCard]] = []
        if self._index is not None:
            scored = self._index.search_scored(query, visible, top_k=top_k)
        duration_ms = round((time.perf_counter() - started) * 1000)
        hits = [card for _score, card in scored]
        if hits:
            self._miss_streak = 0
            for card in hits:
                self._cache[card.name] = card
        else:
            self._miss_streak += 1
            if (
                self._fallback_policy == "legacy"
                and self._miss_streak >= self._miss_fallback_limit
            ):
                self._fallback = True
        ranked_candidates = [
            {"name": card.name, "description": card.description, "score": round(score, 4), "rank": rank}
            for rank, (score, card) in enumerate(scored, start=1)
        ]
        record: dict[str, object] = {
            "query": query,
            "top_k": top_k,
            "base": self._search_base,
            "eligible_catalog": [
                {"name": card.name, "description": card.description}
                for card in sorted(visible, key=lambda item: item.name)
            ],
            "candidates": ranked_candidates,
            "hits": [card.name for card in hits],
            "hit_count": len(hits),
            "duration_ms": duration_ms,
            "fallback": self._fallback,
            "fallback_policy": self._fallback_policy,
            "cached": sorted(self._cache),
        }
        if self._index is not None:
            record["threshold"] = self._index.threshold
        self._search_log.append(record)
        return {
            "query": query,
            # 返回候选名称、普通语言说明与排名;下一轮装载完整 Schema
            "results": ranked_candidates,
            "names": [card.name for card in hits],
            "count": len(hits),
            "fallback": self._fallback,
            "cached": sorted(self._cache),
        }

    def _search_pack(self) -> list[ToolCard]:
        meta = self._catalog.get(SEARCH_TOOLS_NAME)
        by_name: dict[str, ToolCard] = {meta.name: meta}
        for card in self._cache.values():
            by_name[card.name] = card
        return list(by_name.values())


def _visible_in_scene(card: ToolCard, scene_scopes: frozenset[str], *, authenticated: bool) -> bool:
    if card.name == SEARCH_TOOLS_NAME:
        return False
    required = set(card.required_scope or [])
    if "authenticated" in required and not authenticated:
        return False
    functional = required - {"authenticated"}
    if not functional:
        return True
    return bool(functional.intersection(scene_scopes))

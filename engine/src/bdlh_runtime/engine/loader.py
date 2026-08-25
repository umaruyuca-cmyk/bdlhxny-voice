"""工具装载（设计文档 §4.2）：scoped 映射与 search 动态装载。

``scoped``：运行启动时按「场景标签 → 工具包」装载固定子集。
``search``：初始仅装载元工具 ``search_tools``；命中 ToolCard 会话缓存后
进入后续 ``bind_tools``；连续未命中回退宽包。
身份标签（``authenticated``）由调用方授予。装载结果交给循环 ``bind_tools``
与治理中间件 G1。

默认场景为 ``general``（领域中立通用工具组）。垂直领域场景映射由可选
场景包注入，核心代码不硬编码垂直场景名。
"""

from __future__ import annotations

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
_ALLOWED_LOADING = frozenset({"scoped", "search"})


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
    """按 scoped / search 策略取出当次装载集合；search 命中缓存在本实例内。"""

    def __init__(
        self,
        catalog: ToolCatalog,
        *,
        tool_loading: str = "scoped",
        encoder: Encoder | None = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        miss_fallback_limit: int = MISS_FALLBACK_LIMIT,
    ) -> None:
        loading = (tool_loading or "scoped").strip().lower()
        if loading not in _ALLOWED_LOADING:
            raise ValueError("tool_loading 仅支持 scoped|search")
        self._catalog = catalog
        self._tool_loading = loading
        self._index = (
            ToolSearchIndex(encoder, similarity_threshold=similarity_threshold) if encoder is not None else None
        )
        self._cache: dict[str, ToolCard] = {}
        self._miss_streak = 0
        self._fallback = False
        self._miss_fallback_limit = max(1, miss_fallback_limit)

    @property
    def tool_loading(self) -> str:
        return self._tool_loading

    @property
    def fallback_active(self) -> bool:
        return self._fallback

    @property
    def cached_names(self) -> tuple[str, ...]:
        return tuple(sorted(self._cache))

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
            if _visible_in_scene(card, scene_scopes, authenticated=authenticated):
                loaded.append(card)
        return loaded

    def load_for_turn(self, scene_tag: str, *, authenticated: bool = False) -> list[ToolCard]:
        """当轮 ``bind_tools`` 集合：search 为元工具 + 缓存；回退后为宽包。"""
        if self._tool_loading == "search" and not self._fallback:
            return self._search_pack()
        if self._fallback:
            return self.load_scoped(_WIDE_PACK_SCENE, authenticated=authenticated)
        return self.load_scoped(scene_tag, authenticated=authenticated)

    def granted_scopes(self, scene_tag: str, *, authenticated: bool) -> frozenset[str]:
        """供治理中间件 G3 使用的授权标签（场景 toolset ∪ 身份）。"""
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
        """对权限过滤后的目录做检索；命中写入会话缓存，连续未命中触发宽包回退。"""
        visible = self.load_scoped(scene_tag, authenticated=authenticated)
        hits: list[ToolCard] = []
        if self._index is not None:
            hits = self._index.search(query, visible, top_k=top_k)
        if hits:
            self._miss_streak = 0
            for card in hits:
                self._cache[card.name] = card
        else:
            self._miss_streak += 1
            if self._miss_streak >= self._miss_fallback_limit:
                self._fallback = True
        return {
            "query": query,
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

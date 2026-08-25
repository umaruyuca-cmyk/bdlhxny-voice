"""工具检索索引单测（WO-T2-4）。"""

from tests.helpers_encoder import LexicalEncoder

from bdlh_runtime.engine.loader import ToolLoader
from bdlh_runtime.engine.semantic_router.encoder import EncoderUnavailableError
from bdlh_runtime.tools.catalog import catalog_from_snapshot
from bdlh_runtime.tools.search import SEARCH_TOOLS_NAME, ToolSearchIndex

HIT_QUERY = "实时报价 最新价"
MISS_QUERY = "qqqqxxxxzzzz"


class _FailingEncoder:
    def encode(self, texts: list[str]) -> list[list[float]]:
        raise EncoderUnavailableError("embedder down")


def test_search_hits_quote_card(registry_snapshot, finance_pack):
    catalog = catalog_from_snapshot(registry_snapshot)
    index = ToolSearchIndex(LexicalEncoder())
    visible = [card for card in catalog.list() if card.name != SEARCH_TOOLS_NAME]
    hits = index.search(HIT_QUERY, visible, top_k=3)
    names = [card.name for card in hits]
    assert "market.get_realtime_quote" in names
    assert SEARCH_TOOLS_NAME not in names


def test_search_miss_on_unrelated_query(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    index = ToolSearchIndex(LexicalEncoder())
    hits = index.search(MISS_QUERY, catalog.list(), top_k=3)
    assert hits == []


def test_search_empty_query_is_miss(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    index = ToolSearchIndex(LexicalEncoder())
    assert index.search("  ", catalog.list()) == []


def test_encoder_unavailable_degrades_to_miss(registry_snapshot):
    catalog = catalog_from_snapshot(registry_snapshot)
    index = ToolSearchIndex(_FailingEncoder())
    assert index.search(HIT_QUERY, catalog.list()) == []


def test_permission_filter_before_retrieval(registry_snapshot, finance_pack):
    """游客检索「持仓」不得返回需登录工具（权限过滤先于检索）。"""
    catalog = catalog_from_snapshot(registry_snapshot)
    guest_loader = ToolLoader(
        catalog,
        tool_loading="search",
        encoder=LexicalEncoder(),
    )
    result = guest_loader.run_search(
        "持仓",
        top_k=3,
        scene_tag="research",
        authenticated=False,
    )
    assert "portfolio.get_current_positions" not in result["names"]
    host_loader = ToolLoader(
        catalog,
        tool_loading="search",
        encoder=LexicalEncoder(),
    )
    host = host_loader.run_search(
        "持仓",
        top_k=3,
        scene_tag="portfolio",
        authenticated=True,
    )
    assert "portfolio.get_current_positions" in host["names"]

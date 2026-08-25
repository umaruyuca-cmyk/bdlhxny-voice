"""按 ToolCard 把治理中间件放行后的调用分发到适配器。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.contracts.analysis import AnalysisInput
from bdlh_runtime.tools.catalog import ToolCatalog, ToolOrigin

_JAVA_PREFIXES = ("portfolio.", "user.")


class CatalogToolExecutor:
    """把治理中间件放行的调用分发到数据适配器或确定性计算。"""

    def __init__(
        self,
        catalog: ToolCatalog,
        *,
        gateway_adapter: Any = None,
        java_adapter: Any = None,
        web_search_adapter: Any = None,
        analysis_capability: Any = None,
        deep_research_executor: Any = None,
    ) -> None:
        self._catalog = catalog
        self._gateway = gateway_adapter
        self._java = java_adapter
        self._web = web_search_adapter
        self._analysis = analysis_capability
        self._deep = deep_research_executor
        self._observer: Any = None

    def set_observer(self, observer: Any) -> None:
        self._observer = observer

    async def __call__(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._dispatch(name, arguments)
        hook = getattr(self._observer, "on_tool_observation", None) if self._observer is not None else None
        if callable(hook):
            hook(name, result)
        return result

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "research.deep_search" and self._deep is not None:
            return await self._deep.execute(name, arguments)
        if name == "research.web_search" and self._web is not None:
            return await self._web.execute(name, arguments)
        if name == "portfolio.build_current_valuation":
            return self._build_valuation(arguments)
        if name == "analysis.run_analysis":
            return self._run_analysis(arguments)
        if name.startswith(_JAVA_PREFIXES) or name.startswith("portfolio.") or name.startswith("user."):
            if self._java is None:
                return {"status": "UNAVAILABLE", "error": "Java 适配器未装配"}
            return await self._java.execute(name, arguments)
        origin = None
        if self._catalog.contains(name):
            origin = self._catalog.get(name).origin
        if origin is ToolOrigin.MCP or name.startswith("market."):
            if self._gateway is None:
                return {"status": "UNAVAILABLE", "error": "MCP 适配器未装配"}
            return await self._gateway.execute(name, arguments)
        raise KeyError(f"no executor for tool: {name}")

    @staticmethod
    def _observation_items(value: Any) -> list[Any]:
        """容忍观察以 dict 包装或裸列表传入：positions/quotes 提取。"""
        if isinstance(value, dict):
            for key in ("positions", "quotes", "items", "data", "records"):
                inner = value.get(key)
                if isinstance(inner, list):
                    return inner
            return []
        if isinstance(value, list):
            return value
        return []

    def _build_valuation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """确定性估值：market_value = quantity × price，权重 = 市值 / 总市值；fail-closed。"""
        engine_tag = "deterministic-valuation"
        quotes = self._observation_items(arguments.get("quote_observations"))
        price_by_symbol: dict[str, float] = {}
        for quote in quotes:
            if not isinstance(quote, dict):
                continue
            symbol = str(quote.get("symbol") or quote.get("instrument") or "")
            price = quote.get("price")
            if price is None:
                price = quote.get("last")
            if price is None:
                price = quote.get("close")
            if symbol and isinstance(price, (int, float)):
                price_by_symbol[symbol] = float(price)

        positions = self._observation_items(arguments.get("positions_observation"))
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        total = 0.0
        for position in positions:
            if not isinstance(position, dict):
                continue
            symbol = str(position.get("symbol") or position.get("instrument") or "")
            quantity = position.get("quantity")
            if quantity is None:
                quantity = position.get("shares")
            if not symbol or not isinstance(quantity, (int, float)):
                errors.append(f"条目缺少 symbol/quantity：{symbol or '?'}")
                continue
            price = price_by_symbol.get(symbol)
            if price is None:
                errors.append(f"缺少 {symbol} 的价格")
                continue
            market_value = round(float(quantity) * price, 2)
            rows.append({"symbol": symbol, "quantity": float(quantity), "price": price, "market_value": market_value})
            total += market_value

        if errors or not rows:
            return {
                "status": "FAILED",
                "engine": engine_tag,
                "error": "；".join(errors) or "无有效输入条目",
            }
        for row in rows:
            row["weight"] = round(row["market_value"] / total, 4)
        return {
            "status": "SUCCESS",
            "engine": engine_tag,
            "total_market_value": round(total, 2),
            "positions": rows,
        }

    def _run_analysis(self, arguments: dict[str, Any]) -> Any:
        if self._analysis is None:
            return {"status": "UNAVAILABLE", "error": "分析引擎未装配"}
        payload = dict(arguments)
        payload.setdefault("analysis_id", "engine-analysis")
        payload.setdefault("instrument", {"symbol": str(payload.get("symbol") or "UNKNOWN")})
        try:
            analysis_input = AnalysisInput.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            return {"status": "FAILED", "error": f"分析输入非法：{exc}"}
        result = self._analysis.analyze(analysis_input)
        if hasattr(result, "model_dump"):
            return result.model_dump(mode="json")
        return result

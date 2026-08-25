"""按 ToolCard 把治理中间件放行后的调用分发到适配器。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.contracts.analysis import AnalysisInput
from bdlh_runtime.memory.recall import recall_semantic_memory
from bdlh_runtime.tools.catalog import ToolCatalog, ToolOrigin

_JAVA_PREFIXES = ("portfolio.", "user.")


class CatalogToolExecutor:
    """生产执行器：MCP / Java / Web / 分析 / 记忆 / Deep Research。"""

    def __init__(
        self,
        catalog: ToolCatalog,
        *,
        gateway_adapter: Any = None,
        java_adapter: Any = None,
        web_search_adapter: Any = None,
        analysis_capability: Any = None,
        deep_research_executor: Any = None,
        memory_store: Any = None,
        user_id: str = "",
    ) -> None:
        self._catalog = catalog
        self._gateway = gateway_adapter
        self._java = java_adapter
        self._web = web_search_adapter
        self._analysis = analysis_capability
        self._deep = deep_research_executor
        self._memory = memory_store
        self._user_id = user_id
        self._observer: Any = None

    def set_user(self, user_id: str) -> None:
        self._user_id = user_id

    def set_observer(self, observer: Any) -> None:
        self._observer = observer

    async def __call__(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._dispatch(name, arguments)
        hook = getattr(self._observer, "on_tool_observation", None) if self._observer is not None else None
        if callable(hook):
            hook(name, result)
        return result

    async def _dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        if name == "memory.recall":
            result = await recall_semantic_memory(
                self._memory,
                user_id=self._user_id,
                query=str(arguments.get("query") or ""),
                limit=int(arguments.get("limit") or 5),
            )
            return {
                "records": [getattr(item, "content", item) for item in result.records],
                "degraded": result.degraded,
                "limitation": result.limitation,
            }
        if name == "research.deep_search" and self._deep is not None:
            return await self._deep.execute(name, arguments)
        if name == "research.web_search" and self._web is not None:
            return await self._web.execute(name, arguments)
        if name == "portfolio.build_current_valuation":
            return {"status": "SUCCESS", "inputs": arguments}
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

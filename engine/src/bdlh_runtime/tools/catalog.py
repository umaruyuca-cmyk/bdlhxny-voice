"""统一工具目录（设计文档 §4.1、WO-T2-1）。

``ToolCard`` 是全部工具（本地实现 + MCP 代理）的唯一登记形态；**工具目录
（ToolCatalog）是唯一真源**——装载器（T2-3）、检索索引（T2-4）、治理中间件
（T2-2）均从目录读取，不维护第二份清单。

危险动作语义物理化：目录 ``register`` 调用危险动作注册表——命中已配置词表的
工具**物理上无法注册**。默认词表为空；垂直领域词表由可选场景包注入。

数据源迁移（保留引用）：本地与 Java/Web 工具清单自 ``tools/capabilities.py``
（``CapabilityRegistry``，DB RegistrySnapshot 派生）迁移；MCP 工具经目录代理
登记并打 ``origin=mcp`` 标记（``integrations/mcp/registry.py`` 白名单内的服务）。
引擎侧只读伴侣工具（``search_tools``）由本模块在迁移后
登记，不写入八表。
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bdlh_runtime.registry import RegistrySnapshot
from bdlh_runtime.scenarios.dangerous_actions import (
    is_dangerous_action_semantic,
    is_trading_semantic,  # noqa: F401 —— 兼容旧测试导入路径
)

from .capabilities import CapabilityRegistry, CapabilitySpec, registry_from_snapshot

# ── 字面量类型 ───────────────────────────────────────────────────────────────


class ToolOrigin(StrEnum):
    """工具来源：本地实现（含 Java 数据面 / Web 检索 / 分析引擎 / 记忆）
    或 MCP server 代理。治理规则对两者一致生效（§4.4）。"""

    LOCAL = "local"
    MCP = "mcp"


class CostHint(StrEnum):
    """预算权重（§4.3 G-γ：premium 工具按 cost_hint 加权扣减，另有独立开关）。"""

    FREE = "free"
    NORMAL = "normal"
    PREMIUM = "premium"


# ── pydantic 参数契约（§4.1：parameters 由契约投影 JSON Schema）──────────────


class SymbolArgs(BaseModel):
    """单标的查询。"""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="标的代码或名称")


class HistoricalPricesArgs(BaseModel):
    """历史价格序列查询。"""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="标的代码或名称")
    lookback_days: int = Field(ge=1, le=750, description="回看天数")


class WebSearchArgs(BaseModel):
    """公开资料检索。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="检索查询词")


class DeepSearchArgs(BaseModel):
    """深度研究任务。"""

    model_config = ConfigDict(extra="forbid")
    question: str = Field(description="研究问题")
    objective: str = Field(description="研究目标")


class ValuationInputsArgs(BaseModel):
    """结构化重算输入（上游 Observation 的 JSON 文本）。"""

    model_config = ConfigDict(extra="forbid")
    positions_observation: str = Field(description="头寸 Observation 的 JSON 文本")
    account_observation: str = Field(description="账户 Observation 的 JSON 文本")
    quote_observations: str = Field(description="报价 Observation 列表的 JSON 文本")


class EmptyArgs(BaseModel):
    """无必填参数的只读查询。"""

    model_config = ConfigDict(extra="forbid")


class SearchToolsArgs(BaseModel):
    """search 装载模式的元工具：按描述检索可见 ToolCard。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="检索查询词，描述需要的能力")
    top_k: int = Field(default=3, ge=1, le=8, description="返回条数上限")


#: 核心参数契约。垂直领域工具契约由场景包在启用时并入。
_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "research.web_search": WebSearchArgs,
    "research.deep_search": DeepSearchArgs,
    "analysis.run_analysis": EmptyArgs,
    "search_tools": SearchToolsArgs,
}


def register_param_models(models: dict[str, type[BaseModel]]) -> None:
    """场景包注入额外工具的 pydantic 参数契约。"""
    _PARAM_MODELS.update(models)


def _schema_from_model(model: type[BaseModel]) -> dict[str, Any]:
    """pydantic 契约 → 面向模型的 object JSON Schema（去掉 title）。"""
    schema = model.model_json_schema()
    schema.pop("title", None)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    schema.setdefault("required", [])
    return schema


#: 已知参数名 → JSON Schema 类型片段（无 pydantic 契约时的兜底投影）。
_ARGUMENT_TYPES: dict[str, dict[str, Any]] = {
    "symbol": {"type": "string", "description": "标的代码或名称"},
    "symbols": {"type": "array", "items": {"type": "string"}, "description": "标的代码列表"},
    "lookback_days": {"type": "integer", "minimum": 1, "maximum": 750, "description": "回看天数"},
    "query": {"type": "string", "description": "检索查询词"},
    "question": {"type": "string", "description": "研究问题"},
    "objective": {"type": "string", "description": "研究目标"},
}

_UNTYPE_ARGUMENT = {"type": "string", "description": ""}


def _schema_from_required_arguments(required: Iterable[str]) -> dict[str, Any]:
    """由参数名集合投影最小 JSON Schema（object 类型 + required 列表）。"""
    required_names = sorted(set(required))
    return {
        "type": "object",
        "properties": {name: _ARGUMENT_TYPES.get(name, dict(_UNTYPE_ARGUMENT)) for name in required_names},
        "required": required_names,
        "additionalProperties": False,
    }


def _parameters_for(name: str, required_arguments: Iterable[str]) -> dict[str, Any]:
    model = _PARAM_MODELS.get(name)
    if model is not None:
        return _schema_from_model(model)
    return _schema_from_required_arguments(required_arguments)


# ── 双目的 description（模型选择 + embedding 检索）──────────────────────────

#: 核心目录描述。垂直领域工具描述由场景包 overlay 注入。
_DUAL_PURPOSE_DESCRIPTIONS: dict[str, str] = {
    "research.web_search": (
        "检索最新外部公开资料并带来源返回。"
        "用于「搜一下最新报道」「公开资料里怎么说」。检索关键词：网页检索、公开资料、来源。"
    ),
    "research.deep_search": (
        "对研究任务做多轮拆题、检索、压缩，返回结构化研究包（premium，预算加权）。"
        "用于「深入调研某个主题」「给一份研究报告」。检索关键词：深度研究、调研、ResearchBundle。"
    ),
    "analysis.run_analysis": (
        "对已标准化的结构化数据执行确定性分析，返回类型化结果。"
        "用于「帮我算一下」「做一次诊断」。检索关键词：分析引擎、诊断、评分。"
    ),
    "search_tools": (
        "按自然语言描述从当前场景与身份可见的工具目录中检索可用工具，命中后装载进后续上下文。"
        "用于「找一个能查数据的工具」。检索关键词：工具检索、search_tools、装载。"
    ),
}


def _description_for(name: str, fallback: str) -> str:
    from bdlh_runtime.scenarios import apply_description_overlays

    base = _DUAL_PURPOSE_DESCRIPTIONS.get(name, fallback)
    return apply_description_overlays(name, base)


# ── ToolCard 契约（§4.1 字段严格对齐）────────────────────────────────────────


class ToolCard(BaseModel):
    """统一工具登记卡。

    - ``name``：全局唯一，点分命名空间（如 ``web.search``）；
    - ``description``：面向「模型选择 + embedding 检索」双目的撰写；
    - ``parameters``：JSON Schema（由参数契约投影）；
    - ``origin``：``local`` | ``mcp``；
    - ``read_only``：治理输入（G2 只读红线）；
    - ``required_scope``：场景 / 身份可见性标签（scoped 装载与权限过滤共用）；
    - ``cost_hint``：``free`` | ``normal`` | ``premium``（预算加权）。
    """

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    origin: ToolOrigin = ToolOrigin.LOCAL
    read_only: bool = True
    required_scope: list[str] = Field(default_factory=list)
    cost_hint: CostHint = CostHint.NORMAL
    # GT-6 评测轴标注(判官 GT-7 消费;治理轴 read_only 不变)
    side_effect: str = "none"
    requires_confirmation: bool = False
    risk_level: str = "low"

    def manifest(self) -> dict[str, Any]:
        """面向模型 bind_tools 的描述（不含治理与路由细节）。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


# ── 工具目录（唯一真源）──────────────────────────────────────────────────────


class ToolCatalog:
    """全部 ToolCard 的唯一真源。

    装载器 / 检索索引 / 治理中间件均从这里读取；本类不做装载决策与治理裁决。
    """

    def __init__(self) -> None:
        self._cards: dict[str, ToolCard] = {}

    def register(self, card: ToolCard) -> ToolCard:
        """登记工具卡。

        - 重名拒绝（全局唯一）；
        - 危险动作语义守卫：命中已注册词表的名字 / 描述物理拒绝注册；
        - 只读红线：``read_only=False`` 的工具默认拒绝（红线物理化，§4.4）。
        """
        if card.name in self._cards:
            raise ValueError(f"ToolCard already registered: {card.name}")
        if is_dangerous_action_semantic(card.name, card.description):
            raise ValueError(f"危险动作红线：工具不得注册：{card.name}")
        if not card.read_only:
            raise ValueError(f"只读红线：目录仅登记只读工具（read_only=False 被拒）：{card.name}")
        self._cards[card.name] = card
        return card

    def get(self, name: str) -> ToolCard:
        try:
            return self._cards[name]
        except KeyError as exc:
            raise KeyError(f"ToolCard not registered: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._cards

    def list(self) -> list[ToolCard]:
        """按登记顺序返回(对比用例依赖可见工具顺序稳定)。"""
        return list(self._cards.values())

    def list_visible(self, scopes: Iterable[str]) -> list[ToolCard]:
        """按场景 / 身份标签过滤可见工具（scoped 装载与检索权限过滤共用）。

        scope 标签任一命中即可见；空 ``required_scope`` 视为全场景可见。
        """
        granted = set(scopes)
        return [card for card in self.list() if not card.required_scope or granted.intersection(card.required_scope)]

    def __len__(self) -> int:
        return len(self._cards)


# ── 从 CapabilityRegistry 迁移（本地 / Java / Web / 分析引擎工具）──────────────


def _origin_for_adapter(adapter: str) -> ToolOrigin:
    """adapter 字段 → ToolCard.origin：MCP 代理为 mcp，其余（java/web/local）为 local。"""
    return ToolOrigin.MCP if adapter == "mcp" else ToolOrigin.LOCAL


def _cost_hint_for(name: str) -> CostHint:
    """预算权重映射：深度研究为 premium（§4.3 G-γ），其余 normal。"""
    if name == "research.deep_search":
        return CostHint.PREMIUM
    return CostHint.NORMAL


def _card_from_spec(spec: CapabilitySpec) -> ToolCard:
    """CapabilitySpec → ToolCard（点分名沿用；description 用双目的 overlay；
    scope 自 toolsets + 身份标签派生）。"""
    scopes = sorted(spec.toolsets)
    if spec.requires_authenticated_user:
        scopes = sorted(set(scopes) | {"authenticated"})
    return ToolCard(
        name=spec.name,
        description=_description_for(spec.name, spec.description),
        parameters=_parameters_for(spec.name, spec.required_arguments),
        origin=_origin_for_adapter(spec.adapter),
        read_only=True,  # CapabilityRegistry 只登记只读能力（register 已守卫）
        required_scope=scopes,
        cost_hint=_cost_hint_for(spec.name),
        side_effect=spec.side_effect,
        requires_confirmation=spec.requires_confirmation,
        risk_level=spec.risk_level,
    )


def _register_engine_local_tools(catalog: ToolCatalog) -> None:
    """登记不在数据库种子中的引擎侧 search 元工具。"""
    catalog.register(
        ToolCard(
            name="search_tools",
            description=_description_for("search_tools", "按描述检索可见工具"),
            parameters=_parameters_for("search_tools", ("query",)),
            origin=ToolOrigin.LOCAL,
            read_only=True,
            required_scope=[],
            cost_hint=CostHint.NORMAL,
        )
    )


def catalog_from_capability_registry(capabilities: CapabilityRegistry) -> ToolCatalog:
    """自既有能力目录（DB RegistrySnapshot 派生）迁移构建工具目录。"""
    catalog = ToolCatalog()
    for spec in capabilities.list():
        catalog.register(_card_from_spec(spec))
    _register_engine_local_tools(catalog)
    return catalog


def catalog_from_snapshot(snapshot: RegistrySnapshot) -> ToolCatalog:
    """装配入口：由已通过启动校验的 RegistrySnapshot 构建工具目录。"""
    return catalog_from_capability_registry(registry_from_snapshot(snapshot))


# ── MCP 工具代理登记（C-5：外部能力一律经 MCP 接入，代理登记打 origin=mcp）────


def register_mcp_tool(
    catalog: ToolCatalog,
    *,
    name: str,
    description: str,
    parameters: dict[str, Any] | None = None,
    required_scope: Iterable[str] = (),
    cost_hint: CostHint = CostHint.NORMAL,
) -> ToolCard:
    """把动态发现的 MCP 工具以代理形态登记进目录。

    治理规则对本地与 MCP 工具一致生效（§4.4）：危险动作守卫与只读红线同样约束
    MCP 工具；新增 MCP server 自动进入拦截链，无需治理侧适配。
    """
    card = ToolCard(
        name=name,
        description=description,
        parameters=parameters or _schema_from_model(EmptyArgs),
        origin=ToolOrigin.MCP,
        read_only=True,
        required_scope=sorted(set(required_scope)),
        cost_hint=cost_hint,
    )
    return catalog.register(card)

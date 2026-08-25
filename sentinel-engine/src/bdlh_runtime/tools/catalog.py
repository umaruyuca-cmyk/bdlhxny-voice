"""统一工具目录（设计文档 §4.1、WO-T2-1）。

``ToolCard`` 是全部工具（本地实现 + MCP 代理）的唯一登记形态；**工具目录
（ToolCatalog）是唯一真源**——装载器（T2-3）、检索索引（T2-4）、治理中间件
（T2-2）均从目录读取，不维护第二份清单。

C-1 红线物理化：目录 ``register`` 内置交易语义守卫——名字或描述含交易执行
语义的工具**物理上无法注册**，语义层无须也无法「识别并放行」危险操作。

数据源迁移（保留引用）：本地与 Java/Web 工具清单自 ``tools/capabilities.py``
（``CapabilityRegistry``，DB RegistrySnapshot 派生）迁移；MCP 工具经目录代理
登记并打 ``origin=mcp`` 标记（``integrations/mcp/registry.py`` 白名单内的服务）。
引擎侧只读伴侣工具（``memory.recall``、``search_tools``）由本模块在迁移后
登记，不写入八表。
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bdlh_runtime.registry import RegistrySnapshot

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


# ── C-1 交易语义红线（物理守卫）──────────────────────────────────────────────

#: 英文交易执行语义：按单词边界匹配（归一化下划线之后）。
_TRADING_EN_PATTERN = re.compile(
    r"\b(buy|sell|purchase|trade|trading|order|place_order|execute_order)\b",
    re.IGNORECASE,
)

#: 中文交易执行语义：不用 ``\b``（CJK 与 ``\w`` 同属单词字符，边界匹配会漏判）。
_TRADING_ZH_TERMS = ("买入", "卖出", "下单", "挂单", "撤单", "交易执行", "调仓执行")

#: 显式豁免：名称/描述含"交易"字样但语义为只读查询的工具（白名单优先于模式）。
_TRADING_EXEMPT_NAMES = frozenset(
    {
        # 只读交易历史查询：查询已发生交易，不承载交易执行
        "portfolio.get_transaction_history",
    }
)


def is_trading_semantic(name: str, description: str) -> bool:
    """判定工具是否携带交易执行语义（C-1 守卫，供注册与测试使用）。

    名字中的 ``_`` / ``.`` / ``-`` 先归一化为空格再匹配——否则 ``sell_all``
    这类下划线复合词会因 ``\\b`` 把下划线视为单词字符而漏判。中文术语按子串
    匹配，避免 CJK 无单词边界而漏判。
    """
    if name in _TRADING_EXEMPT_NAMES:
        return False
    normalized_name = re.sub(r"[._\-]", " ", name)
    haystacks = (normalized_name, description)
    if any(_TRADING_EN_PATTERN.search(text) for text in haystacks):
        return True
    return any(term in text for text in haystacks for term in _TRADING_ZH_TERMS)


# ── pydantic 参数契约（§4.1：parameters 由契约投影 JSON Schema）──────────────


class SymbolArgs(BaseModel):
    """单标的查询。"""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="证券代码或名称，如 300750")


class HistoricalPricesArgs(BaseModel):
    """历史行情查询。"""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(description="证券代码或名称，如 300750")
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
    """持仓估值重算输入（上游 Observation 的 JSON 文本）。"""

    model_config = ConfigDict(extra="forbid")
    positions_observation: str = Field(description="持仓 Observation 的 JSON 文本")
    account_observation: str = Field(description="账户 Observation 的 JSON 文本")
    quote_observations: str = Field(description="行情 Observation 列表的 JSON 文本")


class EmptyArgs(BaseModel):
    """无必填参数的只读查询。"""

    model_config = ConfigDict(extra="forbid")


class MemoryRecallArgs(BaseModel):
    """L3 语义召回。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="语义召回查询，如用户目标或已确认偏好")
    limit: int = Field(default=5, ge=1, le=20, description="返回条数上限")


class SearchToolsArgs(BaseModel):
    """search 装载模式的元工具：按描述检索可见 ToolCard。"""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="检索查询词，描述需要的能力")
    top_k: int = Field(default=3, ge=1, le=8, description="返回条数上限")


_PARAM_MODELS: dict[str, type[BaseModel]] = {
    "market.resolve_instrument": SymbolArgs,
    "market.get_realtime_quote": SymbolArgs,
    "market.get_historical_prices": HistoricalPricesArgs,
    "market.get_financial_statements": SymbolArgs,
    "market.get_valuation": SymbolArgs,
    "market.get_industry_context": SymbolArgs,
    "market.get_money_flow": SymbolArgs,
    "market.get_news": SymbolArgs,
    "research.web_search": WebSearchArgs,
    "research.deep_search": DeepSearchArgs,
    "analysis.run_analysis": EmptyArgs,
    "portfolio.get_current_positions": EmptyArgs,
    "portfolio.get_account_snapshot": EmptyArgs,
    "portfolio.get_transaction_history": EmptyArgs,
    "portfolio.build_current_valuation": ValuationInputsArgs,
    "user.get_risk_profile": EmptyArgs,
    "memory.recall": MemoryRecallArgs,
    "search_tools": SearchToolsArgs,
}


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
    "symbol": {"type": "string", "description": "证券代码或名称，如 300750"},
    "symbols": {"type": "array", "items": {"type": "string"}, "description": "证券代码列表"},
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

#: 目录层撰写；不覆盖 DB 运维文案。每条含「用途」与「检索关键词」。
_DUAL_PURPOSE_DESCRIPTIONS: dict[str, str] = {
    "market.resolve_instrument": (
        "把用户说的股票名、简称或代码解析成标准标的（代码、名称、市场）。"
        "用于「宁德时代是哪个代码」「300750 是什么」。检索关键词：证券代码、标的解析、股票名称。"
    ),
    "market.get_realtime_quote": (
        "查询一只证券的最新行情（最新价、涨跌幅、成交额）。"
        "用于「现在什么价」「今天涨了多少」。检索关键词：实时报价、最新价、涨跌、盘口。"
    ),
    "market.get_historical_prices": (
        "查询一只证券的历史 OHLCV 价格序列。"
        "用于「近一年走势」「上个月收盘价」。检索关键词：历史行情、K线、OHLCV、回看。"
    ),
    "market.get_financial_statements": (
        "查询一只证券的标准化财务报表（利润表、资产负债表、现金流量表）。"
        "用于「营收多少」「资产负债结构」。检索关键词：财报、三大报表、基本面。"
    ),
    "market.get_valuation": (
        "查询一只证券的估值指标（市盈率、市净率等）。"
        "用于「估值高不高」「PE 多少」。检索关键词：估值、市盈率、市净率、PE、PB。"
    ),
    "market.get_industry_context": (
        "查询标的所属行业与行业背景。"
        "用于「这只股票是哪个行业」「同行对比」。检索关键词：行业、板块、赛道。"
    ),
    "market.get_money_flow": (
        "查询标的资金流向。"
        "用于「主力在买还是在卖」「资金净流入」。检索关键词：资金流、主力、净流入。"
    ),
    "market.get_news": (
        "查询与标的相关的结构化新闻。"
        "用于「最近有什么消息」「公司公告」。检索关键词：新闻、资讯、公告。"
    ),
    "research.web_search": (
        "检索最新外部公开资料并带来源返回。"
        "用于「搜一下最新报道」「公开资料里怎么说」。检索关键词：网页检索、公开资料、来源。"
    ),
    "research.deep_search": (
        "对研究任务做多轮拆题、检索、压缩，返回结构化研究包（premium，预算加权）。"
        "用于「深入调研这只股票」「给一份研究报告」。检索关键词：深度研究、调研、ResearchBundle。"
    ),
    "analysis.run_analysis": (
        "对已标准化的行情、持仓或画像数据执行确定性金融分析，返回类型化结果。"
        "用于「帮我算一下」「组合诊断」「适合度筛查」。检索关键词：分析引擎、诊断、评分、筛查。"
    ),
    "portfolio.get_current_positions": (
        "读取当前登录用户的持仓列表（需登录）。"
        "用于「我现在持有什么」「仓位怎么分布」。检索关键词：持仓、仓位、股票组合。"
    ),
    "portfolio.get_account_snapshot": (
        "读取当前登录用户的账户快照（需登录）。"
        "用于「账户里还有多少现金」「总资产多少」。检索关键词：账户、现金、总资产。"
    ),
    "portfolio.get_transaction_history": (
        "读取当前登录用户已发生的成交流水（只读查询，不下达任何指令）。"
        "用于「我上次什么时候买的」「历史成交」。检索关键词：成交流水、历史记录、已发生。"
    ),
    "portfolio.build_current_valuation": (
        "基于最新行情对当前持仓做确定性估值重算（需登录）。"
        "用于「按现价我的组合值多少」「浮盈浮亏」。检索关键词：估值重算、市值、浮盈。"
    ),
    "user.get_risk_profile": (
        "读取当前登录用户的风险画像与金融档案（需登录）。"
        "用于「我的风险承受能力」「画像是稳健还是进取」。检索关键词：风险画像、风险偏好、档案。"
    ),
    "memory.recall": (
        "按语义检索当前用户的长期记忆（目标、偏好、已确认事实），只读。"
        "用于「我说过的换房计划」「之前确认过的目标」。检索关键词：记忆、目标、偏好、召回。"
    ),
    "search_tools": (
        "按自然语言描述从当前场景与身份可见的工具目录中检索可用工具，命中后装载进后续上下文。"
        "用于「找一个查最新价的工具」「有没有持仓查询」。检索关键词：工具检索、search_tools、装载。"
    ),
}


# ── ToolCard 契约（§4.1 字段严格对齐）────────────────────────────────────────


class ToolCard(BaseModel):
    """统一工具登记卡。

    - ``name``：全局唯一，点分命名空间（如 ``market.get_quote``）；
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
        - C-1 守卫：交易执行语义的名字 / 描述物理拒绝注册；
        - 只读红线：``read_only=False`` 的工具默认拒绝（红线物理化，§4.4）。
        """
        if card.name in self._cards:
            raise ValueError(f"ToolCard already registered: {card.name}")
        if is_trading_semantic(card.name, card.description):
            raise ValueError(f"C-1 红线：交易执行语义的工具不得注册：{card.name}")
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
        return [self._cards[name] for name in sorted(self._cards)]

    def list_visible(self, scopes: Iterable[str]) -> list[ToolCard]:
        """按场景 / 身份标签过滤可见工具（scoped 装载与检索权限过滤共用）。

        scope 标签任一命中即可见；空 ``required_scope`` 视为全场景可见。
        """
        granted = set(scopes)
        return [
            card
            for card in self.list()
            if not card.required_scope or granted.intersection(card.required_scope)
        ]

    def __len__(self) -> int:
        return len(self._cards)


# ── 从 CapabilityRegistry 迁移（本地 / Java / Web / 分析引擎工具）──────────────


def _origin_for_adapter(adapter: str) -> ToolOrigin:
    """adapter 字段 → ToolCard.origin：MCP 代理为 mcp，其余（java/web/local）为 local。"""
    return ToolOrigin.MCP if adapter == "mcp" else ToolOrigin.LOCAL


def _cost_hint_for(name: str) -> CostHint:
    """预算权重映射：深度研究为 premium（§4.3 G-γ），记忆召回为 free，其余 normal。"""
    if name == "research.deep_search":
        return CostHint.PREMIUM
    if name == "memory.recall":
        return CostHint.FREE
    return CostHint.NORMAL


def _description_for(name: str, fallback: str) -> str:
    return _DUAL_PURPOSE_DESCRIPTIONS.get(name, fallback)


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
    )


def _register_engine_local_tools(catalog: ToolCatalog) -> None:
    """登记不在八表种子中的引擎侧只读工具（记忆召回、search 元工具）。"""
    catalog.register(
        ToolCard(
            name="memory.recall",
            description=_description_for("memory.recall", "按语义检索当前用户的长期记忆"),
            parameters=_parameters_for("memory.recall", ("query",)),
            origin=ToolOrigin.LOCAL,
            read_only=True,
            required_scope=["authenticated"],
            cost_hint=_cost_hint_for("memory.recall"),
        )
    )
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

    治理规则对本地与 MCP 工具一致生效（§4.4）：C-1 守卫与只读红线同样约束
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

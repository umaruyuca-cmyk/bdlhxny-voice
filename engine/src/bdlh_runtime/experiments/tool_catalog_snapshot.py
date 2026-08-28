"""对比用例冻结工具目录快照。

工具定义来自正式目录口径(通用 Mock 工具),不在执行器里构造空 Schema。
所有实验变体读取同一份快照与同一顺序。垂直领域工具由可选场景包另行注入。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bdlh_runtime.tools.catalog import (
    ToolCard,
    ToolCatalog,
    _ARGUMENT_TYPES,
    _description_for,
    _parameters_for,
)

COMPARISON_TOOL_CATALOG_VERSION = "comparison-catalog-v1"

#: 通用参数类型补充(无 pydantic 契约时的投影)
_EXTRA_ARGUMENT_TYPES: dict[str, dict[str, Any]] = {
    **_ARGUMENT_TYPES,
    "order_id": {"type": "string", "description": "订单编号"},
    "product_id": {"type": "string", "description": "商品编号"},
    "product_ids": {"type": "array", "items": {"type": "string"}, "description": "商品编号列表"},
    "url": {"type": "string", "description": "网页 URL"},
    "urls": {"type": "array", "items": {"type": "string"}, "description": "网页 URL 列表"},
    "path": {"type": "string", "description": "文件或资源路径"},
    "paths": {"type": "array", "items": {"type": "string"}, "description": "路径列表"},
    "connection_id": {"type": "string", "description": "数据库连接标识"},
    "table": {"type": "string", "description": "数据表名"},
    "sql": {"type": "string", "description": "只读 SQL 查询文本"},
    "repository": {"type": "string", "description": "代码仓库标识"},
    "ref": {"type": "string", "description": "分支或提交引用"},
    "location": {"type": "string", "description": "地点名称或坐标"},
    "origin": {"type": "string", "description": "起点"},
    "destination": {"type": "string", "description": "终点"},
    "mode": {"type": "string", "description": "出行方式"},
    "date": {"type": "string", "description": "日期"},
    "dates": {"type": "string", "description": "日期区间"},
    "participants": {"type": "array", "items": {"type": "string"}, "description": "参与人列表"},
    "duration": {"type": "integer", "description": "时长(分钟)"},
    "priority": {"type": "string", "description": "优先级"},
    "title": {"type": "string", "description": "标题"},
    "description": {"type": "string", "description": "描述正文"},
    "to": {"type": "string", "description": "收件人"},
    "subject": {"type": "string", "description": "邮件主题"},
    "body": {"type": "string", "description": "正文"},
    "channel": {"type": "string", "description": "消息频道"},
    "recipients": {"type": "array", "items": {"type": "string"}, "description": "收件人列表"},
    "start": {"type": "string", "description": "开始时间"},
    "end": {"type": "string", "description": "结束时间"},
    "fields": {"type": "array", "items": {"type": "string"}, "description": "待提取字段"},
    "question": {"type": "string", "description": "比较或分析问题"},
    "filters": {"type": "object", "description": "过滤条件"},
    "quantity": {"type": "integer", "description": "数量"},
    "status": {"type": "string", "description": "状态过滤"},
    "mailbox": {"type": "string", "description": "邮箱标识"},
    "collection": {"type": "string", "description": "知识库集合"},
    "focus": {"type": "string", "description": "摘要关注点"},
    "criteria": {"type": "string", "description": "比较标准"},
    "language": {"type": "string", "description": "编程语言"},
    "code": {"type": "string", "description": "待执行代码"},
    "start_line": {"type": "integer", "description": "起始行号"},
    "end_line": {"type": "integer", "description": "结束行号"},
    "input_ref": {"type": "string", "description": "输入数据引用"},
    "operations": {"type": "array", "description": "转换操作列表"},
    "format": {"type": "string", "description": "导出格式"},
    "expression": {"type": "string", "description": "计算表达式"},
    "identifier": {"type": "string", "description": "引用标识"},
    "preferences": {"type": "object", "description": "行程偏好"},
}


@dataclass(frozen=True)
class SnapshotTool:
    name: str
    description: str
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...] = ()
    side_effect: str = "none"
    requires_confirmation: bool = False
    risk_level: str = "low"
    requires_authenticated_user: bool = False
    operations: tuple[str, ...] = ()
    toolsets: tuple[str, ...] = ()


#: 对比用例可见工具全集(通用 Mock 工具)。描述与必填参数对齐正式目录。
_SNAPSHOT_TOOLS: tuple[SnapshotTool, ...] = (
    SnapshotTool("web.search", "搜索通用网页", ("query",), operations=("READ_PUBLIC_CONTENT",), toolsets=("web_read",)),
    SnapshotTool("web.open", "打开指定网页", ("url",), operations=("READ_PUBLIC_CONTENT",), toolsets=("web_read",)),
    SnapshotTool(
        "web.extract",
        "提取网页结构化字段",
        ("url",),
        optional_arguments=("fields",),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("web_read",),
    ),
    SnapshotTool(
        "web.compare_sources",
        "比较多个网页来源",
        ("urls",),
        optional_arguments=("question",),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("web_read",),
    ),
    SnapshotTool("web.check_freshness", "检查网页或信息更新时间", ("url",), operations=("READ_PUBLIC_CONTENT",), toolsets=("web_read",)),
    SnapshotTool(
        "document.summarize",
        "总结文档",
        ("path",),
        optional_arguments=("focus",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("file_docs",),
    ),
    SnapshotTool(
        "knowledge.search",
        "搜索内部知识库",
        ("query",),
        optional_arguments=("collection",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("cloud_knowledge",),
    ),
    SnapshotTool(
        "mail.search",
        "搜索邮件",
        ("query",),
        optional_arguments=("mailbox",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("mail_messaging",),
    ),
    SnapshotTool(
        "mail.draft",
        "生成邮件草稿(不发送)",
        ("to", "subject", "body"),
        side_effect="write",
        risk_level="medium",
        requires_authenticated_user=True,
        operations=("WRITE_COMMUNICATION",),
        toolsets=("mail_messaging",),
    ),
    SnapshotTool(
        "mail.send",
        "发送邮件(Mock,需确认)",
        ("to", "subject", "body"),
        side_effect="external_action",
        requires_confirmation=True,
        risk_level="high",
        requires_authenticated_user=True,
        operations=("WRITE_COMMUNICATION",),
        toolsets=("mail_messaging",),
    ),
    SnapshotTool(
        "message.send",
        "发送即时消息(Mock,需确认)",
        ("channel", "recipients", "body"),
        side_effect="external_action",
        requires_confirmation=True,
        risk_level="high",
        requires_authenticated_user=True,
        operations=("WRITE_COMMUNICATION",),
        toolsets=("mail_messaging",),
    ),
    SnapshotTool(
        "calendar.list_events",
        "查看日历事件",
        (),
        optional_arguments=("start", "end"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("calendar_task_project",),
    ),
    SnapshotTool(
        "calendar.find_availability",
        "查询空闲时间",
        ("participants", "duration"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("calendar_task_project",),
    ),
    SnapshotTool(
        "calendar.create_event",
        "创建日历事件(Mock,需确认)",
        ("title", "start", "end", "participants"),
        side_effect="write",
        requires_confirmation=True,
        risk_level="high",
        requires_authenticated_user=True,
        operations=("WRITE_SCHEDULE",),
        toolsets=("calendar_task_project",),
    ),
    SnapshotTool(
        "data.transform",
        "转换结构化数据",
        ("input_ref", "operations"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("spreadsheet_data",),
    ),
    SnapshotTool(
        "data.export",
        "导出数据(Mock)",
        ("input_ref", "format"),
        side_effect="write",
        risk_level="medium",
        requires_authenticated_user=True,
        operations=("WRITE_FILE",),
        toolsets=("spreadsheet_data",),
    ),
    SnapshotTool(
        "database.list_tables",
        "列出数据表",
        ("connection_id",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("database_report",),
    ),
    SnapshotTool(
        "database.describe_table",
        "查询表结构",
        ("connection_id", "table"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("database_report",),
    ),
    SnapshotTool(
        "database.query",
        "执行只读查询(Mock,不执行真实 SQL)",
        ("connection_id", "sql"),
        optional_arguments=("table",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("database_report",),
    ),
    SnapshotTool(
        "code.search",
        "搜索代码",
        ("query",),
        optional_arguments=("repository",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("code_git_ci",),
    ),
    SnapshotTool(
        "code.read",
        "读取代码",
        ("path",),
        optional_arguments=("start_line", "end_line"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("code_git_ci",),
    ),
    SnapshotTool(
        "code.execute",
        "执行代码(Mock 沙箱,需确认)",
        ("language", "code"),
        side_effect="external_action",
        requires_confirmation=True,
        risk_level="high",
        operations=("EXECUTE_CODE",),
        toolsets=("code_git_ci",),
    ),
    SnapshotTool(
        "git.get_diff",
        "读取代码差异",
        ("repository",),
        optional_arguments=("ref",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("code_git_ci",),
    ),
    SnapshotTool(
        "ci.get_status",
        "查询构建状态",
        ("repository", "ref"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("code_git_ci",),
    ),
    SnapshotTool("weather.get_forecast", "查询天气", ("location",), optional_arguments=("date",), operations=("READ_PUBLIC_CONTENT",), toolsets=("geo_travel",)),
    SnapshotTool(
        "maps.search_places",
        "搜索地点",
        ("query",),
        optional_arguments=("location",),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("geo_travel",),
    ),
    SnapshotTool(
        "maps.get_directions",
        "查询路线",
        ("origin", "destination", "mode"),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("geo_travel",),
    ),
    SnapshotTool(
        "travel.search_transport",
        "搜索交通方案",
        ("origin", "destination", "date"),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("geo_travel",),
    ),
    SnapshotTool(
        "travel.search_hotels",
        "搜索住宿",
        ("location", "dates"),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("geo_travel",),
    ),
    SnapshotTool(
        "travel.build_itinerary",
        "生成行程结构",
        ("destination", "dates"),
        optional_arguments=("preferences",),
        risk_level="medium",
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("geo_travel",),
    ),
    SnapshotTool(
        "product.search",
        "搜索商品",
        ("query",),
        optional_arguments=("filters",),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("commerce",),
    ),
    SnapshotTool(
        "product.compare",
        "比较商品",
        ("product_ids",),
        optional_arguments=("criteria",),
        operations=("READ_PUBLIC_CONTENT",),
        toolsets=("commerce",),
    ),
    SnapshotTool("product.get_price", "查询价格", ("product_id",), operations=("READ_PUBLIC_CONTENT",), toolsets=("commerce",)),
    SnapshotTool(
        "cart.add_item",
        "加入购物车(Mock,需确认,不产生真实订单)",
        ("product_id", "quantity"),
        side_effect="write",
        requires_confirmation=True,
        risk_level="medium",
        requires_authenticated_user=True,
        operations=("WRITE_CART",),
        toolsets=("commerce",),
    ),
    SnapshotTool(
        "order.get_status",
        "查询订单状态",
        ("order_id",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("commerce",),
    ),
    SnapshotTool(
        "crm.search_customer",
        "搜索客户",
        ("query",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("crm_support",),
    ),
    SnapshotTool(
        "support.search_tickets",
        "搜索工单",
        (),
        optional_arguments=("query", "status"),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("crm_support",),
    ),
    SnapshotTool(
        "support.create_ticket",
        "创建工单(Mock)",
        ("title", "description", "priority"),
        side_effect="write",
        risk_level="medium",
        requires_authenticated_user=True,
        operations=("WRITE_COMMUNICATION",),
        toolsets=("crm_support",),
    ),
    SnapshotTool(
        "contacts.search",
        "搜索联系人",
        ("query",),
        requires_authenticated_user=True,
        operations=("READ_PRIVATE_WORKSPACE",),
        toolsets=("personal_utils",),
    ),
    SnapshotTool("calculator.evaluate", "执行普通计算", ("expression",), operations=("READ_PUBLIC_CONTENT",), toolsets=("personal_utils",)),
    SnapshotTool("citation.lookup", "查询论文或引用信息", ("identifier",), operations=("READ_PUBLIC_CONTENT",), toolsets=("education",)),
    SnapshotTool(
        "research.web_search",
        "检索外部公开资料并带来源返回",
        ("query",),
        operations=("READ_PUBLIC_RESEARCH",),
        toolsets=("news_read",),
    ),
)

_BY_NAME: dict[str, SnapshotTool] = {tool.name: tool for tool in _SNAPSHOT_TOOLS}


class ComparisonToolCatalogError(ValueError):
    """对比用例引用了工具目录中不存在的工具,或目录配置无效。"""


def snapshot_tool_names() -> frozenset[str]:
    return frozenset(_BY_NAME)


def get_snapshot_tool(name: str) -> SnapshotTool:
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise ComparisonToolCatalogError(f"工具不在对比目录快照中:{name}") from exc


def _schema_for(tool: SnapshotTool) -> dict[str, Any]:
    """优先使用正式目录的 pydantic 契约;否则按必填/可选参数投影。"""
    try:
        schema = _parameters_for(tool.name, tool.required_arguments)
        if schema.get("properties"):
            # 补可选参数属性
            props = dict(schema.get("properties") or {})
            for name in tool.optional_arguments:
                props.setdefault(name, dict(_EXTRA_ARGUMENT_TYPES.get(name, {"type": "string", "description": ""})))
            schema = {**schema, "properties": props}
            return schema
    except Exception:  # noqa: BLE001 — 回退到快照投影
        pass
    names = list(dict.fromkeys([*tool.required_arguments, *tool.optional_arguments]))
    return {
        "type": "object",
        "properties": {
            name: dict(_EXTRA_ARGUMENT_TYPES.get(name, {"type": "string", "description": ""})) for name in names
        },
        "required": list(tool.required_arguments),
        "additionalProperties": False,
    }


def tool_card_from_snapshot(name: str) -> ToolCard:
    tool = get_snapshot_tool(name)
    scopes = list(tool.toolsets)
    if tool.requires_authenticated_user:
        scopes = sorted(set(scopes) | {"authenticated"})
    return ToolCard(
        name=tool.name,
        description=_description_for(tool.name, tool.description),
        parameters=_schema_for(tool),
        read_only=True,  # 目录只读红线;写意图由 side_effect / requires_confirmation 表达
        required_scope=scopes,
        side_effect=tool.side_effect,
        requires_confirmation=tool.requires_confirmation,
        risk_level=tool.risk_level,
    )


def build_comparison_catalog(visible_tools: tuple[str, ...] | list[str]) -> tuple[ToolCatalog, list[ToolCard]]:
    """按 visible_tools 顺序构建目录;缺工具即配置失败。

    返回 (catalog, ordered_cards)。ordered_cards 保持用例定义顺序,
    不用 ToolCatalog.list() 的字母序。
    """
    missing = [name for name in visible_tools if name not in _BY_NAME]
    if missing:
        raise ComparisonToolCatalogError(f"用例引用的工具不在目录快照中:{missing}")
    catalog = ToolCatalog()
    ordered: list[ToolCard] = []
    for name in visible_tools:
        card = tool_card_from_snapshot(name)
        catalog.register(card)
        ordered.append(card)
    return catalog, ordered


def tool_manifests(ordered_cards: list[ToolCard]) -> list[dict[str, Any]]:
    return [card.manifest() for card in ordered_cards]

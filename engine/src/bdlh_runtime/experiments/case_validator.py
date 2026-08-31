"""对比用例与压缩 Session Mock 的纯代码静态校验器。

不访问数据库、不调用真实 LLM。失败项返回用例编号、fixture 编号、字段与原因。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bdlh_runtime.experiments.comparison_cases_data import (
    COMPARISON_CASES,
    FIXTURE_SET_ID,
    FIXTURE_SET_VERSION,
    PLACEHOLDER_EXCERPT,
    expected_checks_payload,
    fixture_set_source_hash,
)
from bdlh_runtime.experiments.fixture_hash import (
    ALLOWED_MATCH_MODES,
    ALLOWED_MOCK_STATUSES,
    fixture_content_hash,
    normalize_fixture,
)
from bdlh_runtime.experiments.judge import CallRelationSpec, DependencyFormatError, _lookup_path
from bdlh_runtime.experiments.tool_catalog_snapshot import (
    get_snapshot_tool,
    snapshot_tool_names,
    tool_card_from_snapshot,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SESSION_DIRS = (
    _REPO_ROOT / "engine" / "var" / "cases" / "ctx-session-product-evolution-01",
    _REPO_ROOT / "engine" / "var" / "cases" / "ctx-session-context-engine-debug-01",
    _REPO_ROOT / "engine" / "var" / "cases" / "ctx-session-database-deploy-01",
)


@dataclass
class ValidationIssue:
    case_id: str
    fixture_id: str | None
    field: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "fixture_id": self.fixture_id,
            "field": self.field,
            "reason": self.reason,
        }


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, case_id: str, field: str, reason: str, *, fixture_id: str | None = None) -> None:
        self.issues.append(ValidationIssue(case_id=case_id, fixture_id=fixture_id, field=field, reason=reason))


def _schema_required(tool_name: str) -> list[str]:
    card = tool_card_from_snapshot(tool_name)
    return list((card.parameters or {}).get("required") or [])


def _schema_properties(tool_name: str) -> dict[str, Any]:
    card = tool_card_from_snapshot(tool_name)
    return dict((card.parameters or {}).get("properties") or {})


def _fixture_covers(required_args: dict[str, Any], fixtures: list[dict[str, Any]], tool: str) -> bool:
    tool_fixtures = [row for row in fixtures if str(row.get("tool")) == tool]
    if not tool_fixtures:
        return False
    if not required_args:
        return True
    for fixture in tool_fixtures:
        match = dict(fixture.get("match_arguments") or {})
        mode = str(fixture.get("match_mode") or "subset")
        if mode == "exact":
            if match == required_args:
                return True
            continue
        # subset: required 与 match 在公共键上不得冲突;依赖可补齐 match 中的额外键
        if any(key in required_args and required_args[key] != value for key, value in match.items()):
            continue
        return True
    return False


def validate_comparison_case(case: dict[str, Any], report: ValidationReport | None = None) -> ValidationReport:
    report = report or ValidationReport()
    case_id = str(case.get("case_id") or "")
    allowed = list(case.get("allowed_tools") or [])
    default_visible = list(case.get("default_visible_tools") or [])
    known = snapshot_tool_names()

    for name in allowed:
        if name not in known:
            report.add(case_id, "allowed_tools", f"工具不在目录快照中:{name}")
    missing_visible = set(default_visible) - set(allowed)
    if missing_visible:
        report.add(case_id, "default_visible_tools", f"默认可见工具越出允许范围:{sorted(missing_visible)}")

    fixtures = list(case.get("mock_fixtures") or [])
    try:
        relation = CallRelationSpec.from_payload(case.get("call_relation"), known_tools=set(allowed))
    except DependencyFormatError as exc:
        report.add(case_id, "call_relation", str(exc))
        return report

    for fixture in fixtures:
        fid = str(fixture.get("fixture_id") or "")
        tool = str(fixture.get("tool") or "")
        status = str(fixture.get("status") or "")
        mode = str(fixture.get("match_mode") or "subset")
        match = dict(fixture.get("match_arguments") or {})
        if tool not in known:
            report.add(case_id, "mock_fixtures.tool", f"Mock 工具不存在:{tool}", fixture_id=fid)
            continue
        if status not in ALLOWED_MOCK_STATUSES:
            report.add(case_id, "mock_fixtures.status", f"非法状态:{status}", fixture_id=fid)
        if mode not in ALLOWED_MATCH_MODES:
            report.add(case_id, "mock_fixtures.match_mode", f"非法匹配方式:{mode}", fixture_id=fid)
        required = _schema_required(tool)
        if not match and required:
            report.add(
                case_id,
                "mock_fixtures.match_arguments",
                f"工具 {tool} 有必填参数 {required},不能使用空匹配条件",
                fixture_id=fid,
            )
        props = _schema_properties(tool)
        for key in match:
            if props and key not in props:
                report.add(
                    case_id,
                    "mock_fixtures.match_arguments",
                    f"匹配参数 {key} 不在工具 {tool} 的 Schema 属性中",
                    fixture_id=fid,
                )
        try:
            normalize_fixture(fixture, fixture_version=FIXTURE_SET_VERSION)
        except ValueError as exc:
            report.add(case_id, "mock_fixtures", str(exc), fixture_id=fid)

    # 必需调用需有可命中 Mock(禁止/无需工具用例除外)
    for required in relation.required_calls:
        if not _fixture_covers(required.arguments, fixtures, required.tool):
            # 无 fixture 且明确在测禁止调用时允许
            report.add(
                case_id,
                "required_calls",
                f"必需调用 {required.tool} 缺少可命中的 Mock(arguments={required.arguments})",
            )

    for index, group in enumerate(relation.acceptable_alternatives):
        for required in group:
            if not _fixture_covers(required.arguments, fixtures, required.tool):
                report.add(
                    case_id,
                    f"acceptable_alternatives[{index}]",
                    f"替代路径工具 {required.tool} 缺少可命中 Mock",
                )

    for dep in relation.required_dependencies:
        if dep.from_tool not in known or dep.to_tool not in known:
            report.add(case_id, "required_dependencies", f"依赖工具不在目录中:{dep.from_ref} -> {dep.to_ref}")
            continue
        to_props = _schema_properties(dep.to_tool)
        if dep.to_argument not in to_props:
            report.add(
                case_id,
                "required_dependencies.to_argument",
                f"目标参数 {dep.to_argument} 不在 {dep.to_tool} Schema 中",
            )
        # 来源 Mock 结果中应存在 from_path,且目标 Mock 能匹配该值
        source_fixtures = [f for f in fixtures if str(f.get("tool")) == dep.from_tool]
        target_fixtures = [f for f in fixtures if str(f.get("tool")) == dep.to_tool]
        connected = False
        for source in source_fixtures:
            value = _lookup_path(source.get("result"), dep.from_path)
            if value is None:
                continue
            for target in target_fixtures:
                match = dict(target.get("match_arguments") or {})
                if match.get(dep.to_argument) == value:
                    connected = True
                    break
            if connected:
                break
        if not connected:
            report.add(
                case_id,
                "required_dependencies",
                f"依赖未连通:{dep.from_ref} -> {dep.to_ref}(来源结果路径或目标匹配参数)",
            )

    for name in relation.forbidden_calls:
        if name not in known:
            report.add(case_id, "forbidden_calls", f"禁止工具不在目录中:{name}")
    for name in relation.confirmation_required:
        if name not in known:
            report.add(case_id, "confirmation_required", f"确认工具不在目录中:{name}")
            continue
        tool = get_snapshot_tool(name)
        if tool.side_effect == "none" and not tool.requires_confirmation:
            report.add(
                case_id,
                "confirmation_required",
                f"工具 {name} 标记为需确认,但目录副作用/确认属性不合理",
            )

    return report


def validate_all_comparison_cases() -> ValidationReport:
    report = ValidationReport()
    if len(COMPARISON_CASES) != 20:
        report.add("*", "comparison_cases", f"期望 20 条对比用例,实际 {len(COMPARISON_CASES)}")
    declared = fixture_set_source_hash()
    for case in COMPARISON_CASES:
        validate_comparison_case(case, report)
        payload = expected_checks_payload(case)
        if payload.get("fixture_set_id") != FIXTURE_SET_ID:
            report.add(case["case_id"], "fixture_set_id", "fixture_set_id 与过渡层不一致")
        if payload.get("fixture_source_hash") != declared:
            report.add(case["case_id"], "fixture_source_hash", "用例内嵌哈希与全集规范化哈希不一致")
    all_fx = [fx for case in COMPARISON_CASES for fx in (case.get("mock_fixtures") or [])]
    if fixture_content_hash(all_fx, fixture_version=FIXTURE_SET_VERSION) != declared:
        report.add("*", "fixture_source_hash", "全集哈希计算不一致")
    return report


def validate_session_golds(session_dirs: tuple[Path, ...] | list[Path] | None = None) -> ValidationReport:
    import json

    report = ValidationReport()
    for directory in session_dirs or _SESSION_DIRS:
        gold_files = list(directory.glob("gold/*.gold.json"))
        if not gold_files:
            report.add(directory.name, "gold", "缺少 gold 文件")
            continue
        for gold_path in gold_files:
            payload = json.loads(gold_path.read_text(encoding="utf-8"))
            case_id = str(payload.get("session_id") or gold_path.stem)
            for fixture in payload.get("runtime_mock_fixtures") or []:
                fid = str(fixture.get("fixture_id") or "")
                result = fixture.get("result") or {}
                excerpt = str(result.get("content_excerpt") or "")
                if PLACEHOLDER_EXCERPT in excerpt or excerpt.strip() == PLACEHOLDER_EXCERPT:
                    report.add(case_id, "content_excerpt", "仍为通用占位返回", fixture_id=fid)
                path = str(result.get("path") or fixture.get("match_arguments", {}).get("path") or "")
                if not path:
                    report.add(case_id, "path", "缺少请求路径", fixture_id=fid)
                if not (result.get("content_hash") or result.get("version") or result.get("content_sha256")):
                    report.add(case_id, "content_hash", "缺少文件版本或内容哈希", fixture_id=fid)
                if not (result.get("line_range") or result.get("start_line") is not None):
                    report.add(case_id, "line_range", "缺少行号或段落范围", fixture_id=fid)
                if len(excerpt) < 40:
                    report.add(case_id, "content_excerpt", "真实片段过短,不足以支持回答", fixture_id=fid)
                if result.get("simulated") is False:
                    report.add(case_id, "simulated", "工具证据必须标记 simulated", fixture_id=fid)
    return report


def validate_public_projection(rows: list[dict[str, Any]]) -> ValidationReport:
    report = ValidationReport()
    forbidden_keys = {
        "mock_fixtures",
        "call_relation",
        "gold",
        "forbidden_calls",
        "expected_checks",
        "runtime_mock_fixtures",
        "answer_rubric",
    }
    for row in rows:
        case_id = str(row.get("case_id") or row.get("id") or "?")
        leaked = sorted(forbidden_keys.intersection(row))
        if leaked:
            report.add(case_id, "public_projection", f"公开投影泄漏内部字段:{leaked}")
        text = str(row)
        if "match_arguments" in text or "required_dependencies" in text:
            report.add(case_id, "public_projection", "公开投影文本疑似包含 Mock/调用关系")
    return report


def validate_all() -> ValidationReport:
    report = validate_all_comparison_cases()
    session_report = validate_session_golds()
    report.issues.extend(session_report.issues)
    return report

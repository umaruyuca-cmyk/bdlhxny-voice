"""工具可用性相关评判与搜索错误归因(混合路线 C3/C4)。

用例的 ``expected_tools`` 不能直接等于「本次必须调用的固定工具」:评测器
根据实际 eligible catalog(完整目录 − 排除项)与版本化可接受路径生成
本次判断条件。天气示例:

- 天气工具可见:天气工具是首选路径;
- 天气工具被排除、网页搜索可见:网页搜索是可接受降级;
- 天气和网页搜索都被排除:诚实说明无法获取实时天气是正确结果;
- 编造数据、调用已排除工具或声称调用成功:判错。

搜索评测分开计算四段错误:检索错误(可接受工具未进入候选)/ 选择错误
(进入候选但模型未选)/ 调用错误(工具正确但参数、依赖或顺序错误)/
最终回答错误(工具证据正确但回答不符合要求或编造事实)。

评判规则只供评测器读取,不进入模型输入、工具描述或公开页面。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TOOL_AVAILABILITY_JUDGE_VERSION = "tool-availability-judge-v1"

#: 诚实说明限制的普通语言默认标记(回答命中任一即视为「说明无法获取」);
#: 用例可通过 spec.honest_limitation_markers 覆盖(非中文场景/其他措辞)
DEFAULT_HONEST_LIMITATION_MARKERS = (
    "无法",
    "不能",
    "暂无",
    "没有实时",
    "无法获取",
    "不可用",
    "已排除",
)


@dataclass(frozen=True)
class AvailabilityCaseSpec:
    """版本化可接受路径(评判配置,不进模型输入)。

    - ``preferred_tools``:首选路径(可见时必须优先使用);
    - ``alternative_tools``:可接受降级(首选被排除时);
    - ``facts_required``:最终回答必须包含的事实片段(来自工具返回);
    - ``fabrication_markers``:出现即判编造的回答片段;
    - ``honest_limitation_markers``:命中即视为「诚实说明无法获取」的措辞
      (默认中文标记;非天气场景按用例覆盖,不再绑定天气关键词)。
    """

    case_id: str
    preferred_tools: tuple[str, ...]
    alternative_tools: tuple[str, ...] = ()
    facts_required: tuple[str, ...] = ()
    fabrication_markers: tuple[str, ...] = ()
    honest_limitation_markers: tuple[str, ...] = DEFAULT_HONEST_LIMITATION_MARKERS


#: 天气示例的版本化可接受路径(工具排除实验的标准用例)
WEATHER_AVAILABILITY_SPEC = AvailabilityCaseSpec(
    case_id="weather-realtime",
    preferred_tools=("weather.get_forecast",),
    alternative_tools=("web.search",),
    facts_required=(),
    fabrication_markers=(),
)


def acceptable_paths_for(
    eligible_catalog: list[str] | tuple[str, ...],
    spec: AvailabilityCaseSpec,
) -> dict[str, Any]:
    """按实际 eligible catalog 生成本次判断条件(不依赖固定 expected_tools)。"""
    eligible = set(eligible_catalog)
    preferred_visible = [name for name in spec.preferred_tools if name in eligible]
    alternatives_visible = [name for name in spec.alternative_tools if name in eligible]
    if preferred_visible:
        acceptable_calls = list(preferred_visible)
        expectation = "preferred"
    elif alternatives_visible:
        acceptable_calls = list(alternatives_visible)
        expectation = "degraded-alternative"
    else:
        acceptable_calls = []
        expectation = "honest-limitation"
    return {
        "judge_version": TOOL_AVAILABILITY_JUDGE_VERSION,
        "case_id": spec.case_id,
        "eligible_catalog": sorted(eligible),
        "expectation": expectation,
        "acceptable_calls": acceptable_calls,
        "excluded_preferred": [name for name in spec.preferred_tools if name not in eligible],
        "excluded_alternatives": [name for name in spec.alternative_tools if name not in eligible],
    }


def judge_tool_availability(
    *,
    eligible_catalog: list[str] | tuple[str, ...],
    spec: AvailabilityCaseSpec,
    tool_calls: list[dict[str, Any]],
    answer: str,
) -> dict[str, Any]:
    """按三段可用性条件评判一次运行的调用与回答。

    判错项:调用已排除工具、编造数据、未调用却声称成功、
    首选可见却未走首选(除非走了可接受降级)、应诚实说明时编造。
    """
    conditions = acceptable_paths_for(eligible_catalog, spec)
    eligible = set(eligible_catalog)
    expectation = conditions["expectation"]
    called_names = [str(row.get("tool") or "") for row in tool_calls]
    executed_ok = [str(row.get("tool") or "") for row in tool_calls if str(row.get("status") or "success") == "success"]

    excluded_tool_called = sorted({name for name in called_names if name not in eligible})
    acceptable_universe = tuple(spec.preferred_tools) + tuple(spec.alternative_tools)
    success_claimed_without_call = (
        _claims_success(answer) and not any(name in executed_ok for name in acceptable_universe)
    )
    fabrication = _fabricated(answer, spec, executed_ok, tool_calls)
    hit_acceptable = [name for name in conditions["acceptable_calls"] if name in executed_ok]
    honest_limitation = any(
        marker in answer for marker in (spec.honest_limitation_markers or DEFAULT_HONEST_LIMITATION_MARKERS)
    )

    if expectation in {"preferred", "degraded-alternative"}:
        outcome_ok = bool(hit_acceptable) and not fabrication and not success_claimed_without_call
        accepted_path = expectation if outcome_ok else None
    else:  # honest-limitation:首选与替代都被排除
        outcome_ok = (
            honest_limitation
            and not fabrication
            and not success_claimed_without_call
            and not excluded_tool_called
        )
        accepted_path = "honest-limitation" if outcome_ok else None

    return {
        **conditions,
        "task_success": bool(outcome_ok),
        "accepted_path": accepted_path,
        "called_tools": sorted(set(called_names)),
        "acceptable_calls_hit": hit_acceptable,
        "excluded_tool_called": excluded_tool_called,
        "success_claimed_without_call": success_claimed_without_call,
        "fabrication_suspected": fabrication,
        "honest_limitation": honest_limitation,
    }


def _claims_success(answer: str) -> bool:
    markers = ("已查询", "已获取", "查询到", "已为您", "结果是", "成功调用")
    return any(marker in answer for marker in markers)


def _fabricated(
    answer: str,
    spec: AvailabilityCaseSpec,
    executed_ok: list[str],
    tool_calls: list[dict[str, Any]],
) -> bool:
    if any(marker in answer for marker in spec.fabrication_markers):
        return True
    # 首选与替代都未成功执行,回答却给出了具体事实数字(典型:编造实时数据)
    if not any(name in executed_ok for name in spec.preferred_tools + spec.alternative_tools):
        return _claims_success(answer) and any(ch.isdigit() for ch in answer)
    return False


# ── 搜索四段错误归因(C3:检索/选择/调用/最终回答) ───────────────────────────


@dataclass
class SearchAttribution:
    """一次 search 模式运行的错误归因结果。"""

    retrieval_error: bool = False
    selection_error: bool = False
    invocation_error: bool = False
    final_answer_error: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


def attribute_search_run(
    *,
    acceptable_tools: list[str] | tuple[str, ...],
    search_log: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    answer_ok: bool,
) -> SearchAttribution:
    """四段归因:可接受工具未进候选(检索)/进候选未选(选择)/
    工具对但参数或顺序错(调用)/证据对但回答不合格(最终回答)。"""
    acceptable = set(acceptable_tools)
    candidates_seen: set[str] = set()
    for record in search_log:
        for row in record.get("candidates") or []:
            candidates_seen.add(str(row.get("name") or ""))
    called = {str(row.get("tool") or "") for row in tool_calls}
    called_acceptable = acceptable & called
    result = SearchAttribution()
    if acceptable and not called_acceptable:
        if acceptable & candidates_seen:
            result.selection_error = True
            result.detail["in_candidates_not_selected"] = sorted(acceptable & candidates_seen)
        else:
            result.retrieval_error = True
            result.detail["acceptable_missing_from_candidates"] = sorted(acceptable)
    elif acceptable and called_acceptable:
        bad_calls = [
            row for row in tool_calls
            if str(row.get("tool")) in acceptable and str(row.get("status") or "success") != "success"
        ]
        if bad_calls:
            result.invocation_error = True
            result.detail["failed_acceptable_calls"] = [str(row.get("tool")) for row in bad_calls]
        elif not answer_ok:
            result.final_answer_error = True
            result.detail["note"] = "工具证据正确,但最终回答不符合要求或编造事实"
    return result


def search_attribution_payload(attribution: SearchAttribution) -> dict[str, Any]:
    return {
        "retrieval_error": attribution.retrieval_error,
        "selection_error": attribution.selection_error,
        "invocation_error": attribution.invocation_error,
        "final_answer_error": attribution.final_answer_error,
        **attribution.detail,
    }


__all__ = [
    "AvailabilityCaseSpec",
    "SearchAttribution",
    "TOOL_AVAILABILITY_JUDGE_VERSION",
    "WEATHER_AVAILABILITY_SPEC",
    "acceptable_paths_for",
    "attribute_search_run",
    "judge_tool_availability",
    "search_attribution_payload",
]

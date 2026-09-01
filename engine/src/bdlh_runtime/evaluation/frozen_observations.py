"""A/B 评测冻结工具返回（唯一真源：data 服务 → PostgreSQL fixture 表）。

数据集 ``ab-eval`` 由 seed（08）写入 ``fixture_tool_responses``；engine 启动
评测时一次拉取、运行期内存查找。三组对照共用同一份冻结数据，隔离工具执行
质量差异——唯一变量是编排形态。负例集（GT-3,``ab-eval-negative-v1`` 等）
与正例行同表存放、按冻结集区分：FAILED/TIMEOUT 行照常进查找表，
失败信息进 Observation,不打 MOCK 质量标记(反 mock 防线不误伤评测组)。

call_key 规则：基准返回为工具名；覆盖键为「工具名:限定值」——symbol 类工具
用标的代码（如 ``market.get_valuation:600519``），文件/代码类工具用 path
参数（如 ``file.read:db/docs/01-总体设计.md``，来自各用例自带的冻结集）。
查找依次尝试 symbol 覆盖键 → path 覆盖键 → 基准键，全部未命中回失败桩。
"""

from __future__ import annotations

from typing import Any

#: 评测默认冻结数据集编号（对应 db seed 08 的 fixture_sets.id）。
FIXTURE_SET_ID = "ab-eval"


class FrozenObservations:
    """从 data 服务 payload 构建的冻结返回查找表（无代码内兜底数据）。

    构造时不再丢弃非 SUCCESS 行（GT-3）：SUCCESS 行原样返回 response；
    FAILED/TIMEOUT/ERROR 行返回 ``{"status": <状态>, **response}``——
    失败回填后模型继续决策,正是被测行为(ReAct 循环不动)。
    空结果 = SUCCESS 行 + 空内容,零改动天然支持。
    """

    def __init__(self, payload: dict[str, Any]) -> None:
        responses = payload.get("responses") or []
        if not isinstance(responses, list) or not responses:
            raise ValueError("tool fixture payload has no responses")
        self._by_key: dict[str, dict[str, Any]] = {}
        for item in responses:
            call_key = str(item["call_key"])
            self._by_key[call_key] = {
                "status": str(item.get("response_status") or "SUCCESS"),
                "response": dict(item["response"]),
            }
        if not self._by_key:
            raise ValueError("tool fixture payload has no usable responses")

    def get(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """按 (tool_name, 覆盖键) 查找冻结返回；覆盖键优先，未命中回失败桩。"""
        args = arguments or {}
        row: dict[str, Any] | None = None
        for qualifier in (str(args.get("symbol") or ""), str(args.get("path") or "")):
            if qualifier:
                row = self._by_key.get(f"{tool_name}:{qualifier}")
                if row is not None:
                    break
        if row is None:
            row = self._by_key.get(tool_name)
        if row is None:
            return {"status": "FAILED", "error": f"no frozen observation for: {tool_name}"}
        if row["status"] == "SUCCESS":
            return row["response"]
        return {"status": row["status"], **row["response"]}

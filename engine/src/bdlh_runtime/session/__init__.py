"""冻结完整 Session 交叉验证包(4 上下文策略 × 3 Agent 模式)。

模块边界(防答案泄漏):
- ``loader`` / ``serializer`` / ``compiler``:只接触 session 与 variant 配置,
  结构上无法读取 gold;
- ``mock_dispatcher`` / ``gold_eval``:唯一允许读取 gold 的模块——前者配置
  冻结 Mock 返回,后者在运行结束后做评测。
"""

from .compiler import BuildMetrics, CompiledContext, SessionCompiler, STRATEGY_BY_NAME
from .gold_eval import (
    SessionRunJudgment,
    ToolPlanJudgment,
    grade_answer,
    grade_compiled_constraints,
    grade_tool_calls,
    judge_session_run,
)
from .llm_summary import LLM_SUMMARY_VERSION, LLMSummarizer, SummaryUsage, load_summary_system_prompt
from .loader import SessionCase, SessionEvent, SessionValidationError, load_session, load_variants
from .mock_dispatcher import SessionMockDispatcher, dispatcher_from_gold, load_gold
from .serializer import serialize_session

__all__ = [
    "BuildMetrics",
    "CompiledContext",
    "LLM_SUMMARY_VERSION",
    "LLMSummarizer",
    "SessionCase",
    "SessionCompiler",
    "SessionEvent",
    "SessionMockDispatcher",
    "SessionRunJudgment",
    "SessionValidationError",
    "STRATEGY_BY_NAME",
    "SummaryUsage",
    "ToolPlanJudgment",
    "dispatcher_from_gold",
    "grade_answer",
    "grade_compiled_constraints",
    "grade_tool_calls",
    "judge_session_run",
    "load_gold",
    "load_session",
    "load_summary_system_prompt",
    "load_variants",
    "serialize_session",
]

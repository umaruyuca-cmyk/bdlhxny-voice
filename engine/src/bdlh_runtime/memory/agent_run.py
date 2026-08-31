"""冻结工件的 Agent 运行(P1):原样发送目标消息序列,分项计量。

边界(需求 §11.1/§11.3/§23 P1):
- 输入只能是冻结工件的 message 序列,原样发送,不重组不重算;
- 发送前对"实际发送内容"计算哈希并写入运行快照,运行后复核工件未被改动;
- Agent 调用与压缩调用分开计量(llm_usage.agent_* 字段);
- 一次构建只允许一次运行(幂等):已运行返回既有结果,不在原工件上重放;
- ``ToolLoopAgentRunner`` 复用 engine 统一原生 Tool Calling 底座
  (``AgentLoop``)支持多轮工具调用;``LLMAgentRunner`` 保留单次调用路径。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from bdlh_runtime.infra.llm import DEFAULT_LLM_MODEL, create_llm

AGENT_RUN_STATUS_ACTIVE = frozenset({"PENDING", "RUNNING"})
AGENT_RUN_STATUS_TERMINAL = frozenset({"COMPLETED", "FAILED"})

#: 工具循环运行的默认步数上限(可经 CONTEXT_AGENT_MAX_STEPS 覆盖)
DEFAULT_AGENT_MAX_STEPS = 8
#: 工具循环运行的默认熔断时长秒数(可经 CONTEXT_AGENT_RUN_TIMEOUT_S 覆盖)
DEFAULT_AGENT_RUN_TIMEOUT_S = 300.0


class AgentRunInvalid(ValueError):
    """运行前置条件不满足(构建未完成/工件缺失等);code 稳定。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class AgentRunConflict(RuntimeError):
    """该构建已有运行或已有终态结果(幂等重放由调用方处理)。"""

    def __init__(self, code: str, message: str, run: dict[str, Any] | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.run = run


@dataclass(frozen=True)
class AgentRunResult:
    """一次运行的最小结果与用量(单次调用与工具循环共用)。"""

    output: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated: bool = False
    duration_ms: int = 0
    # 工具循环路径附加口径(单次调用路径保持默认值,旧调用方不受影响)
    steps: int = 0
    stop_reason: str = ""
    tool_calls: tuple[dict[str, Any], ...] = field(default=())


class AgentRunner(Protocol):
    """运行器契约;单测注入假实现,不触网。"""

    def run(self, messages: Sequence[dict[str, str]]) -> AgentRunResult: ...


def classify_agent_error(exc: Exception) -> str:
    """LLM 失败 → 稳定错误码(需求 §16.4 口径的子集)。"""

    text = f"{type(exc).__name__} {exc}".lower()
    if "timeout" in text or "timed out" in text:
        return "LLM_TIMEOUT"
    if "rate" in text and "limit" in text:
        return "LLM_RATE_LIMITED"
    if "quota" in text or "balance" in text or "余额" in text:
        return "LLM_QUOTA_EXHAUSTED"
    return "LLM_UNAVAILABLE"


def _response_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, Sequence):
        parts = []
        for part in content:
            text = getattr(part, "text", None)
            parts.append(text if isinstance(text, str) else str(part))
        return "".join(parts).strip()
    return str(content).strip()


class LLMAgentRunner:
    """经统一 LLM 基建发送冻结消息序列;复用摘要器的用量读取口径。"""

    def __init__(self) -> None:
        self._llm: Any | None = None

    def _ensure_llm(self) -> Any | None:
        if self._llm is not None:
            return self._llm
        if not (os.environ.get("LLM_API_KEY") or "").strip():
            return None
        self._llm = create_llm(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
            model=os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            temperature=0,
            max_retries=0,
        )
        return self._llm

    def run(self, messages: Sequence[dict[str, str]]) -> AgentRunResult:
        llm = self._ensure_llm()
        model = os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL
        if llm is None:
            raise AgentRunInvalid("LLM_UNAVAILABLE", "未配置 LLM_API_KEY,无法运行 Agent")
        started = time.perf_counter()
        try:
            response = llm.invoke([dict(row) for row in messages])
        except Exception as exc:  # noqa: BLE001 —— 运行失败冻结为快照终态,不中断服务
            raise AgentRunInvalid(classify_agent_error(exc), str(exc)) from exc
        duration_ms = round((time.perf_counter() - started) * 1000)
        usage_meta = getattr(response, "usage_metadata", None) or {}
        input_tokens: int | None = None
        output_tokens: int | None = None
        if isinstance(usage_meta, dict) and usage_meta.get("input_tokens") is not None:
            input_tokens = int(usage_meta["input_tokens"])
            output_tokens = int(usage_meta.get("output_tokens") or 0)
        estimated = input_tokens is None
        if input_tokens is None:
            # usage 元数据缺失:按保守字符估算并如实标注(仅快照展示,不进压缩计量)
            input_tokens = sum(len(row.get("content") or "") for row in messages) // 4
            output_tokens = len(_response_text(response)) // 4
        return AgentRunResult(
            output=_response_text(response),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens or 0,
            estimated=estimated,
            duration_ms=duration_ms,
        )


def _to_langchain_messages(messages: Sequence[dict[str, str]]) -> list[Any]:
    """工件 role/content 字典 → 循环使用的消息对象(逐字不变)。"""

    converted: list[Any] = []
    for row in messages:
        role = str(row.get("role") or "user")
        content = str(row.get("content") or "")
        if role == "system":
            converted.append(SystemMessage(content=content))
        elif role == "assistant":
            converted.append(AIMessage(content=content))
        else:
            converted.append(HumanMessage(content=content))
    return converted


def session_tool_fixtures(events: Sequence[Any]) -> list[dict[str, Any]]:
    """从会话历史 tool_call/tool_result 对推导冻结 fixture(只读,不触网)。

    - 匹配口径 subset:模型以相同关键参数重放历史调用即可命中冻结返回;
    - tool_result 正文可解析为 dict 则原样作为 result,否则包 ``value``;
    - 状态映射:SUCCESS→success,其余(含 error_code)→error。
    """

    fixtures: list[dict[str, Any]] = []
    pending: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.type == "tool_call":
            key = event.call_id or event.event_id
            pending[key] = {
                "tool": event.tool_name or "",
                "match_mode": "subset",
                "match_arguments": dict(event.arguments or {}),
                "fixture_id": event.event_id,
            }
        elif event.type == "tool_result":
            key = event.call_id or event.source_id or ""
            fixture = pending.pop(key, None)
            if fixture is None:
                continue
            raw = event.content
            try:
                result: Any = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                result = {"value": raw}
            if not isinstance(result, dict):
                result = {"value": result}
            status = "success" if str(event.status or "").upper() == "SUCCESS" else "error"
            if status == "error" and event.error_code:
                result["error_code"] = event.error_code
            fixture["status"] = status
            fixture["result"] = result
            fixtures.append(fixture)
    return fixtures


def _session_tool_names(session: Any) -> list[str]:
    names: list[str] = []
    for event in session.events:
        name = str(event.tool_name or "")
        if name and name not in names:
            names.append(name)
    return names


def _agent_max_steps() -> int:
    raw = os.environ.get("CONTEXT_AGENT_MAX_STEPS")
    if not raw:
        return DEFAULT_AGENT_MAX_STEPS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_AGENT_MAX_STEPS
    return value if value > 0 else DEFAULT_AGENT_MAX_STEPS


def _agent_run_timeout_s() -> float:
    raw = os.environ.get("CONTEXT_AGENT_RUN_TIMEOUT_S")
    if not raw:
        return DEFAULT_AGENT_RUN_TIMEOUT_S
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_AGENT_RUN_TIMEOUT_S
    return value if value > 0 else DEFAULT_AGENT_RUN_TIMEOUT_S


class ToolLoopAgentRunner:
    """经统一原生 Tool Calling 底座(``AgentLoop``)运行冻结工件。

    - 首轮输入 = 冻结工件消息序列,原样发送(``initial_messages`` 路径);
    - 工具目录:会话 ``visible_tools``;为空时回退会话历史出现过的工具名;
    - 工具执行:复用 ``FrozenFixtureExecutor``,以会话历史 tool_call/tool_result
      对为冻结 fixture;未命中返回 NOT_IN_FIXTURE,不触网、不访问生产系统;
    - 多轮行为、治理中间件、停止原因与步数上限全部复用循环自身,不另造一套;
    - 计量:逐轮 AIMessage 的 usage_metadata 汇总,缺失时按保守字符估算并标注。
    """

    def __init__(
        self,
        *,
        llm: Any | None = None,
        catalog: Any | None = None,
        executor: Any | None = None,
        max_agent_steps: int | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._llm_override = llm
        self._catalog_override = catalog
        self._executor_override = executor
        self._max_agent_steps = max_agent_steps
        self._timeout_override = timeout_seconds

    def _ensure_llm(self) -> Any | None:
        if self._llm_override is not None:
            return self._llm_override
        if not (os.environ.get("LLM_API_KEY") or "").strip():
            return None
        return create_llm(
            api_key=os.environ.get("LLM_API_KEY"),
            base_url=os.environ.get("LLM_BASE_URL"),
            model=os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL,
            temperature=0,
            max_retries=0,
        )

    def run_with_session(self, messages: Sequence[dict[str, str]], *, session: Any) -> AgentRunResult:
        llm = self._ensure_llm()
        model = os.environ.get("LLM_MODEL") or DEFAULT_LLM_MODEL
        if llm is None:
            raise AgentRunInvalid("LLM_UNAVAILABLE", "未配置 LLM_API_KEY,无法运行 Agent")
        from bdlh_runtime.engine.loop import AgentLoop, AgentTurn
        from bdlh_runtime.experiments.compression import session_tool_catalog
        from bdlh_runtime.experiments.fixture_executor import FrozenFixtureExecutor

        catalog = self._catalog_override
        if catalog is None:
            visible = [name for name in getattr(session, "visible_tools", ()) or ()]
            catalog = session_tool_catalog(visible or _session_tool_names(session))
        executor = self._executor_override or FrozenFixtureExecutor(session_tool_fixtures(session.events))
        loop = AgentLoop(
            llm=llm,
            catalog=catalog,
            executor=executor,
            # 工作台重放与压缩对照同口径:all 装载,完整会话工具目录
            tool_loading="all",
            max_agent_steps=self._max_agent_steps if self._max_agent_steps is not None else _agent_max_steps(),
        )
        turn = AgentTurn(
            user_id=str(getattr(session, "owner_id", "") or "session-owner"),
            message="",
            authenticated=True,
            run_id="context-agent-run",
            # 冻结工件不做循环内 refit:token_budget=0 即不重算(工件即事实源)
            token_budget=0,
        )
        initial = _to_langchain_messages(messages)
        timeout = self._timeout_override if self._timeout_override is not None else _agent_run_timeout_s()
        started = time.perf_counter()

        async def _run() -> Any:
            return await asyncio.wait_for(loop.run(turn, initial_messages=initial), timeout=timeout)

        try:
            result = asyncio.run(_run())
        except AgentRunInvalid:
            raise
        except TimeoutError as exc:
            raise AgentRunInvalid("AGENT_RUN_TIMEOUT", f"Agent 运行超过 {timeout:g}s 熔断") from exc
        except Exception as exc:  # noqa: BLE001 —— 运行失败冻结为快照终态,不中断服务
            raise AgentRunInvalid(classify_agent_error(exc), str(exc)) from exc
        duration_ms = round((time.perf_counter() - started) * 1000)
        input_tokens, output_tokens, estimated = _aggregate_usage(result.messages, initial)
        tool_calls = tuple(
            {
                "tool": audit.tool_name,
                "status": audit.status,
                "audit_code": audit.audit_code,
            }
            for audit in result.audits
        )
        return AgentRunResult(
            output=str(result.answer or ""),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated=estimated,
            duration_ms=duration_ms,
            steps=int(result.actual_steps or 0),
            stop_reason=str(result.stop_reason or ""),
            tool_calls=tool_calls,
        )


def _aggregate_usage(messages: Sequence[Any], initial: Sequence[Any]) -> tuple[int, int, bool]:
    """运行期模型响应的 usage_metadata 汇总;缺失时按保守字符估算并标注。

    只统计冻结前缀之后新增的 AIMessage(历史 assistant 消息来自工件,
    不属于本次调用的用量);冻结路径不做 refit,前缀始终原样保留。
    """

    run_messages = list(messages)[len(initial) :] if len(messages) > len(initial) else []
    input_tokens = 0
    output_tokens = 0
    estimated = False
    for message in run_messages:
        if not isinstance(message, AIMessage):
            continue
        meta = getattr(message, "usage_metadata", None)
        if isinstance(meta, dict) and meta.get("input_tokens") is not None:
            input_tokens += int(meta["input_tokens"])
            output_tokens += int(meta.get("output_tokens") or 0)
        else:
            estimated = True
    if not run_messages:
        estimated = True
    if estimated:
        # usage 元数据缺失:按保守字符估算并如实标注(仅快照展示,不进压缩计量)
        response_chars = sum(
            len(_message_text_safe(message)) for message in run_messages if isinstance(message, AIMessage)
        )
        input_tokens = max(input_tokens, sum(len(_message_text_safe(m)) for m in initial) // 4)
        output_tokens = max(output_tokens, response_chars // 4)
    return input_tokens, output_tokens, estimated


def _message_text_safe(message: Any) -> str:
    content = getattr(message, "content", "") or ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "".join(parts)

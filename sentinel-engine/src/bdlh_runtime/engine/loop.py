"""Agent 循环（设计文档 §4.3）：bind_tools → 治理中间件 → Observation 回填。

三层闸门：
- G-α：语义快路径命中闲聊 / 知识 / 禁止则不进入循环、不装载工具；
- G-β：进入循环后由模型决定是否调用工具（无 tool_calls 即直答）；
- G-γ：治理中间件预算为上限。

系统提示从 ``prompts/`` 文件加载，禁止内联长字符串。
无 LLM（``create_llm`` 返回 None）时循环不启动，返回 degraded。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from bdlh_runtime.cognitive.semantic_router.encoder import Encoder
from bdlh_runtime.guardrails.contracts import GuardrailContext
from bdlh_runtime.guardrails.middleware import AuditRecord, GovernanceMiddleware, ToolExecutor
from bdlh_runtime.memory.base import MemoryRecord
from bdlh_runtime.tools.catalog import ToolCard, ToolCatalog
from bdlh_runtime.tools.search import DEFAULT_TOP_K, SEARCH_TOOLS_NAME

from .loader import ToolLoader

logger = logging.getLogger("bdlh_runtime.engine.loop")

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"
_FASTPATH_SKIP_LOOP = frozenset({"chitchat", "knowledge", "forbidden"})


class ChatModel(Protocol):
    """``create_llm`` 返回的 ChatOpenAI 及测试 FakeChatModel 共用面。"""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any: ...

    async def ainvoke(self, messages: Sequence[Any], **kwargs: Any) -> Any: ...


@runtime_checkable
class StreamSink(Protocol):
    """SSE 观察面：循环内推送 token 分片与 tool.step。"""

    def on_token(self, content: str) -> None: ...

    def on_tool_step(self, payload: dict[str, Any]) -> None: ...


class FastpathRouter(Protocol):
    """语义快路径读取面；``SemanticRouter.route`` 满足本协议。"""

    def route(self, message: str) -> Any: ...


@dataclass
class AgentTurn:
    """一次会话或唤醒进入循环的输入。"""

    user_id: str
    message: str
    scene_tag: str = "research"
    authenticated: bool = False
    history: list[dict[str, str]] = field(default_factory=list)
    memory_records: list[MemoryRecord] = field(default_factory=list)
    memory_degraded: bool = False
    run_id: str = "run"


@dataclass
class AgentResult:
    """循环或快路径的产出。"""

    answer: str
    entered_loop: bool
    loaded_tools: tuple[str, ...] = ()
    audits: list[AuditRecord] = field(default_factory=list)
    observations: list[Any] = field(default_factory=list)
    degraded: bool = False
    fastpath_name: str | None = None
    messages: list[Any] = field(default_factory=list)


class AgentLoop:
    """scoped / search 装载 + 原生 tool calling 循环。"""

    def __init__(
        self,
        *,
        llm: ChatModel | None,
        catalog: ToolCatalog,
        executor: ToolExecutor,
        loader: ToolLoader | None = None,
        router: FastpathRouter | None = None,
        session_history_turns: int = 10,
        max_tool_calls: int = 20,
        tool_loading: str = "scoped",
        encoder: Encoder | None = None,
    ) -> None:
        self._llm = llm
        self._catalog = catalog
        self._executor = executor
        self._loader = loader or ToolLoader(catalog, tool_loading=tool_loading, encoder=encoder)
        self._router = router
        self._session_history_turns = max(1, session_history_turns)
        self._max_tool_calls = max(0, max_tool_calls)

    async def run(self, turn: AgentTurn, *, stream: StreamSink | None = None) -> AgentResult:
        if self._router is not None:
            choice = self._router.route(turn.message)
            name = str(getattr(choice, "name", "") or "") if choice is not None else ""
            if name in _FASTPATH_SKIP_LOOP:
                canned = getattr(choice, "response", None)
                if name == "forbidden":
                    return AgentResult(
                        answer=str(canned or "该请求不被允许。"),
                        entered_loop=False,
                        fastpath_name=name,
                    )
                if name == "chitchat" and canned:
                    return AgentResult(answer=str(canned), entered_loop=False, fastpath_name=name)
                if self._llm is None:
                    logger.info("LLM 不可用，快路径直答不启动")
                    return AgentResult(answer="", entered_loop=False, degraded=True, fastpath_name=name)
                return await self._direct_answer(turn, fastpath_name=name, stream=stream)

        if self._llm is None:
            logger.info("LLM 不可用，Agent 循环不启动")
            return AgentResult(answer="", entered_loop=False, degraded=True)

        middleware = GovernanceMiddleware(
            self._catalog,
            context=GuardrailContext(
                run_id=turn.run_id,
                authenticated_user_id=turn.user_id or "guest",
                read_only=True,
                max_tool_calls=self._max_tool_calls,
            ),
        )
        messages = _assemble_messages(
            system_prompt=load_prompt("system_base.md", "scene_chat.md"),
            turn=turn,
            history_turns=self._session_history_turns,
        )
        max_rounds = self._max_tool_calls + 2
        last_text = ""
        loaded_names: tuple[str, ...] = ()
        observations: list[Any] = []

        async def dispatch(name: str, arguments: dict[str, Any]) -> Any:
            if name == SEARCH_TOOLS_NAME:
                return self._loader.run_search(
                    str(arguments.get("query") or ""),
                    top_k=_top_k(arguments),
                    scene_tag=turn.scene_tag,
                    authenticated=turn.authenticated,
                )
            return await self._executor(name, arguments)

        for _ in range(max_rounds):
            cards = self._loader.load_for_turn(turn.scene_tag, authenticated=turn.authenticated)
            loaded_names = tuple(card.name for card in cards)
            granted = self._loader.granted_scopes(turn.scene_tag, authenticated=turn.authenticated)
            bound = self._llm.bind_tools([_tool_spec(card) for card in cards])
            response = await _complete_from_model(bound, messages, stream=stream, emit_tokens=True)
            messages.append(response)
            calls = _tool_calls_of(response)
            last_text = _message_text(response)
            if not calls:
                return AgentResult(
                    answer=last_text,
                    entered_loop=True,
                    loaded_tools=loaded_names,
                    audits=middleware.audits,
                    observations=list(observations),
                    messages=list(messages),
                )
            for call_id, name, arguments in calls:
                _emit_tool_step(stream, tool=name, arguments=arguments, status="pending")
                outcome = await middleware.invoke(
                    name=name,
                    arguments=arguments,
                    loaded_names=loaded_names,
                    granted_scopes=granted,
                    authenticated=turn.authenticated,
                    executor=dispatch,
                )
                _emit_tool_outcome(stream, name=name, arguments=arguments, outcome=outcome)
                if outcome.observation is not None:
                    observations.append(outcome.observation)
                messages.append(
                    ToolMessage(
                        content=_observation_payload(outcome),
                        tool_call_id=call_id or name,
                    )
                )
        return AgentResult(
            answer=last_text,
            entered_loop=True,
            loaded_tools=loaded_names,
            audits=middleware.audits,
            observations=list(observations),
            messages=list(messages),
        )

    async def _direct_answer(
        self,
        turn: AgentTurn,
        *,
        fastpath_name: str,
        stream: StreamSink | None = None,
    ) -> AgentResult:
        assert self._llm is not None
        messages = _assemble_messages(
            system_prompt=load_prompt("system_base.md", "scene_direct.md"),
            turn=turn,
            history_turns=self._session_history_turns,
        )
        response = await _complete_from_model(self._llm, messages, stream=stream, emit_tokens=True)
        return AgentResult(
            answer=_message_text(response),
            entered_loop=False,
            fastpath_name=fastpath_name,
            messages=list(messages) + [response],
        )


def load_prompt(*filenames: str) -> str:
    """从 ``prompts/`` 加载并拼接；文件缺失即失败，禁止内联兜底。"""
    chunks: list[str] = []
    for name in filenames:
        path = _PROMPTS_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"系统提示文件缺失：{path}")
        chunks.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(chunks)


def _assemble_messages(*, system_prompt: str, turn: AgentTurn, history_turns: int) -> list[Any]:
    messages: list[Any] = [SystemMessage(content=system_prompt)]
    if turn.memory_degraded:
        messages.append(SystemMessage(content="长期记忆暂不可用（memory_degraded），不得编造用户目标。"))
    elif turn.memory_records:
        lines = [record.content for record in turn.memory_records if getattr(record, "content", None)]
        if lines:
            body = "\n".join(f"- {line}" for line in lines)
            messages.append(SystemMessage(content=f"长期记忆（L3）：\n{body}"))
    history = list(turn.history)[-(history_turns * 2) :]
    for item in history:
        role = str(item.get("role", "user"))
        content = str(item.get("content", ""))
        if role == "assistant":
            messages.append(AIMessage(content=content))
        else:
            messages.append(HumanMessage(content=content))
    messages.append(HumanMessage(content=turn.message))
    return messages


def _top_k(arguments: dict[str, Any]) -> int:
    raw = arguments.get("top_k", DEFAULT_TOP_K)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_TOP_K
    return max(1, min(value, 8))


def _tool_spec(card: ToolCard) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": card.name,
            "description": card.description,
            "parameters": card.parameters,
        },
    }


def _tool_calls_of(message: Any) -> list[tuple[str, str, dict[str, Any]]]:
    raw_calls = getattr(message, "tool_calls", None) or []
    parsed: list[tuple[str, str, dict[str, Any]]] = []
    for call in raw_calls:
        if isinstance(call, dict):
            name = str(call.get("name") or "")
            call_id = str(call.get("id") or "")
            arguments: Any = call.get("args") if call.get("args") is not None else call.get("arguments") or {}
        else:
            name = str(getattr(call, "name", "") or "")
            call_id = str(getattr(call, "id", "") or "")
            arguments = getattr(call, "args", {}) or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        if name:
            parsed.append((call_id, name, arguments))
    return parsed


def _message_text(message: Any) -> str:
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


def _observation_payload(outcome: Any) -> str:
    if outcome.observation is not None:
        obs = outcome.observation
        provenance = obs.provenance[0] if obs.provenance else None
        payload = {
            "data": obs.data,
            "source": provenance.source if provenance else None,
            "data_time": provenance.retrieved_at if provenance else None,
            "quality_flags": obs.data_quality.model_dump(),
            "status": obs.status,
            "error_code": obs.error_code,
            "result_type": obs.result_type,
            "payload": obs.payload,
        }
    else:
        payload = {"data": None, "status": "REJECTED"}
    if outcome.rejection is not None:
        payload["rejected"] = True
        payload["audit_code"] = outcome.rejection.audit_code
        payload["reason"] = (outcome.rejection.reasons or [""])[0]
    return json.dumps(payload, ensure_ascii=False, default=str)


def _has_tool_signal(message: Any) -> bool:
    if _tool_calls_of(message):
        return True
    return bool(getattr(message, "tool_call_chunks", None))


def _emit_tool_step(
    stream: StreamSink | None,
    *,
    tool: str,
    arguments: dict[str, Any],
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    if stream is None or not hasattr(stream, "on_tool_step"):
        return
    payload: dict[str, Any] = {"tool": tool, "arguments": arguments, "status": status}
    if extra:
        payload.update(extra)
    stream.on_tool_step(payload)


def _emit_tool_outcome(stream: StreamSink | None, *, name: str, arguments: dict[str, Any], outcome: Any) -> None:
    extra: dict[str, Any] = {}
    audit = getattr(outcome, "audit", None)
    if audit is not None:
        extra["elapsedMs"] = getattr(audit, "elapsed_ms", None)
        extra["auditCode"] = getattr(audit, "audit_code", None)
    if getattr(outcome, "rejection", None) is not None:
        status = "rejected"
    elif getattr(outcome, "allowed", False):
        status = "success"
    else:
        status = "failed"
    observation = getattr(outcome, "observation", None)
    data = getattr(observation, "data", None) if observation is not None else None
    if name == SEARCH_TOOLS_NAME and isinstance(data, dict):
        extra["query"] = data.get("query")
        extra["hitCount"] = data.get("count")
    _emit_tool_step(stream, tool=name, arguments=arguments, status=status, extra=extra)


async def _complete_from_model(
    model: Any,
    messages: Sequence[Any],
    *,
    stream: StreamSink | None,
    emit_tokens: bool,
) -> Any:
    """优先 ``astream``；无流式面时回退 ``ainvoke``。工具轮不向客户端推 token。"""

    astream = getattr(model, "astream", None)
    if not callable(astream):
        result = await model.ainvoke(messages)
        if emit_tokens and not _has_tool_signal(result):
            _emit_token(stream, _message_text(result))
        return result
    pieces: list[Any] = []
    saw_tools = False
    async for chunk in astream(messages):
        pieces.append(chunk)
        if _has_tool_signal(chunk):
            saw_tools = True
        text = _message_text(chunk)
        if emit_tokens and text and not saw_tools:
            _emit_token(stream, text)
    if not pieces:
        return AIMessage(content="")
    merged = pieces[0]
    for item in pieces[1:]:
        try:
            merged = merged + item
        except TypeError:
            merged = item
    return merged


def _emit_token(stream: StreamSink | None, content: str) -> None:
    text = str(content or "")
    if not text or stream is None or not hasattr(stream, "on_token"):
        return
    stream.on_token(text)

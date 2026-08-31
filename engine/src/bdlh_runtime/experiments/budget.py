"""作业级费用硬限额(修复方案 §11.2)。

只统计**已测量**的真实量:压缩/摘要构建的真实模型请求(来自 SummaryUsage
口径,缓存命中不计)与 Agent 运行的实际步数(每步至多一次逻辑模型调用)。
不使用估算值冒充真实消耗。

超过任一限额后:停止发起新的运行单元,已完成工件与结果保留,
任务以明确的预算终止状态收尾(PARTIAL/FAILED + BUDGET_EXCEEDED 原因)。

环境变量(0 或未设置 = 不限制该项):
- ``MAX_LLM_REQUESTS_PER_JOB``
- ``MAX_INPUT_TOKENS_PER_JOB``
- ``MAX_ESTIMATED_COST_PER_JOB``
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


def _env_int(name: str) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _env_float(name: str) -> float:
    raw = (os.getenv(name) or "").strip()
    try:
        value = float(raw)
        return value if value > 0 else 0.0
    except ValueError:
        return 0.0


@dataclass
class JobBudget:
    """一个任务(作业/批次)的已测量用量累计与限额判定。"""

    max_llm_requests: int = 0
    max_input_tokens: int = 0
    max_estimated_cost: float = 0.0
    llm_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    #: 首个被突破的限额说明;空串 = 未超限
    terminated_reason: str = field(default="")

    @classmethod
    def from_env(cls) -> JobBudget:
        return cls(
            max_llm_requests=_env_int("MAX_LLM_REQUESTS_PER_JOB"),
            max_input_tokens=_env_int("MAX_INPUT_TOKENS_PER_JOB"),
            max_estimated_cost=_env_float("MAX_ESTIMATED_COST_PER_JOB"),
        )

    def record(
        self,
        *,
        llm_requests: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost: float = 0.0,
    ) -> None:
        self.llm_requests += int(llm_requests)
        self.input_tokens += int(input_tokens)
        self.output_tokens += int(output_tokens)
        self.cost += float(cost)
        if not self.terminated_reason:
            self.terminated_reason = self.exceeded_reason()

    def exceeded_reason(self) -> str:
        if self.max_llm_requests and self.llm_requests > self.max_llm_requests:
            return (
                f"BUDGET_EXCEEDED: LLM 请求数 {self.llm_requests} 超过作业上限 "
                f"{self.max_llm_requests}(MAX_LLM_REQUESTS_PER_JOB)"
            )
        if self.max_input_tokens and self.input_tokens > self.max_input_tokens:
            return (
                f"BUDGET_EXCEEDED: 输入 Token {self.input_tokens} 超过作业上限 "
                f"{self.max_input_tokens}(MAX_INPUT_TOKENS_PER_JOB)"
            )
        if self.max_estimated_cost and self.cost > self.max_estimated_cost:
            return (
                f"BUDGET_EXCEEDED: 估算费用 {self.cost:.4f} 超过作业上限 "
                f"{self.max_estimated_cost}(MAX_ESTIMATED_COST_PER_JOB)"
            )
        return ""

    @property
    def exhausted(self) -> bool:
        return bool(self.terminated_reason)

    def to_payload(self) -> dict[str, Any]:
        return {
            "llm_requests": self.llm_requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost": round(self.cost, 6),
            "limits": {
                "max_llm_requests": self.max_llm_requests or None,
                "max_input_tokens": self.max_input_tokens or None,
                "max_estimated_cost": self.max_estimated_cost or None,
            },
            "terminated_reason": self.terminated_reason or None,
        }

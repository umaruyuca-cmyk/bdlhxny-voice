"""将外部 Adapter 结果转换为统一 Observation，含服务端吞错识别。

核心职责（架构文档 v3.1 §7.3 约束 5）：
cn-financial 的部分工具（get_money_flow、get_market_overview）会把数据源
失败包成正常响应 {"error": true, "message": "...RemoteDisconnected..."}，
此时 MCP 协议层 isError=false。如果不解析响应体，这种失败会被当成成功
喂给分析能力——本 Normalizer 负责识别并纠正。

识别规则：Observation.data.raw_text 解析为 JSON 后，若含 error=true，
将 Observation.status 降级为 FAILED、data_quality 标记 INVALID。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from stockwise_analysis.contracts.observation import DataQuality, Observation

logger = logging.getLogger("stockwise_analysis.observations.normalizer")


class ObservationNormalizer:
    """标准化入口；禁止将 MCP 原始 JSON 直接传给分析能力。

    当前实现聚焦"服务端吞错识别"。后续可扩展字段映射、脱敏、单位统一
    （如 akshare-one 的元 → cn-financial 的亿元）等标准化逻辑。
    """

    def normalize(self, observation: Observation) -> Observation:
        """标准化单个 Observation。

        步骤：
        1. 检测服务端吞错（error:true 响应）→ 降级为 FAILED；
        2. （后续）字段映射和单位统一；
        3. 返回标准化后的 Observation（不修改原始对象）。
        """
        if observation.status != "SUCCESS":
            return observation

        data = observation.data
        if not isinstance(data, dict):
            return observation

        # ── 服务端吞错识别 ──
        # cn-financial 的失败响应：{"error": true, "message": "..."}
        # 藏在 data.raw_text 里（adapter 把原始文本放进 raw_text）
        raw_text = data.get("raw_text", "")
        swallowed_error = self._detect_swallowed_error(raw_text)
        if swallowed_error is not None:
            logger.warning(
                "检测到服务端吞错 (capability=%s): %s",
                observation.capability,
                swallowed_error[:120],
            )
            return Observation(
                observation_id=observation.observation_id,
                capability=observation.capability,
                status="FAILED",
                data=None,
                data_quality=DataQuality(quality_status="INVALID"),
                provenance=observation.provenance,
                error_code="SWALLOWED_ERROR",
                error_message=f"服务端将数据源失败包成正常响应: {swallowed_error[:300]}",
            )

        return observation

    def normalize_many(self, observations: list[Observation]) -> list[Observation]:
        """批量标准化。"""
        return [self.normalize(obs) for obs in observations]

    def _detect_swallowed_error(self, raw_text: str) -> str | None:
        """检测响应文本中是否藏有 error:true 的服务端吞错。

        返回错误消息（有错）或 None（无错）。处理两种形态：
        1. 直接 JSON：{"error": true, "message": "..."}
        2. JSON 数组首元素含 error（部分工具返回 [{error:true,...}]）

        解析失败时返回 None（可能只是非 JSON 的正常文本响应）。
        """
        if not raw_text:
            return None

        try:
            parsed: Any = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError):
            return None

        # 形态 1：对象含 error:true
        if isinstance(parsed, dict) and parsed.get("error") is True:
            return str(parsed.get("message", parsed.get("msg", "未知错误")))

        # 形态 2：数组首元素含 error:true
        if isinstance(parsed, list) and parsed:
            first = parsed[0]
            if isinstance(first, dict) and first.get("error") is True:
                return str(first.get("message", first.get("msg", "未知错误")))

        return None

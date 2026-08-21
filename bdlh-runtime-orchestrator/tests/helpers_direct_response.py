"""Tests-only direct-response stub — not a product path."""

from __future__ import annotations


class DeterministicDirectResponseModel:
    """无模型环境的可测试确定性回答。"""

    _ANSWERS = {
        "市盈率": "市盈率（PE）是股票价格与每股收益的比值，常用于衡量市场为企业盈利支付的估值倍数。比较时应结合行业、盈利稳定性和增长预期，不能只看数值高低。",
        "pe": "市盈率（PE）是股票价格与每股收益的比值，常用于衡量市场为企业盈利支付的估值倍数。比较时应结合行业、盈利稳定性和增长预期，不能只看数值高低。",
        "市净率": "市净率（PB）是股票价格与每股净资产的比值，常用于观察市场相对账面净资产给出的估值。它更适合与同行业公司及企业自身历史区间比较。",
        "pb": "市净率（PB）是股票价格与每股净资产的比值，常用于观察市场相对账面净资产给出的估值。它更适合与同行业公司及企业自身历史区间比较。",
    }

    def answer(self, message: str) -> str:
        normalized = message.strip().lower()
        for keyword, answer in self._ANSWERS.items():
            if keyword in normalized:
                return answer
        return f"关于“{message.strip()}”：当前为测试替身回答。"

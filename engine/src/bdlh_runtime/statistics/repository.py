"""运行记录读取(P0-7):统计的唯一输入是已落库/落盘的运行明细。

第一版数据源:所有者批次报告(数据服务 report 列 → 本地工件兜底,
由调用方注入完整 report)。匿名任务(var/jobs)与压缩矩阵结果形状
不同,后续再接适配器。本模块不发起任何网络调用,不调用 LLM。
"""

from __future__ import annotations

from typing import Any


def runs_from_report(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从批次报告 payload 提取运行明细;形状不符时返回空(不抛错)。"""
    if not isinstance(report, dict):
        return []
    runs = report.get("runs")
    if not isinstance(runs, list):
        return []
    return [row for row in runs if isinstance(row, dict)]


def report_meta(report: dict[str, Any] | None) -> dict[str, Any]:
    """实验定义元数据:模板标识、冻结条件哈希与正式样本门槛。"""
    if not isinstance(report, dict):
        return {}
    version = report.get("template_version")
    fixed_conditions = report.get("fixed_conditions")
    formal_min = fixed_conditions.get("formal_min_repeat_count") if isinstance(fixed_conditions, dict) else None
    return {
        "template_id": str(report.get("template_id") or ""),
        "template_version": int(version) if isinstance(version, int) else None,
        "fixed_conditions_hash": str(report.get("fixed_conditions_hash") or ""),
        "formal_min_repeat_count": int(formal_min) if isinstance(formal_min, int) else None,
        "budget_terminated": report.get("budget_terminated"),
    }

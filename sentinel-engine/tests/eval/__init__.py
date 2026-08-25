"""eval 题库包（设计文档 §11.2）。"""

from .routing_cases import (
    BASELINE_TASK_SUCCESS,
    CATEGORIES,
    MIN_CASES_PER_CATEGORY,
    MIN_TOTAL_CASES,
    ROUTING_CASES,
    EvalCase,
    cases_by_category,
)

__all__ = [
    "BASELINE_TASK_SUCCESS",
    "CATEGORIES",
    "EvalCase",
    "MIN_CASES_PER_CATEGORY",
    "MIN_TOTAL_CASES",
    "ROUTING_CASES",
    "cases_by_category",
]

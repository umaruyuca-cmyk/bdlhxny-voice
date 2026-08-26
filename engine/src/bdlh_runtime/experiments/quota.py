"""匿名测试的限额配置(服务端真源,前端只负责显示)。

限额值全部来自环境变量,不写死在前端;超限时返回明确的错误与下次可用时间。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class PublicQuotaConfig:
    """匿名运行限额快照(随任务保存为 quota_snapshot)。"""

    max_concurrent_jobs_per_anonymous: int = 1
    daily_jobs_per_anonymous: int = 10
    comparison_daily_jobs: int = 10
    compression_context_daily_jobs: int = 5
    queue_timeout_s: int = 120
    max_job_duration_s: int = 900
    #: 4×1 原生矩阵一次运行 4 格,时长上限单独配置
    matrix_max_job_duration_s: int = 300
    max_agent_steps: int = 8
    repeat_options: tuple[int, ...] = (3, 5)

    @classmethod
    def from_env(cls) -> PublicQuotaConfig:
        def _int(name: str, default: int) -> int:
            raw = (os.getenv(name) or "").strip()
            return int(raw) if raw.isdigit() and int(raw) > 0 else default

        from bdlh_runtime.experiments import COMPARISON_REPEAT_COUNTS, default_max_agent_steps

        return cls(
            max_concurrent_jobs_per_anonymous=_int("PUBLIC_MAX_CONCURRENT_JOBS_PER_ANON", 1),
            daily_jobs_per_anonymous=_int("PUBLIC_DAILY_JOBS_PER_ANON", 10),
            comparison_daily_jobs=_int("PUBLIC_COMPARISON_DAILY_JOBS", 10),
            compression_context_daily_jobs=_int("PUBLIC_COMPRESSION_CONTEXT_DAILY_JOBS", 5),
            queue_timeout_s=_int("PUBLIC_QUEUE_TIMEOUT_S", 120),
            max_job_duration_s=_int("PUBLIC_MAX_JOB_DURATION_S", 900),
            matrix_max_job_duration_s=_int("PUBLIC_MATRIX_MAX_JOB_DURATION_S", 300),
            max_agent_steps=default_max_agent_steps(),
            repeat_options=COMPARISON_REPEAT_COUNTS,
        )

    def as_dict(self) -> dict[str, int | list[int]]:
        return {
            "max_concurrent_jobs_per_anonymous": self.max_concurrent_jobs_per_anonymous,
            "daily_jobs_per_anonymous": self.daily_jobs_per_anonymous,
            "comparison_daily_jobs": self.comparison_daily_jobs,
            "compression_context_daily_jobs": self.compression_context_daily_jobs,
            "queue_timeout_s": self.queue_timeout_s,
            "max_job_duration_s": self.max_job_duration_s,
            "matrix_max_job_duration_s": self.matrix_max_job_duration_s,
            "max_agent_steps": self.max_agent_steps,
            "repeat_options": list(self.repeat_options),
        }

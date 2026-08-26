"""写操作确认(混合路线阶段 B4)。

G1-G7 原实现把「非只读工具统一拒绝」当成了确认机制的替身;本模块补充
真正的写操作确认:

- 确认记录包含 ``confirmation_id / run_id / tool_name / arguments_hash /
  actor / expires_at / status``;
- 确认必须与本次运行、具体工具和规范化参数绑定,不能复用于其他调用
  (单次消费,用后即 ``USED``);
- 缺少确认 → ``CONFIRMATION_REQUIRED``;无效/过期/参数变化/运行或工具
  不匹配/重复使用 → 各自独立审计码;
- 有效确认只允许对应的 Mock 写调用继续——实验执行器全部为 Mock/冻结
  执行器,不发送邮件、不写外部文件、不修改第三方系统(结构保证)。

数据库需要确认记录时,只交付增量 SQL(见 db/postgresql/changes),不执行。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

#: 写操作确认的独立审计码(与 G2 只读规则 READ_ONLY_REQUIRED 分开记录)
AUDIT_CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
AUDIT_CONFIRMATION_INVALID = "CONFIRMATION_INVALID"
AUDIT_CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
AUDIT_CONFIRMATION_ARGUMENTS_MISMATCH = "CONFIRMATION_ARGUMENTS_MISMATCH"
AUDIT_CONFIRMATION_RUN_MISMATCH = "CONFIRMATION_RUN_MISMATCH"
AUDIT_CONFIRMATION_TOOL_MISMATCH = "CONFIRMATION_TOOL_MISMATCH"
AUDIT_CONFIRMATION_ALREADY_USED = "CONFIRMATION_ALREADY_USED"

#: 确认状态机:GRANTED → USED(单次消费);EXPIRED 只在校验时推导
CONFIRMATION_STATUS_GRANTED = "GRANTED"
CONFIRMATION_STATUS_USED = "USED"

DEFAULT_CONFIRMATION_TTL_SECONDS = 600


def hash_arguments(arguments: Mapping[str, Any]) -> str:
    """规范化参数哈希:键排序 + 紧凑 JSON + SHA-256;参数变化即失效。"""
    canonical = json.dumps(
        dict(arguments or {}), sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ConfirmationRecord:
    """一次写操作确认;与 run/tool/参数三元组绑定,单次消费。"""

    confirmation_id: str
    run_id: str
    tool_name: str
    arguments_hash: str
    actor: str
    expires_at: str  # ISO-8601 UTC
    status: str = CONFIRMATION_STATUS_GRANTED

    def expired_at_now(self, *, now: datetime | None = None) -> bool:
        moment = now or datetime.now(UTC)
        return moment >= datetime.fromisoformat(self.expires_at)

    def to_payload(self) -> dict[str, Any]:
        """公开/工件形态(不含内部索引)。"""
        return {
            "confirmation_id": self.confirmation_id,
            "run_id": self.run_id,
            "tool_name": self.tool_name,
            "arguments_hash": self.arguments_hash,
            "actor": self.actor,
            "expires_at": self.expires_at,
            "status": self.status,
        }


def build_confirmation_upsert(record: ConfirmationRecord, *, consumed_at: str | None = None) -> dict[str, Any]:
    """写确认持久化载荷(write_confirmations 表列名对齐;只构建,不执行 SQL)。

    ``consumed_at`` 仅在 status=USED 时给出;维护者按
    db/postgresql/changes/20260826-write-confirmations.sql 手动落库。
    """
    return {
        "id": record.confirmation_id,
        "run_id": record.run_id,
        "tool_name": record.tool_name,
        "arguments_hash": record.arguments_hash,
        "actor": record.actor,
        "expires_at": record.expires_at,
        "status": record.status,
        "consumed_at": consumed_at if record.status == CONFIRMATION_STATUS_USED else None,
    }


@dataclass
class ConfirmationStore:
    """确认记录的内存仓储(测试与实验);生产持久化由增量 SQL 承载,不执行。"""

    ttl_seconds: int = DEFAULT_CONFIRMATION_TTL_SECONDS
    _records: dict[str, ConfirmationRecord] = field(default_factory=dict)

    def create(
        self,
        *,
        run_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        actor: str,
    ) -> ConfirmationRecord:
        """为「本次运行 + 具体工具 + 规范化参数」创建一条已授予的确认。"""
        record = ConfirmationRecord(
            confirmation_id=f"cfm-{uuid4().hex[:12]}",
            run_id=run_id,
            tool_name=tool_name,
            arguments_hash=hash_arguments(arguments),
            actor=actor,
            expires_at=(datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)).isoformat(),
            status=CONFIRMATION_STATUS_GRANTED,
        )
        self._records[record.confirmation_id] = record
        return record

    def retrieve(self, confirmation_id: str) -> ConfirmationRecord | None:
        """按 id 从权威存储读取确认;不存在即视为无效(闭环校验的入口)。"""
        return self._records.get(confirmation_id)

    def validate(
        self,
        record: ConfirmationRecord,
        *,
        run_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> tuple[str, str]:
        """校验绑定关系;返回 (audit_code, reason)。空 code 表示有效。

        传入的记录必须同时存在于本权威存储(retrieve 命中且为同一条),
        仅字段自洽的外部对象不构成有效确认。
        """
        stored = self._records.get(record.confirmation_id)
        if stored is None or stored != record:
            return AUDIT_CONFIRMATION_INVALID, "确认不在权威存储中或与存储记录不一致"
        if record.status == CONFIRMATION_STATUS_USED:
            return AUDIT_CONFIRMATION_ALREADY_USED, "确认已被消费,不能复用于其他调用"
        if record.expired_at_now():
            return AUDIT_CONFIRMATION_EXPIRED, "确认已过期"
        if record.run_id != run_id:
            return AUDIT_CONFIRMATION_RUN_MISMATCH, f"确认绑定运行 {record.run_id},本次运行为 {run_id}"
        if record.tool_name != tool_name:
            return AUDIT_CONFIRMATION_TOOL_MISMATCH, f"确认绑定工具 {record.tool_name},本次调用 {tool_name}"
        if record.arguments_hash != hash_arguments(arguments):
            return AUDIT_CONFIRMATION_ARGUMENTS_MISMATCH, "参数已变化,旧确认失效"
        return "", ""

    def consume(self, record: ConfirmationRecord) -> ConfirmationRecord:
        """单次消费:标记 USED;再次使用按 ALREADY_USED 拒绝。"""
        used = ConfirmationRecord(**{**record.__dict__, "status": CONFIRMATION_STATUS_USED})
        self._records[used.confirmation_id] = used
        return used


#: 确认提供方:同步或 async 均可;签名 (run_id, tool_name, arguments) -> ConfirmationRecord | None。
#: 返回的记录必须来自(或已写入)中间件持有的权威 ConfirmationStore,
#: 否则按 CONFIRMATION_INVALID 拒绝——仅字段自洽的对象不构成有效确认。
ConfirmationProvider = Callable[[str, str, Mapping[str, Any]], Any]


@dataclass
class AutoGrantConfirmationProvider:
    """自动授予提供方:为「本运行内、目标工具、参数完全一致」的调用发确认。

    只用于治理实验中显式声明「写操作会被批准」的探针用例;实验执行器
    全部为 Mock,不产生外部副作用。
    """

    store: ConfirmationStore = field(default_factory=ConfirmationStore)
    actor: str = "experiment-harness"
    #: 每个确认只允许消费一次;参数变化自动失效(创建时重新绑定)
    max_grants_per_binding: int = 1
    _grant_counts: dict[tuple[str, str, str], int] = field(default_factory=dict)

    def __call__(self, run_id: str, tool_name: str, arguments: Mapping[str, Any]) -> ConfirmationRecord | None:
        key = (run_id, tool_name, hash_arguments(arguments))
        used = self._grant_counts.get(key, 0)
        if used >= self.max_grants_per_binding:
            return None  # 同一绑定的第二次调用不再授予 → CONFIRMATION_REQUIRED
        self._grant_counts[key] = used + 1
        return self.store.create(run_id=run_id, tool_name=tool_name, arguments=arguments, actor=self.actor)


@dataclass
class DenyAllConfirmationProvider:
    """拒绝全部确认(用户未批准路径):恒返回 None → CONFIRMATION_REQUIRED。"""

    def __call__(self, run_id: str, tool_name: str, arguments: Mapping[str, Any]) -> ConfirmationRecord | None:
        return None


__all__ = [
    "AUDIT_CONFIRMATION_ALREADY_USED",
    "AUDIT_CONFIRMATION_ARGUMENTS_MISMATCH",
    "AUDIT_CONFIRMATION_EXPIRED",
    "AUDIT_CONFIRMATION_INVALID",
    "AUDIT_CONFIRMATION_REQUIRED",
    "AUDIT_CONFIRMATION_RUN_MISMATCH",
    "AUDIT_CONFIRMATION_TOOL_MISMATCH",
    "AutoGrantConfirmationProvider",
    "CONFIRMATION_STATUS_GRANTED",
    "CONFIRMATION_STATUS_USED",
    "ConfirmationProvider",
    "ConfirmationRecord",
    "ConfirmationStore",
    "DEFAULT_CONFIRMATION_TTL_SECONDS",
    "DenyAllConfirmationProvider",
    "build_confirmation_upsert",
    "hash_arguments",
]

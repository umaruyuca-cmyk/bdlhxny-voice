"""运行控制面：用户 Pause 协作式停止（ADR-014）。"""

from __future__ import annotations

from threading import RLock


class RunControlPlane:
    """进程内 pause 请求表；多实例下后续可换共享存储，契约不变。"""

    def __init__(self) -> None:
        self._pause_requested: dict[str, bool] = {}
        self._lock = RLock()

    def request_pause(self, run_id: str) -> None:
        key = str(run_id or "").strip()
        if not key:
            raise ValueError("run_id is required")
        with self._lock:
            self._pause_requested[key] = True

    def is_pause_requested(self, run_id: str) -> bool:
        key = str(run_id or "").strip()
        if not key:
            return False
        with self._lock:
            return bool(self._pause_requested.get(key))

    def clear(self, run_id: str) -> None:
        key = str(run_id or "").strip()
        if not key:
            return
        with self._lock:
            self._pause_requested.pop(key, None)

"""API 层共享上下文：把装配好的应用依赖递给各 router（重构方案 D1/P3）。

此前这些依赖以闭包形式寄生在 ``create_api_app`` 内（1188 行 god file 的
根因）；拆分后各 router 从 ``ApiContext`` 显式获取，``routes.py`` 只保留
应用工厂装配。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from bdlh_runtime.runtime.run_state import RunStateStore

from .auth import AuthenticationError, JwtAuthenticator


class ApiContext:
    """router 共享依赖与鉴权/读取辅助；只做转发与隔离，不含业务编排。"""

    def __init__(
        self,
        *,
        application: Any,
        store: RunStateStore,
        chat_sessions: Any,
        authenticator: JwtAuthenticator,
    ) -> None:
        self.application = application
        self.store = store
        self.chat_sessions = chat_sessions
        self.authenticator = authenticator

    def request_user_id(self, authorization: str | None, claimed_user_id: str | None = None) -> str | None:
        """返回 JWT 中的可信 user_id；开发模式才允许无 Token 的显式 user_id。"""

        try:
            authenticated_user_id = self.authenticator.authenticate(authorization)
        except AuthenticationError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        normalized_claim = str(claimed_user_id).strip() if claimed_user_id is not None else None
        if authenticated_user_id is not None and normalized_claim not in {None, authenticated_user_id}:
            raise HTTPException(status_code=403, detail="请求 user_id 与登录用户不一致")
        return authenticated_user_id or normalized_claim

    def authenticated_task_user(self, authorization: str | None) -> str:
        user_id = self.request_user_id(authorization)
        if user_id is None:
            raise HTTPException(status_code=401, detail="持续任务需要已认证用户")
        return user_id

    def authorize_run(self, run_id: str, requester_user_id: str | None, state: dict[str, Any]) -> None:
        """阻止用户读取或恢复其他用户的运行。"""

        application = self.application
        location = (
            application.run_registry.get(run_id, requester_user_id) if application.run_registry is not None else None
        )
        owner_user_id = location.user_id if location is not None else state.get("user_id")
        if requester_user_id is not None and owner_user_id is not None:
            if str(requester_user_id) != str(owner_user_id):
                raise HTTPException(status_code=403, detail="无权访问该运行")
        elif application.settings.auth_required and owner_user_id is None:
            raise HTTPException(status_code=403, detail="运行缺少用户归属，禁止访问")

    async def load_run_state(self, run_id: str, requester_user_id: str | None) -> dict[str, Any] | None:
        """从 RunRegistry + RunStateReader 读取 Cognitive 运行状态（P2a：默认内存实现）。"""

        location = self.application.run_registry.get(run_id) if self.application.run_registry is not None else None
        if location is not None and requester_user_id is not None and str(location.user_id) != str(requester_user_id):
            raise HTTPException(status_code=403, detail="无权访问该运行")
        return self.store.load(run_id, requester_user_id)

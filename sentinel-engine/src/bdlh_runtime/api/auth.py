"""FastAPI 用户 JWT 校验。

JWT 由 Java 用户系统签发，Python 只验证签名和 subject，并把 subject 作为可信
user_id 注入 LangGraph。原始 Token 不写入 State、Checkpointer、事件或日志。

未携带 Token 时返回 ``None``（游客）；对话入口再归一为 ``GUEST_USER_ID``。
``required=True`` 只表示服务端应配置 ``JWT_SECRET`` 以便登录用户可校验，
不再在缺 Token 时拦截对话。登录专属能力请用 ``authenticated_task_user``。
"""

from __future__ import annotations

from dataclasses import dataclass

import jwt


class AuthenticationError(ValueError):
    """用户身份凭证缺失或无效。"""


@dataclass(frozen=True)
class JwtAuthenticator:
    secret: str | None
    required: bool = False

    def authenticate(self, authorization: str | None) -> str | None:
        if not authorization:
            # 游客：缺 Token 不拦截；登录专属路由自行要求身份。
            return None
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            raise AuthenticationError("Authorization 必须使用 Bearer Token")
        if not self.secret:
            raise AuthenticationError("服务端未配置 JWT_SECRET")
        try:
            claims = jwt.decode(token.strip(), self.secret, algorithms=["HS256"])
            subject = str(claims.get("sub", "")).strip()
            if not subject or not subject.isdigit() or int(subject) <= 0:
                raise AuthenticationError("Token 缺少有效用户标识")
            return subject
        except AuthenticationError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthenticationError("Token 无效或已过期") from exc

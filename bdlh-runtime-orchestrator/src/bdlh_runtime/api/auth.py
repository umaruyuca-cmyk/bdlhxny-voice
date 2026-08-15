"""FastAPI 用户 JWT 校验。

JWT 由 Java 用户系统签发，Python 只验证签名和 subject，并把 subject 作为可信
user_id 注入 LangGraph。原始 Token 不写入 State、Checkpointer、事件或日志。
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
            if self.required:
                raise AuthenticationError("请先登录")
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
            raise AuthenticationError("登录状态无效或已过期") from exc

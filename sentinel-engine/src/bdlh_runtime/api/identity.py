"""会话身份：登录用户用 JWT sub；未登录固定为游客。

游客可以走对话主路径（chat / agent-runs），但金融资料确认、持续任务、
通知等登录专属能力仍须 ``authenticated_task_user`` / 前端登录门禁。
"""

from __future__ import annotations

#: 与 JWT 约定一致：合法登录 subject 必须为正整数；0 专留给游客。
GUEST_USER_ID = "0"


def effective_user_id(user_id: str | None) -> str:
    """把可选鉴权结果归一成可写入 State / Data Plane 的稳定 user_id。"""
    if user_id is None:
        return GUEST_USER_ID
    text = str(user_id).strip()
    return text if text else GUEST_USER_ID

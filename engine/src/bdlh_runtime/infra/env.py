"""deploy/.env 加载器:统一配置入口。

所有需要 LLM 配置的 CLI(``session_cross_eval`` / ``context_eval`` /
``ab_eval``)在 main() 入口调用 ``load_deploy_env()``,把 ``deploy/.env``
中的键注入进程环境;已存在的环境变量优先,不覆盖。

查找顺序:
1. 显式传入的 path;
2. 环境变量 ``DEPLOY_ENV_FILE`` 指定的文件;
3. 仓库根目录 ``deploy/.env``(按本文件位置向上推导)。

只做 KEY=VALUE 行解析(支持行内注释剥离与成对引号去除),不引入额外依赖;
值中含 ``#`` 时不剥离(避免截断密钥/令牌)。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 仓库根 = engine/src/bdlh_runtime/infra/env.py 向上 4 级(engine → src → bdlh_runtime → infra)
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _parse_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_deploy_env(path: str | Path | None = None) -> dict[str, str]:
    """把 deploy/.env 的键注入 ``os.environ``(不覆盖已有),返回注入的键值。"""

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    elif os.getenv("DEPLOY_ENV_FILE"):
        candidates.append(Path(os.environ["DEPLOY_ENV_FILE"]))
    else:
        candidates.append(_REPO_ROOT / "deploy" / ".env")
        candidates.append(Path.cwd() / "deploy" / ".env")

    env_file = next((item for item in candidates if item.is_file()), None)
    if env_file is None:
        return {}

    loaded: dict[str, str] = {}
    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw_value = stripped.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = _parse_value(raw_value)
        if key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded

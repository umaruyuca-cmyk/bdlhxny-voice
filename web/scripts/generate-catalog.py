#!/usr/bin/env python
"""经 data 服务 API 生成工具目录与用例库的静态 JSON(公开站零后端)。

架构约定:所有数据访问经 data 服务 internal 接口,不直连数据库。
前置条件:data 服务运行中(默认 127.0.0.1:18081),deploy/.env 有 DATA_INTERNAL_TOKEN。
用法:python scripts/generate-catalog.py
"""
import json
import os
import sys
import urllib.request

# ── 配置(从 deploy/.env 读取,不硬编码) ──
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_env_path = os.path.join(_repo_root, "deploy", ".env")

def _load_env(path):
    env = {}
    if not os.path.isfile(path):
        return env
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env

_env = _load_env(_env_path)
DATA_BASE = os.environ.get("DATA_API_BASE_URL", "http://127.0.0.1:18081/internal/v1")
DATA_TOKEN = os.environ.get("DATA_INTERNAL_TOKEN", _env.get("DATA_INTERNAL_TOKEN", ""))
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "showcase-data")

def _get(path):
    """调 data 服务 internal 接口(令牌必填,fail-fast)。"""
    if not DATA_TOKEN:
        print("错误: DATA_INTERNAL_TOKEN 未配置(检查 deploy/.env 或环境变量)", file=sys.stderr)
        sys.exit(1)
    req = urllib.request.Request(
        DATA_BASE + path,
        headers={"X-Internal-Token": DATA_TOKEN, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"错误: data 服务返回 HTTP {e.code}: {e.read()[:200]}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"错误: 无法连接 data 服务({DATA_BASE}): {e.reason}", file=sys.stderr)
        print("请先启动 data 服务: 详见 deploy/本地启动说明.md", file=sys.stderr)
        sys.exit(1)

def gen_tools():
    """从 data 服务 /tool-catalog 拉取全部工具,投影为前端 JSON。"""
    catalog = _get("/tool-catalog")
    tools = []
    for cap in catalog.get("capabilities") or []:
        tools.append({
            "name": cap.get("name"),
            "description": cap.get("description"),
            "domain": cap.get("domain"),
            "adapter": cap.get("adapter"),
            "read_only": cap.get("read_only"),
            "requires_auth": cap.get("requires_authenticated_user"),
            "required_arguments": cap.get("required_arguments") or [],
            "depends_on": cap.get("depends_on") or [],
            "timeout_seconds": cap.get("timeout_seconds"),
            "side_effect": cap.get("side_effect"),
            "requires_confirmation": cap.get("requires_confirmation"),
            "risk_level": cap.get("risk_level"),
            "enabled": cap.get("enabled"),
            "toolsets": cap.get("toolsets") or [],
            "operations": cap.get("operations") or [],
        })
    tools.sort(key=lambda t: (t["domain"] or "", t["name"] or ""))
    path = os.path.join(OUT, "tools.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"tools": tools, "total": len(tools)}, f, ensure_ascii=False, indent=2)
    print(f"tools.json: {len(tools)} tools ← data 服务 /tool-catalog")

def gen_cases():
    """从 data 服务 /cases 拉取用例,投影为公开 JSON。

    投影规则(两类用例口径):只发布新口径对比用例的公开字段——
    判定标志是 expected_checks 内显式的 test_type=COMPARISON_CASE
    (data 服务视图不透出 case_definitions.test_type 列;因历史运行
    外键而被 SQL 保留的旧用例没有该字段,自然被过滤);
    评判配置(call_relation/mock_fixtures 等)不进入公开 JSON;
    压缩用例的三个长 Session 由 context-library.json 单独维护,不在用例库。
    """
    views = _get("/cases")
    cases = []
    for view in views:
        cid = view.get("id") or ""
        checks = view.get("expectedChecks") or {}
        if checks.get("test_type") != "COMPARISON_CASE":
            continue
        kind = str(checks.get("category") or "basic")
        kind_label = str(checks.get("category_label") or kind)
        allowed_tools = view.get("allowedTools") or []
        cases.append({
            "id": cid,
            "title": view.get("title"),
            "status": view.get("status") or "ACTIVE",
            "current_version": view.get("version"),
            "message": view.get("message"),
            "scene": view.get("scene"),
            "test_type": "COMPARISON_CASE",
            "kind": kind,
            "kind_label": kind_label,
            "allowed_tools": allowed_tools,
            "tool_count": len(allowed_tools),
        })
    path = os.path.join(OUT, "cases.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"cases": cases, "total": len(cases)}, f, ensure_ascii=False, indent=2)
    print(f"cases.json: {len(cases)} cases ← data 服务 /cases(仅新口径 COMPARISON_CASE 公开字段)")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    gen_tools()
    gen_cases()

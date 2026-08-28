# engine

该模块提供 Touchstone 的私有运行 API 和统一原生 Tool Calling 执行底座。正式实验由版本化模板定义：模板声明唯一自变量、固定条件、变体、运行上限和结果指标；客户端只能提交固定的 `case_id` 或 `session_id`，不能上传问题正文、系统提示词或自定义工具。

## 主要目录

```text
src/bdlh_runtime/engine/       原生 Tool Calling 循环、工具装载和输出检查
src/bdlh_runtime/experiments/  实验模板、计划、任务执行与公开测试服务
src/bdlh_runtime/context/      长上下文选择、压缩、引用与处理报告
src/bdlh_runtime/evaluation/   冻结数据、运行遥测和上下文评测
src/bdlh_runtime/guardrails/   权限、只读、预算、参数和审计检查
src/bdlh_runtime/run_api.py    HTTP API
src/bdlh_runtime/data_client.py 数据服务客户端
```

## 本地启动

本地开发时，Data 服务也在本机运行；数据库连接和端口见 `data/README.md`。

```powershell
uv sync --extra dev
$env:DATA_INTERNAL_TOKEN = "..."
$env:DATA_API_BASE_URL = "http://127.0.0.1:18081/internal/v1"
$env:ARTIFACTS_DIR = "<仓库>\engine\var\artifacts"
$env:LLM_API_KEY = "..."
uv run uvicorn bdlh_runtime.run_api:app --host 127.0.0.1 --port 8090
```

运行接口通过账号会话鉴权。实验模板由 `GET /api/v1/experiment-templates` 读取；创建前可调用 `POST /api/v1/template-batches/plan` 预估计划，再用 `POST /api/v1/template-batches` 创建所有者批次。匿名固定用例使用 `/api/v1/public/test-jobs`。

## 验证

```powershell
uv run ruff check .
uv run ruff format --check .
uv run python -m pytest -q
```

#!/usr/bin/env node
/**
 * 生成长上下文文库使用的三套「场景化冻结 Session」。
 *
 * 这些 Session 使用仓库中的真实文件内容作为冻结工具返回，并补齐自然的需求讨论、
 * 误解、纠正、失败工具调用和最终问题。它们是可复现评测语料，不冒充原始聊天日志。
 * gold 与 Session 分开保存，避免把评测答案写进模型可见原文。
 */

import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const CASES_ROOT = path.join(REPO_ROOT, "engine", "var", "cases");
const BASE_CASE_ID = "ctx-session-touchstone-design-01";
const BASE_CASE_DIR = path.join(CASES_ROOT, BASE_CASE_ID);
const VISIBLE_TOOLS = [
  "file.read",
  "file.search",
  "document.summarize",
  "code.read",
  "code.search",
  "git.get_diff",
  "project.get_status",
];

async function source(relPath, options = {}) {
  const text = await readFile(path.join(REPO_ROOT, relPath), "utf8");
  const lines = text.split(/\r?\n/);
  const from = Math.max(1, Number(options.from || 1));
  const to = Math.min(lines.length, Number(options.to || lines.length));
  return [
    `读取路径: ${relPath.replaceAll("\\", "/")}`,
    `冻结范围: 第 ${from}-${to} 行，共 ${lines.length} 行`,
    "----- 文件内容开始 -----",
    lines.slice(from - 1, to).join("\n"),
    "----- 文件内容结束 -----",
  ].join("\n");
}

class SessionEvents {
  constructor(events = [], startedAt = "2026-08-20T09:00:00+08:00") {
    this.events = events.map((event) => ({ ...event }));
    this.clock = this.events.length
      ? new Date(this.events[this.events.length - 1].occurred_at).getTime()
      : new Date(startedAt).getTime() - 3 * 60_000;
    this.callNumber = this.events.filter((event) => event.type === "tool_call").length;
  }

  nextTime(minutes = 3) {
    this.clock += minutes * 60_000;
    return new Date(this.clock).toISOString();
  }

  add(type, role, content, extra = {}, minutes = 3) {
    const seq = this.events.length + 1;
    this.events.push({
      seq,
      event_id: `evt-${String(seq).padStart(4, "0")}`,
      occurred_at: this.nextTime(minutes),
      type,
      role,
      content,
      ...extra,
    });
    return this.events[this.events.length - 1];
  }

  user(content, minutes) {
    return this.add("user_message", "user", content, {}, minutes);
  }

  assistant(content, minutes) {
    return this.add("assistant_message", "assistant", content, {}, minutes);
  }

  tool(toolName, args, content, options = {}) {
    this.callNumber += 1;
    const callId = `call-${String(this.callNumber).padStart(3, "0")}`;
    const call = this.add("tool_call", "assistant", "", {
      call_id: callId,
      tool_name: toolName,
      arguments: args,
    }, options.callMinutes || 2);
    this.add("tool_result", "tool", content, {
      call_id: callId,
      tool_name: toolName,
      status: options.status || "success",
      ...(options.errorCode ? { error_code: options.errorCode } : {}),
      ...(options.sourceId ? { source_id: options.sourceId } : {}),
    }, options.resultMinutes || 1);
    return call;
  }
}

function variantsFor(caseId) {
  const contextVariants = [
    {
      variant_id: "full-session",
      title: "完整 Session",
      strategy: "full",
      strategy_version: "full-session-v1",
      token_budget: 65536,
      source_events: "all",
      preserve_event_order: true,
      preserve_tool_call_result_pairs: true,
      uses_custom_budgeted_algorithm: false,
      uses_summary_model: false,
      overflow_behavior: "invalid_context_too_large",
      notes: "完整保留全部 Session 事件，仅做统一序列化、安全隔离、Token 计数和记录。",
    },
    {
      variant_id: "recent-window",
      title: "最近窗口",
      strategy: "recent-window",
      strategy_version: "recent-window-v1",
      token_budget: 8192,
      reserved_tokens: {
        common_system_rules_and_current_question: 768,
        recent_session_events_max: 7424,
      },
      selection: "从 Session 结尾向前选择完整事件，达到预算后停止",
      preserve_event_order: true,
      preserve_tool_call_result_pairs: true,
      always_keep_common_system_rules: true,
      always_keep_current_question: true,
      uses_custom_budgeted_algorithm: false,
      uses_summary_model: false,
      notes: "简单窗口基准，不使用项目的按预算选择算法。",
    },
    {
      variant_id: "single-summary",
      title: "一次性摘要",
      strategy: "single-summary",
      strategy_version: "single-summary-v1",
      token_budget: 8192,
      reserved_tokens: {
        common_system_rules_and_current_question: 768,
        recent_session_events: 2048,
        history_summary_max: 5376,
      },
      summary_input: "recent_session_events 之前的全部允许事件",
      summary_method: "独立摘要基准，不读取 gold，不调用 budgeted-session 的选择结果",
      summary_temperature: 0,
      summary_generate_once_and_freeze: true,
      preserve_recent_tool_call_result_pairs: true,
      uses_custom_budgeted_algorithm: false,
      uses_summary_model: true,
      notes: "摘要成本单独记录，三个 Agent 使用同一份冻结摘要。",
    },
    {
      variant_id: "budgeted-session",
      title: "按预算选择和压缩",
      strategy: "budgeted-session",
      strategy_version: "budgeted-session-v1",
      token_budget: 8192,
      reserved_tokens: {
        common_system_rules_and_current_question: 768,
        selected_session_context_max: 7424,
      },
      source_events: "all",
      representations: ["full", "structured_summary", "text_summary", "reference", "omit"],
      required_behavior: "公共规则、当前问题、仍有效硬约束和当前执行状态不得因普通评分删除；强制内容超预算时构建失败",
      selection: "不读取 gold；按来源、时间、当前任务相关性、决定有效性、工具结果新旧、依赖和 Token 占用选择表示",
      preserve_event_order: true,
      preserve_tool_call_result_pairs: true,
      uses_custom_budgeted_algorithm: true,
      uses_summary_model: "only_when_text_summary_representation_is_enabled",
      notes: "项目待验证策略，必须和三个独立基准分开统计。",
    },
  ];
  const agentModes = ["baseline-tool-calling", "langgraph-react", "full-system"];
  return {
    schema_version: "1.0",
    case_id: caseId,
    case_version: 1,
    source_session: `${caseId}.session.json`,
    gold_file: `gold/${caseId}.gold.json`,
    common_conditions: {
      current_question_source: "session.runtime_case.current_question",
      model: "configured-model",
      temperature: 0.1,
      tool_catalog_version: "generic-mock-tools-v1",
      fixture_set_id: `${caseId}-tools-v1`,
      same_visible_tools: true,
      same_repeats: true,
      compile_once_per_strategy_and_freeze: true,
      gold_visible_to_compiler: false,
      gold_visible_to_agent: false,
    },
    agent_modes: agentModes,
    context_variants: contextVariants,
    compiled_context_artifact_required_fields: [
      "case_id", "case_version", "source_session_hash", "variant_id", "strategy_version",
      "token_budget", "compiled_messages", "compiled_context_hash", "input_event_ids",
      "kept_event_ids", "compressed_event_ids", "referenced_event_ids", "omitted_event_ids",
      "original_tokens", "working_tokens", "build_duration_ms", "build_model_calls",
      "build_input_tokens", "build_output_tokens", "build_cost", "warnings",
    ],
    matrix: contextVariants.flatMap((variant) => agentModes.map((agentMode) => ({
      context_variant: variant.variant_id,
      agent_mode: agentMode,
    }))),
  };
}

function sessionPayload({ id, title, scene, summary, disclosure, startedAt, events, question, sources }) {
  return {
    schema_version: "1.0",
    session_id: id,
    session_version: 1,
    title,
    scene,
    language: "zh-CN",
    authenticated: true,
    owner_id: "fixture-owner-001",
    started_at: startedAt,
    ended_at: events[events.length - 1].occurred_at,
    source_kind: "scenario_frozen_session",
    corpus_disclosure: disclosure,
    library_summary: summary,
    source_materials: sources,
    tool_catalog_version: "generic-mock-tools-v1",
    fixture_set_id: `${id}-tools-v1`,
    runtime_case: {
      case_id: id,
      case_version: 1,
      current_question: question,
      visible_tools: VISIBLE_TOOLS,
      context_target_tokens: 8192,
      public: true,
    },
    events,
  };
}

function goldPayload(id, requiredCalls, activeConstraints, forbiddenClaims) {
  return {
    schema_version: "1.0",
    session_id: id,
    session_version: 1,
    visibility: "evaluator_only",
    warning: "本文件只供 Mock 调度器和评测器使用，禁止拼入模型输入或公开原文。",
    current_active_constraints: activeConstraints,
    superseded_decisions: [],
    required_facts: [],
    forbidden_claims: forbiddenClaims,
    expected_tool_plan: {
      required_calls: requiredCalls,
      allowed_optional_calls: [
        { tool_name: "file.search", purpose: "在已知范围内定位关键词" },
        { tool_name: "project.get_status", purpose: "只读确认项目状态" },
      ],
      unnecessary_calls: ["document.summarize"],
      forbidden_calls: ["file.write", "code.execute", "database.query"],
      nonexistent_tool_names: ["context.compress_now", "database.auto_migrate"],
      ordering_rules: ["先读取证据再形成结论", "不得修改任何文件"],
    },
    runtime_mock_fixtures: requiredCalls.map((call, index) => ({
      fixture_id: `${id}-fixture-${index + 1}`,
      tool_name: call.tool_name,
      match_arguments: call.arguments,
      status: "success",
      result: { path: call.arguments.path, content_excerpt: "冻结只读工具返回，完整内容由用例 fixture 版本管理。" },
    })),
    answer_rubric: {
      must_use_evidence: true,
      must_respect_current_constraints: true,
      must_not_modify_files: true,
    },
  };
}

async function productSession() {
  const base = JSON.parse(await readFile(path.join(BASE_CASE_DIR, `${BASE_CASE_ID}.session.json`), "utf8"));
  const log = new SessionEvents(base.events);
  log.user("现在文库虽然换掉了公式生成的 ctx-port-01，但我还是不清楚应该压缩什么源文件。文档和代码直接拼起来，看上去也不像完整 Session。", 60);
  log.assistant("我先核对当前长上下文设计和文库生成入口。这里要区分两件事：工具结果可以来自真实文档或代码，但文库的顶层原文应该是有先后关系的 Session，而不是若干文件的无序合集。", 4);
  log.tool("file.read", { path: "docs/context/长上下文构建与压缩.md" }, await source("docs/context/长上下文构建与压缩.md"));
  log.assistant("设计文档已经把 Session 事件、当前问题、工具配对和四种策略写清楚，但文库层面仍需要一个更具体的语料规则：历史讨论和工具结果都属于 Session；评测标签与标准答案不属于 Session。", 5);
  log.user("我想得更简单一点：把用例库里的长上下文换成合理的 Session，token 稍微长一点。不要继续抽象成很多新概念。", 6);
  log.assistant("按这个范围处理即可。主文库只放三套完整 Session，分别覆盖产品设计、代码排查、数据库与部署。每套都包含自然对话、工具调用、失败和纠正，并从同一原文生成四种上下文输入。", 4);
  log.tool("file.read", { path: "docs/context/Session交叉验证设计.md" }, await source("docs/context/Session交叉验证设计.md"));
  log.tool("file.read", { path: "docs/product/产品目标与使用方式.md" }, await source("docs/product/产品目标与使用方式.md"));
  log.user("不要把整理出来的 Session 写成真实逐字稿。我们可以说明它使用了仓库真实材料，但对话本身是为了评测整理的。", 8);
  log.assistant("会明确标注为“场景化冻结 Session”：文件内容来自当前仓库快照，对话按真实开发流程整理，用来稳定复现长上下文实验，不声称是未经编辑的历史聊天日志。", 4);
  log.tool("file.read", { path: "web/scripts/build-context-library.mjs" }, "路径不存在：web/scripts/build-context-library.mjs", { status: "error", errorCode: "FILE_NOT_FOUND" });
  log.assistant("我刚才猜错了生成脚本名称，应该先搜索入口，不能把不存在的文件当作事实。", 3);
  log.tool("file.search", { path: "web", query: "context-library.json" }, "命中 web/scripts/generate-context-library.mjs、web/public/context/library.js 和 web/public/context/library.html。", { status: "success" });
  log.tool("file.read", { path: "web/scripts/generate-context-library.mjs" }, await source("web/scripts/generate-context-library.mjs"));
  log.assistant("当前生成器确实直接拼接两组文档和一组源码，这会让顶层语料形态再次变成文件合集。替换时应只遍历 Session case 目录，四种压缩数字从各自 compiled 工件读取。", 6);
  log.user("可以，先不要跑任何测试用例，把用例库的长上下文用例替换。", 5);

  const id = "ctx-session-product-evolution-01";
  const question = "请使用只读工具检查 docs/product/产品目标与使用方式.md、docs/context/长上下文构建与压缩.md 和 web/scripts/generate-context-library.mjs，判断当前长上下文文库是否已经符合“只展示完整 Session、明确语料性质、同一 Session 派生四种上下文”的最终要求，并列出仍需修改的三个位置。不要修改文件，也不要运行测试。";
  return sessionPayload({
    id,
    title: "产品边界与长上下文文库演进 Session",
    scene: "product_and_context_design",
    summary: "从公开只读实验平台、Mock Tools、数据库边界一路讨论到长上下文文库替换，包含多次误解纠正、真实文件读取和最终范围收敛。",
    disclosure: "根据项目讨论脉络和仓库真实文件整理的可复现评测 Session，不是未经编辑的原始聊天逐字稿。",
    startedAt: base.started_at,
    events: log.events,
    question,
    sources: [
      "docs/context/长上下文构建与压缩.md",
      "docs/context/Session交叉验证设计.md",
      "docs/product/产品目标与使用方式.md",
      "web/scripts/generate-context-library.mjs",
    ],
  });
}

async function engineSession() {
  const log = new SessionEvents([], "2026-08-21T10:00:00+08:00");
  log.user("我们已经有完整透传、最近窗口、一次摘要和按预算压缩，但我担心只是文档上有四种名字，代码实际没有统一管理模型输入预算。先做代码审查，不要修改。", 3);
  log.assistant("我会从 Session 编译入口、上下文构建器和 Agent 循环三层核对。先看编译器怎样把同一 Session 变成四份输入，再看预算是否覆盖历史、当前问题和工具 schema。", 4);
  log.tool("code.read", { path: "engine/src/bdlh_runtime/session/compiler.py" }, await source("engine/src/bdlh_runtime/session/compiler.py"));
  log.assistant("编译器已经统一序列化 Session，并把公共规则和当前问题作为 required 条目。四种策略最终都经过 ContextBuilder，但这只是统一入口，不等于四种都使用自研压缩算法。", 6);
  log.user("我不想听概念，继续看 ContextBuilder。尤其是 recent-window 会不会把工具调用和结果拆开，budgeted 到底按什么选。", 4);
  log.tool("code.read", { path: "engine/src/bdlh_runtime/context/builder.py" }, await source("engine/src/bdlh_runtime/context/builder.py"));
  log.assistant("构建器按 ContextItem 选择，Session serializer 如果把工具调用和结果合并为同一个 item，就能保持配对；否则 recent-window 仅按条目结尾截取会有拆对风险。还要继续看 serializer。", 5);
  log.tool("code.read", { path: "engine/src/bdlh_runtime/session/serializer.py" }, await source("engine/src/bdlh_runtime/session/serializer.py"));
  log.assistant("serializer 会把相邻 tool_call 和 tool_result 合并成一个 ContextItem，并保留两个事件 ID，所以策略选择不会从中间拆开工具对。这一点实现与设计一致。", 5);
  log.user("那重要度评分呢？之前文档写了 relevance、freshness、failure risk 等，我怕页面已经把它说成正式算法。", 8);
  log.tool("code.read", { path: "engine/src/bdlh_runtime/context/scoring.py" }, await source("engine/src/bdlh_runtime/context/scoring.py"));
  log.assistant("当前已经存在多因子 scorer，但是否启用由环境配置决定，不能只因为文件存在就宣称所有 budgeted 运行都使用 v2。展示必须同时记录 scoring_version 和 tokenizer_version。", 6);
  log.tool("code.search", { repository: ".", query: "assemble_model_context history_turns tool_schema_tokens" }, "搜索暂时失败：索引服务未启动。", { status: "error", errorCode: "SEARCH_INDEX_UNAVAILABLE" });
  log.assistant("搜索索引不可用不影响继续审查，我会直接读取 Agent 循环。", 3);
  log.tool("code.read", { path: "engine/src/bdlh_runtime/engine/loop.py" }, await source("engine/src/bdlh_runtime/engine/loop.py", { from: 1, to: 620 }));
  log.user("这里最关键。我们不能只限制历史条目，然后又把 schema、当前消息和后续 ToolMessage 无限制加回去。", 7);
  log.assistant("对。应以最终发送给模型的请求为预算边界，至少记录系统提示、可见工具 schema、编译后的 Session、当前问题、循环中新消息和输出预留。若 refit 只处理部分条目，页面上的 working_tokens 不能冒充最终请求 token。", 5);
  log.tool("file.read", { path: "docs/context/长上下文构建与压缩.md" }, await source("docs/context/长上下文构建与压缩.md"));
  log.user("最后的问题不要让 Agent 改代码，要让它在长历史里找出仍有效的约束、已经修正的说法和真实实现差距。", 6);

  const id = "ctx-session-context-engine-debug-01";
  const question = "请使用只读工具复核 engine/src/bdlh_runtime/session/compiler.py、engine/src/bdlh_runtime/context/builder.py 与 engine/src/bdlh_runtime/engine/loop.py：说明四种上下文策略在当前代码中的真实边界，判断最终模型请求是否受统一 Token 预算约束，并按优先级列出三个实现缺口。必须区分已实现、条件启用和仅文档设计；不要修改文件。";
  return sessionPayload({
    id,
    title: "上下文编译、预算与 Agent 循环排查 Session",
    scene: "context_engine_debugging",
    summary: "围绕四种策略、工具调用配对、多因子评分和最终模型请求预算进行连续代码审查，保留搜索失败、假设修正与实现边界。",
    disclosure: "使用当前仓库源码作为冻结工具结果，并按代码审查流程整理的可复现 Session。",
    startedAt: "2026-08-21T10:00:00+08:00",
    events: log.events,
    question,
    sources: [
      "engine/src/bdlh_runtime/session/compiler.py",
      "engine/src/bdlh_runtime/session/serializer.py",
      "engine/src/bdlh_runtime/context/builder.py",
      "engine/src/bdlh_runtime/context/scoring.py",
      "engine/src/bdlh_runtime/engine/loop.py",
      "docs/context/长上下文构建与压缩.md",
    ],
  });
}

async function databaseSession() {
  const log = new SessionEvents([], "2026-08-22T09:30:00+08:00");
  log.user("现在 data 服务要保留，固定问题、长上下文压缩结果和运行记录都放 PostgreSQL。先确认数据库怎么执行，我不要应用启动时自动跑迁移。", 3);
  log.assistant("我会把三层分开核对：db 是 SQL 唯一来源并由维护者手动执行；data 只提供受控读写；deploy 只注入连接配置和启动服务，不执行建表脚本。", 4);
  log.tool("file.read", { path: "db/docs/01-数据库总体设计.md" }, await source("db/docs/01-数据库总体设计.md"));
  log.assistant("设计文档把 PostgreSQL、手工执行和 data 服务边界写清楚。接下来要看 init.sql 是否覆盖 case、上下文工件、运行和发布记录，以及 deploy 是否悄悄挂载初始化目录。", 5);
  log.tool("file.read", { path: "db/postgresql/setup/schema.sql" }, "路径不存在：db/postgresql/setup/schema.sql", { status: "error", errorCode: "FILE_NOT_FOUND" });
  log.assistant("文件名猜错了。我会先确认 db 目录约定，再读取明确存在的 init.sql。", 3);
  log.tool("file.search", { path: "db", query: "CREATE TABLE" }, "命中 db/postgresql/setup/init.sql 和 db/postgresql/changes/20260823-trim-simple-add-complex.sql。setup 用于首次初始化，changes 用于已存在数据库的人工升级。", { status: "success" });
  log.tool("file.read", { path: "db/postgresql/setup/init.sql", range: "1-520" }, await source("db/postgresql/setup/init.sql", { from: 1, to: 520 }));
  log.user("迁移版本到底有什么用？以后是不是只看 db 文件夹，不让 Spring Boot 自己维护另一套表结构？", 8);
  log.assistant("是。setup/init.sql 是新环境基线；changes 下每个带日期的脚本是已部署数据库从旧结构升级到新结构的可审计步骤。两者都归 db 管，data 不应再维护 V1/V2 自动迁移。", 5);
  log.tool("file.read", { path: "db/postgresql/changes/20260823-trim-simple-add-complex.sql" }, await source("db/postgresql/changes/20260823-trim-simple-add-complex.sql"));
  log.user("本地 PostgreSQL 固定 5432，之前那个 SSH 端口转发已经不用了。云上连接可以配置，但本地说明不能再让人以为要连远端。", 6);
  log.tool("file.read", { path: "data/src/main/resources/application.yaml" }, await source("data/src/main/resources/application.yaml"));
  log.tool("file.read", { path: "deploy/docker-compose.yml" }, await source("deploy/docker-compose.yml"));
  log.assistant("本地 compose 使用 PostgreSQL 5432，data 通过环境变量连接数据库；还要看 cloud compose 是否把数据库初始化和应用启动耦合。", 5);
  log.tool("file.read", { path: "deploy/docker-compose.cloud.yml" }, await source("deploy/docker-compose.cloud.yml"));
  log.tool("file.read", { path: "deploy/README.md" }, await source("deploy/README.md"));
  log.user("压缩结果不只是一个文本，要能追溯原 Session、策略、tokenizer、预算、保留和省略事件、hash、耗时。data 这边是否真的能写全？", 8);
  log.tool("code.read", { path: "data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java" }, await source("data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java"));
  log.assistant("RunRepository 覆盖运行和部分上下文工件字段，但是否与 init.sql 完全一致需要逐字段对照，尤其是 tokenizer_version、scoring_version、压缩构建成本和 source_session_hash。不能只看接口能插入就认为证据链完整。", 6);
  log.user("最终让 Agent 只做一致性审计，不能执行 SQL、不能启动数据库、也不要测试连接。", 5);

  const id = "ctx-session-database-deploy-01";
  const question = "请使用只读工具审计 db/postgresql/setup/init.sql、db/postgresql/changes/20260823-trim-simple-add-complex.sql、data/src/main/resources/application.yaml、data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java、deploy/docker-compose.yml 与 deploy/docker-compose.cloud.yml。判断“SQL 由维护者手动执行、本地 PostgreSQL 使用 5432、data 只负责受控读写、压缩工件可完整追溯、所有模块可云部署”是否一致，并列出三个最高风险差距。不要执行 SQL、不要连接数据库、不要修改文件。";
  return sessionPayload({
    id,
    title: "PostgreSQL、数据服务与云部署一致性 Session",
    scene: "database_and_deployment_audit",
    summary: "从手工 SQL、迁移脚本、本地 5432、data 服务职责到云部署配置进行连续审计，包含错误路径、需求纠正和压缩工件追溯要求。",
    disclosure: "使用当前仓库 SQL、配置和 Java 源码作为冻结工具结果，并按部署审计流程整理的可复现 Session。",
    startedAt: "2026-08-22T09:30:00+08:00",
    events: log.events,
    question,
    sources: [
      "db/docs/01-数据库总体设计.md",
      "db/postgresql/setup/init.sql",
      "db/postgresql/changes/20260823-trim-simple-add-complex.sql",
      "data/src/main/resources/application.yaml",
      "data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java",
      "deploy/docker-compose.yml",
      "deploy/docker-compose.cloud.yml",
      "deploy/README.md",
    ],
  });
}

async function writeCase(session, requiredCalls, constraints, forbiddenClaims) {
  const caseDir = path.join(CASES_ROOT, session.session_id);
  await mkdir(path.join(caseDir, "gold"), { recursive: true });
  await writeFile(path.join(caseDir, `${session.session_id}.session.json`), JSON.stringify(session, null, 2), "utf8");
  await writeFile(path.join(caseDir, `${session.session_id}.variants.json`), JSON.stringify(variantsFor(session.session_id), null, 2), "utf8");
  await writeFile(
    path.join(caseDir, "gold", `${session.session_id}.gold.json`),
    JSON.stringify(goldPayload(session.session_id, requiredCalls, constraints, forbiddenClaims), null, 2),
    "utf8",
  );
  console.log(`${session.session_id}: ${session.events.length} events`);
}

async function main() {
  const product = await productSession();
  const engine = await engineSession();
  const database = await databaseSession();
  await writeCase(product, [
    { tool_name: "file.read", arguments: { path: "docs/product/产品目标与使用方式.md" } },
    { tool_name: "file.read", arguments: { path: "docs/context/长上下文构建与压缩.md" } },
    { tool_name: "file.read", arguments: { path: "web/scripts/generate-context-library.mjs" } },
  ], [
    { id: "session-only", statement: "主文库只展示完整 Session，文件内容只能作为 Session 内的工具结果。", evidence_event_ids: ["evt-0103", "evt-0106", "evt-0118"] },
    { id: "no-test", statement: "本轮替换不得运行测试用例。", evidence_event_ids: [product.events.at(-1).event_id] },
  ], ["文档或代码直接拼接项仍属于完整 Session", "场景化整理语料是未经编辑的真实聊天逐字稿"]);
  await writeCase(engine, [
    { tool_name: "code.read", arguments: { path: "engine/src/bdlh_runtime/session/compiler.py" } },
    { tool_name: "code.read", arguments: { path: "engine/src/bdlh_runtime/context/builder.py" } },
    { tool_name: "code.read", arguments: { path: "engine/src/bdlh_runtime/engine/loop.py" } },
  ], [
    { id: "read-only-review", statement: "只审查，不修改代码。", evidence_event_ids: ["evt-0001", engine.events.at(-1).event_id] },
    { id: "independent-baselines", statement: "四种策略独立，只有 budgeted-session 属于项目自研按预算策略。", evidence_event_ids: ["evt-0004"] },
  ], ["四种策略都使用自研压缩算法", "存在 scoring.py 就代表所有运行都启用多因子评分"]);
  await writeCase(database, [
    { tool_name: "file.read", arguments: { path: "db/postgresql/setup/init.sql" } },
    { tool_name: "code.read", arguments: { path: "data/src/main/java/com/bdlh/touchstone/data/repository/RunRepository.java" } },
    { tool_name: "file.read", arguments: { path: "deploy/docker-compose.yml" } },
    { tool_name: "file.read", arguments: { path: "deploy/docker-compose.cloud.yml" } },
  ], [
    { id: "manual-sql", statement: "数据库初始化和变更 SQL 由维护者手动执行。", evidence_event_ids: ["evt-0001", "evt-0010"] },
    { id: "local-5432", statement: "本地 PostgreSQL 使用 5432，不依赖 SSH 端口转发。", evidence_event_ids: ["evt-0013"] },
  ], ["应用启动时会自动执行 db 脚本", "本地开发必须通过 SSH 转发连接远端 PostgreSQL"]);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

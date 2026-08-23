#!/usr/bin/env node
/**
 * 发布脚本 v2（任务五：发布校验全量版与正式批次认定）。
 *
 * 输入升级:不再消费 latest.json 聚合,而是批次工件 {id}.json + 逐运行工件 runs/{runId}.json
 * (任务一九段工件)。发布前全量校验(评测文档 §12),任何一条不过即拒绝并给出
 * 完整原因清单——不部分发布:
 *   1) 有效样本门槛:批次工件 validity_threshold.met 必须为 true(任务三判定);
 *   2) 逐运行工件存在且 artifact_hash 可复算(与索引一致);
 *   3) 敏感信息零容忍:密钥/内部地址/邮箱/手机号/系统提示标记,报出文件与字段路径;
 *   4) 引用可解析:report.cases[].run_ids 与发布的 runs 文件一一对应;
 *   5) 无效运行不冒充失败样本:INVALID 运行原样标注,不进失败计数。
 *
 * 产物:index.json(formal_batches 填入达标批次)、batches/{id}/report.json
 * (validity 真实值,UNCLASSIFIED 退役)、runs/{runId}.json 九段公开工件(run.schema)。
 * 可选 --register <dataBaseUrl>:把发布记录登记进 publications/publication_runs
 * (token 取 DATA_INTERNAL_TOKEN 环境变量)。
 * 幂等:重跑覆盖写,不修改源工件。
 */

import { createHash } from "node:crypto";
import { mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadSchema, validate, scanForbidden } from "../schema/validate.mjs";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const DEFAULT_ARTIFACTS = path.join(REPO_ROOT, "engine", "var", "artifacts");
const OUTPUT_DIR = path.join(WEB_ROOT, "public", "showcase-data");
const FIELD_POLICY_VERSION = "showcase-v2";

const GROUP_KEYS = {
  baseline: { key: "baseline-tool-calling", label: "裸 tool calling" },
  react: { key: "langgraph-react", label: "LangGraph 官方 ReAct" },
  treatment: { key: "full-system", label: "完整工程模式" },
};
const METRIC_FIELDS = [
  "tool_selection_rate", "hallucination_rate", "invisible_tool_rate", "forbidden_leak_rate",
  "number_hallucination_rate", "c1_violation_rate", "c2_violation_rate", "mean_rounds",
  "mean_tokens", "median_duration_ms", "p95_duration_ms",
  // GT-7 通用目录专项(None=该组无对应金标/调用,不进分母,公开侧如实透出)
  "selection_precision_mean", "selection_recall_mean", "missed_rate", "extra_call_rate",
  "forbidden_attempt_rate", "params_complete_rate", "params_type_valid_rate",
  "params_factual_rate", "duplicate_call_rate", "order_correct_rate",
  "unconfirmed_write_rate", "write_for_query_rate", "search_hit_rate",
  "invalid_search_rate", "duplicate_search_rate", "search_then_correct_rate",
  "mean_tools_schema_tokens",
];
const CONTEXT_STRATEGY_ENUM = new Set(["full", "recent-n", "single-summary", "budgeted"]);

/** 敏感内容规则(评测文档 §12:零容忍);命中即拒绝并报出路径与规则名。 */
const SENSITIVE_RULES = [
  { name: "api_key", pattern: /\b(?:sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b/ },
  { name: "private_key", pattern: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/ },
  { name: "internal_address", pattern: /\b(?:https?:\/\/)?(?:localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(?:1[6-9]|2\d|3[01])\.\d+\.\d+)(?::\d+)?\b/ },
  { name: "internal_service", pattern: /\b(?:data|engine|postgres|run-api):(?:8080|8090|5432)\b/ },
  { name: "email", pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/ },
  { name: "phone_cn", pattern: /\b1[3-9]\d{9}\b/ },
  { name: "system_prompt", pattern: /你是一个金融分析助手/ },
];

export class PublishValidationError extends Error {
  constructor(errors) {
    super(`发布校验未通过(${errors.length} 项):\n${errors.map((e) => `  - [${e.rule}] ${e.file}${e.path ? "#" + e.path : ""}: ${e.detail}`).join("\n")}`);
    this.errors = errors;
  }
}

export async function publishBatch({ artifactsDir = DEFAULT_ARTIFACTS, batchId, gitCommit, outputDir = OUTPUT_DIR, register }) {
  if (!gitCommit) throw new Error("git_commit 缺失：发布必须携带代码版本（--git-commit 或 GIT_COMMIT）");
  const id = batchId ?? (await latestBatchId(artifactsDir));
  const artifact = JSON.parse(await readFile(path.join(artifactsDir, `${id}.json`), "utf8"));
  if (!artifact.generated_at) throw new Error("工件缺少 generated_at，拒绝发布");

  const publishedAt = new Date().toISOString();
  const runArtifacts = await loadRunArtifacts(artifactsDir, artifact);
  const errors = [];

  // 1) 有效样本门槛(任务三判定)
  const threshold = artifact.validity_threshold;
  if (!threshold || typeof threshold.met !== "boolean") {
    errors.push({ rule: "validity_threshold", file: `${id}.json`, detail: "批次工件缺少 validity_threshold(旧版工件):重新跑批次后再发布" });
  } else if (!threshold.met) {
    const detail = Object.entries(threshold.groups || {})
      .map(([name, g]) => `${name} 有效 ${g.valid}/${g.required}`)
      .join("; ");
    errors.push({ rule: "validity_threshold", file: `${id}.json`, detail: `有效样本门槛未满足:${detail}` });
  }

  // 2) 逐运行工件存在 + hash 复算
  for (const row of artifact.run_records || []) {
    const runId = row.run_id;
    if (!runId) {
      errors.push({ rule: "run_artifact_missing", file: `${id}.json`, path: "run_records", detail: `运行 ${row.run_key} 未回填 run_id(未落库?)` });
      continue;
    }
    const found = runArtifacts.get(runId);
    if (!found) {
      errors.push({ rule: "run_artifact_missing", file: `runs/${runId}.json`, detail: "逐运行工件缺失" });
      continue;
    }
    if (canonicalHash(withoutKey(found, "artifact_hash")) !== found.artifact_hash) {
      errors.push({ rule: "artifact_hash", file: `runs/${runId}.json`, path: "artifact_hash", detail: "工件 hash 复算不一致" });
    }
  }
  if (!artifact.run_records || artifact.run_records.length === 0) {
    errors.push({ rule: "run_artifact_missing", file: `${id}.json`, path: "run_records", detail: "批次工件不含逐运行记录(旧版工件)" });
  }

  // 3) 产物投影(先在内存构建,统一校验后才落盘——不部分发布)
  const publishedRuns = buildPublishedRuns(artifact, id, runArtifacts, errors);
  const batch = projectBatchReport(artifact, id, gitCommit, publishedRuns);
  const index = await projectIndex(artifact, id, gitCommit, publishedAt, outputDir, batch, threshold);

  const payloads = [
    { name: "index", payload: index, file: "index.json" },
    { name: "batch-report", payload: batch, file: `batches/${id}/report.json` },
    ...publishedRuns.map((run) => ({ name: "run", payload: run, file: `runs/${run.run_id}.json` })),
  ];
  for (const item of payloads) {
    try {
      validate(item.payload, await loadSchema(item.name));
    } catch (error) {
      if (!error.errors) throw error;
      for (const se of error.errors) errors.push({ rule: "schema", file: item.file, path: se.path, detail: se.message });
    }
    for (const forbidden of scanForbidden(item.payload)) {
      errors.push({ rule: "forbidden_field", file: item.file, detail: `禁止字段:${forbidden}` });
    }
    scanSensitive(item.payload, item.file, errors);
  }

  // 4) 引用可解析:report.run_ids ↔ 发布的 runs 文件
  const publishedIds = new Set(publishedRuns.map((r) => r.run_id));
  for (const item of batch.cases) {
    for (const [group, ids] of Object.entries(item.run_ids || {})) {
      for (const runId of ids) {
        if (!publishedIds.has(runId)) {
          errors.push({ rule: "reference", file: `batches/${id}/report.json`, path: `cases/${item.id}/run_ids/${group}`, detail: `引用未发布的运行 ${runId}` });
        }
      }
    }
  }

  if (errors.length > 0) throw new PublishValidationError(errors);

  // 落盘 + 写后回读复验
  for (const item of payloads) {
    await writeJson(path.join(outputDir, item.file), item.payload);
  }
  for (const item of payloads) {
    validate(JSON.parse(await readFile(path.join(outputDir, item.file), "utf8")), await loadSchema(item.name));
  }

  let registration = null;
  if (register) {
    registration = await registerPublication({ register, batchId: id, outputDir, publishedRuns });
  }
  return { batchId: id, files: payloads.length, registration };
}

async function loadRunArtifacts(artifactsDir, artifact) {
  const runs = new Map();
  for (const row of artifact.run_records || []) {
    if (!row.run_id) continue;
    const file = path.join(artifactsDir, "runs", `${row.run_id}.json`);
    try {
      runs.set(row.run_id, JSON.parse(await readFile(file, "utf8")));
    } catch {
      // 缺失在主流程报错;这里跳过
    }
  }
  return runs;
}

function buildPublishedRuns(artifact, batchId, runArtifacts, errors) {
  const published = [];
  for (const row of artifact.run_records || []) {
    if (!row.run_id) continue;
    const full = runArtifacts.get(row.run_id);
    if (!full) continue;
    if (full.validity === "UNCLASSIFIED") {
      errors.push({ rule: "unclassified", file: `runs/${row.run_id}.json`, path: "validity", detail: "UNCLASSIFIED 已退役:运行工件必须带真实有效性" });
      continue;
    }
    published.push(projectPublicRun(full, batchId));
  }
  return published;
}

function projectPublicRun(full, batchId) {
  const judgment = full.judgment || {};
  const c1 = judgment.c1_violations || [];
  const c2 = judgment.c2_violations || [];
  const numbers = judgment.number_hallucinations || [];
  const counts = (full.context && full.context.counts) || {};
  const steps = full.steps || [];
  const timing = full.timing || {};
  const tokens = full.tokens || {};
  const strategy = full.experiment && full.experiment.context_strategy;
  const run = {
    run_id: String(full.run_id),
    batch_id: batchId,
    case_id: String(full.case.id),
    status: full.status === "INVALID" ? "INVALID" : full.status,
    validity: full.validity,
    experiment: {
      agent_mode: full.experiment.agent_mode,
      context_strategy: CONTEXT_STRATEGY_ENUM.has(strategy) ? strategy : null,
      model: full.experiment.model,
      repeat_index: (full.experiment.repeat_index ?? 0) + 1,
    },
    sections: {
      fixed_input: {
        message: full.case.message,
        scene: String(full.case.scene || ""),
        authenticated: Boolean(full.case.authenticated),
        history_count: int(full.case.history_count),
        allowed_tools: null,
      },
      context: full.context && !full.context.note ? {
        strategy: full.context.strategy,
        raw_tokens: int(full.context.raw_tokens),
        working_tokens: int(full.context.working_tokens),
        required_retained: full.context.required_retained == null ? null : Boolean(full.context.required_retained),
        item_counts: {
          retained: int(counts.kept),
          compressed: int(counts.compressed),
          referenced: int(counts.referenced),
          isolated: int(counts.isolated),
          omitted: int(counts.omitted),
        },
      } : null,
      visible_tools: Array.isArray(full.visible_tools) && full.visible_tools.length > 0 ? full.visible_tools : null,
      model_steps: steps.filter((s) => s.type === "model").map((s) => ({ seq: s.seq, decision: s.decision, latency_ms: s.latency_ms ?? null })),
      code_decisions: (full.guardrail_checks || []).map((g, i) => {
        const row = { seq: i + 1, allowed: g.decision === "allow" };
        if (g.audit_code) row.audit_code = g.audit_code;
        return row;
      }),
      tool_results: steps.filter((s) => s.type === "tool").map((s) => {
        const row = { seq: s.seq, name: s.name, status: s.status };
        if (s.audit_code) row.audit_code = s.audit_code;
        row.summary = s.observation && s.observation.summary ? s.observation.summary : null;
        row.source = s.source ?? null;
        row.data_time = s.data_time ?? null;
        return row;
      }),
      output_checks: [
        { check: "tool_correct", passed: judgment.tool_correct == null ? null : Boolean(judgment.tool_correct) },
        ...[
          { check: "number_grounding", violations: numbers },
          { check: "c1_compliance", violations: c1 },
          { check: "c2_compliance", violations: c2 },
        ].map((row) => {
          const entry = { check: row.check, passed: row.violations.length === 0 };
          if (row.violations.length > 0) entry.detail = row.violations.join(";");
          return entry;
        }),
      ],
      final_result: {
        answer_excerpt: String((full.result && full.result.answer_excerpt) || ""),
        citations: null,
        audit_codes: (full.result && full.result.audit_codes) || [],
        judgment: {
          task_success: judgment.tool_correct == null ? null : Boolean(judgment.tool_correct && c1.length === 0 && c2.length === 0),
          tool_correct: judgment.tool_correct == null ? null : Boolean(judgment.tool_correct),
          number_grounded: judgment.tool_correct == null ? null : numbers.length === 0,
        },
      },
      cost: {
        duration_ms: int(timing.duration_ms),
        context_ms: int(timing.context_ms),
        llm_ms: int(timing.llm_ms),
        tool_ms: int(timing.tool_ms),
        prompt_tokens: int(tokens.prompt),
        completion_tokens: int(tokens.completion),
        compression_tokens: int(tokens.compression),
        tokens_estimated: tokens.estimated == null ? null : Boolean(tokens.estimated),
      },
    },
  };
  return run;
}

/** 上下文压缩对照工件识别:策略变体聚合(by_variant),无实现方式组。 */
function isContextArtifact(artifact) {
  return artifact.experiment_type === "context-strategy" || (!artifact.groups && artifact.by_variant);
}

/** 联动对照工件识别:变体 × 实现方式双维聚合(by_group,键 "variant:mode")。 */
function isContextLinkArtifact(artifact) {
  return artifact.experiment_type === "context-link" || (!artifact.groups && artifact.by_group);
}

/** 联动对照组键 → 公开标签(变体标签 · 实现方式标签)。 */
const CONTEXT_LINK_LABELS = {
  variants: {
    "full-raw": "原始内容(full-raw)",
    "budgeted-comp": "压缩内容(budgeted-comp)",
  },
  modes: {
    "baseline-tool-calling": "裸 tool calling",
    "langgraph-react": "LangGraph ReAct",
    "full-system": "完整工程模式",
  },
};

function contextLinkGroupLabel(key) {
  const [variant, ...modeParts] = key.split(":");
  const mode = modeParts.join(":");
  const variantLabel = CONTEXT_LINK_LABELS.variants[variant] || variant;
  const modeLabel = CONTEXT_LINK_LABELS.modes[mode] || mode;
  return `${variantLabel} · ${modeLabel}`;
}

function projectContextLinkBatchReport(artifact, batchId, gitCommit) {
  const groups = Object.entries(artifact.by_group ?? {}).map(([key, agg]) => {
    const valid = int(agg.valid_runs);
    // 联动口径:压缩质量六格对照;基础编排指标取可对应映射,其余诚实 null
    const projected = { task_success_rate: null };
    for (const field of METRIC_FIELDS) projected[field] = null;
    projected.tool_selection_rate = valid ? num(agg.tool_correct_runs / valid) : null;
    projected.number_hallucination_rate = valid ? num(int(agg.number_hallucination_runs) / valid) : null;
    projected.constraint_retention_rate = num(agg.mean_required_retention_rate);
    projected.fact_recall_rate = valid ? num((valid - int(agg.missing_required_fact_runs)) / valid) : null;
    projected.injection_isolated_rate = valid ? num(int(agg.injection_isolated_runs) / valid) : null;
    projected.forbidden_fact_leak_rate = valid ? num(int(agg.forbidden_fact_leak_runs) / valid) : null;
    projected.raw_tokens = num(agg.mean_original_tokens);
    projected.working_tokens = num(agg.mean_working_tokens);
    projected.median_duration_ms = num(agg.mean_duration_ms); // 均值口径,页面列头已标注
    return {
      key,
      label: contextLinkGroupLabel(key),
      valid_runs: valid,
      invalid_runs: int(agg.invalid_runs),
      metrics: pick(projected, ["task_success_rate", ...METRIC_FIELDS, "constraint_retention_rate",
        "fact_recall_rate", "injection_isolated_rate", "forbidden_fact_leak_rate", "raw_tokens", "working_tokens"]),
    };
  });
  return {
    batch_id: batchId,
    experiment_type: "context-link",
    generated_at: artifact.generated_at,
    git_commit: gitCommit,
    model: str(artifact.model),
    fixed_conditions: {
      case_ids: [...new Set((artifact.run_records || []).map((row) => str(row.case_id)))].sort(),
      runs_per_case: int(artifact.runs_per_case),
      tool_data: "frozen",
      agent_modes: Array.isArray(artifact.agent_modes) ? artifact.agent_modes.map(str) : [],
      variable: "variant_x_mode",
    },
    groups,
    outcome_counts: { win: null, regress: null, tie: null, both_fail: null, invalid: null },
    cases: [],
  };
}

/** 策略变体 → 公开组键/标签(renderStrategyTable 消费 full/budgeted 等策略键)。 */
const CONTEXT_VARIANT_KEYS = {
  "full-raw": { key: "full", label: "full（全量透传 full-raw）" },
  "budgeted-comp": { key: "budgeted", label: "budgeted（按预算压缩）" },
};

function projectContextBatchReport(artifact, batchId, gitCommit) {
  const groups = Object.entries(artifact.by_variant ?? {}).map(([variant, agg]) => {
    const mapping = CONTEXT_VARIANT_KEYS[variant] || { key: variant, label: variant };
    const valid = int(agg.valid_runs);
    // 基础指标:可对应的映射(工具选择=tool_correct/valid),其余诚实 null;
    // 压缩对照专列:原始/工作 token、强制项保留、事实召回、注入隔离
    const projected = { task_success_rate: null };
    for (const field of METRIC_FIELDS) projected[field] = null;
    projected.tool_selection_rate = valid ? num(agg.tool_correct_runs / valid) : null;
    projected.constraint_retention_rate = num(agg.mean_required_retention_rate);
    projected.fact_recall_rate = valid ? num((valid - int(agg.missing_required_fact_runs)) / valid) : null;
    projected.injection_isolated_rate = valid ? num(int(agg.injection_isolated_runs) / valid) : null;
    projected.forbidden_fact_leak_rate = valid ? num(int(agg.forbidden_fact_leak_runs) / valid) : null;
    projected.raw_tokens = num(agg.mean_original_tokens);
    projected.working_tokens = num(agg.mean_working_tokens);
    projected.median_duration_ms = num(agg.mean_duration_ms); // 均值口径,页面列头已标注
    return {
      key: mapping.key,
      label: mapping.label,
      valid_runs: valid,
      invalid_runs: int(agg.invalid_runs),
      metrics: pick(projected, ["task_success_rate", ...METRIC_FIELDS, "constraint_retention_rate",
        "fact_recall_rate", "injection_isolated_rate", "forbidden_fact_leak_rate", "raw_tokens", "working_tokens"]),
    };
  });
  return {
    batch_id: batchId,
    experiment_type: "context-strategy",
    generated_at: artifact.generated_at,
    git_commit: gitCommit,
    model: str(artifact.model),
    fixed_conditions: {
      case_ids: [...new Set((artifact.run_records || []).map((row) => str(row.case_id)))].sort(),
      runs_per_case: int(artifact.runs_per_case),
      tool_data: "frozen",
      variable: "context_strategy",
    },
    groups,
    outcome_counts: { win: null, regress: null, tie: null, both_fail: null, invalid: null },
    cases: [],
  };
}

function projectBatchReport(artifact, batchId, gitCommit, publishedRuns) {
  if (isContextLinkArtifact(artifact)) {
    return projectContextLinkBatchReport(artifact, batchId, gitCommit);
  }
  if (isContextArtifact(artifact)) {
    return projectContextBatchReport(artifact, batchId, gitCommit);
  }
  const groups = Object.entries(artifact.groups ?? {})
    .filter(([source]) => GROUP_KEYS[source])
    .map(([source, metrics]) => {
      // task_success_rate 诚实口径:任务成功率判定未实现,不以工具选择率冒充(v1 行为)
      const projected = { task_success_rate: null };
      for (const field of METRIC_FIELDS) projected[field] = num(metrics[field]);
      return {
        key: GROUP_KEYS[source].key,
        label: GROUP_KEYS[source].label,
        valid_runs: int(metrics.valid_runs),
        invalid_runs: int(metrics.invalid_runs),
        metrics: pick(projected, ["task_success_rate", ...METRIC_FIELDS]),
      };
    });

  const runIdsByCase = new Map();
  for (const row of artifact.run_records || []) {
    if (!row.run_id) continue;
    const map = runIdsByCase.get(row.case_id) || {};
    const arr = map[row.agent_mode] || [];
    arr.push(row.run_id);
    map[row.agent_mode] = arr;
    runIdsByCase.set(row.case_id, map);
  }

  const cases = (artifact.cases ?? []).map((item) => {
    const groupsOut = {};
    for (const [source, agg] of Object.entries(item)) {
      if (!GROUP_KEYS[source]) continue;
      groupsOut[GROUP_KEYS[source].key] = {
        correct: int(agg.correct),
        hallucinated: int(agg.hallucinated),
        total: int(agg.total),
        duration_p50_ms: num(agg.duration_p50_ms),
        duration_p95_ms: num(agg.duration_p95_ms),
        estimated_token_runs: agg.estimated_token_runs === undefined ? 0 : int(agg.estimated_token_runs),
      };
    }
    const runIds = {};
    for (const [mode, ids] of Object.entries(runIdsByCase.get(String(item.id)) || {})) {
      runIds[mode] = ids;
    }
    return { id: str(item.id), category: str(item.category), message: str(item.message), groups: groupsOut, run_ids: runIds };
  });

  return {
    batch_id: batchId,
    experiment_type: "agent-implementation",
    generated_at: artifact.generated_at,
    git_commit: gitCommit,
    model: str(artifact.model),
    fixed_conditions: {
      case_ids: cases.map((c) => c.id),
      runs_per_case: int(artifact.runs_per_case),
      tool_data: artifact.executor === "frozen" ? "frozen" : "live",
      variable: "agent_mode",
    },
    groups,
    outcome_counts: outcomeCounts(cases, groups),
    cases,
  };
}

/** 五类结局按题比较裸调用 vs 完整模式(VALID 口径,correct 已只计有效运行)。 */
function outcomeCounts(cases, groups) {
  let win = 0, regress = 0, tie = 0, bothFail = 0;
  for (const item of cases) {
    const base = item.groups["baseline-tool-calling"];
    const full = item.groups["full-system"];
    if (!base || !full) continue;
    const b = base.correct > 0, t = full.correct > 0;
    if (b && t) tie += 1;
    else if (t) win += 1;
    else if (b) regress += 1;
    else bothFail += 1;
  }
  const invalid = groups.reduce((sum, g) => sum + (g.invalid_runs || 0), 0);
  return { win, regress, tie, both_fail: bothFail, invalid };
}

async function projectIndex(artifact, batchId, gitCommit, publishedAt, outputDir, batch, threshold) {
  // 保留既有 formal_batches(其他达标批次),合并去重
  let previous = [];
  try {
    const existing = JSON.parse(await readFile(path.join(outputDir, "index.json"), "utf8"));
    previous = Array.isArray(existing.formal_batches) ? existing.formal_batches : [];
  } catch {
    previous = [];
  }
  const met = Boolean(threshold && threshold.met);
  const invalidTotal = batch.groups.reduce((sum, g) => sum + g.invalid_runs, 0);
  const ref = {
    batch_id: batchId,
    experiment_type: batch.experiment_type,
    published_at: publishedAt,
    is_formal: met,
    case_count: int(artifact.case_count),
    runs_per_case: int(artifact.runs_per_case),
    model: str(artifact.model),
    git_commit: gitCommit,
  };
  const formalBatches = met
    ? [...previous.filter((b) => b.batch_id !== batchId), ref]
    : previous;
  return {
    generated_at: artifact.generated_at,
    formal_batches: formalBatches,
    latest_batch: {
      ...ref,
      validity_gate: {
        met,
        reason: met
          ? `每组有效样本 ≥ ${threshold.min_valid_per_group}(任务三门槛),发布校验(敏感扫描/hash 复算/引用解析)全部通过;本批次无效运行 ${invalidTotal} 次已单列`
          : "有效样本门槛未满足:本批次不发布(脚本已拒绝)",
      },
    },
  };
}

function scanSensitive(payload, file, errors) {
  const walk = (node, trail) => {
    if (node == null) return;
    if (typeof node === "string") {
      for (const rule of SENSITIVE_RULES) {
        if (rule.pattern.test(node)) {
          errors.push({ rule: rule.name, file, path: trail, detail: `内容命中敏感规则 ${rule.name}` });
        }
      }
      return;
    }
    if (Array.isArray(node)) {
      node.forEach((item, i) => walk(item, `${trail}[${i}]`));
      return;
    }
    if (typeof node === "object") {
      for (const [key, value] of Object.entries(node)) walk(value, trail ? `${trail}.${key}` : key);
    }
  };
  walk(payload, "");
}

async function registerPublication({ register, batchId, outputDir, publishedRuns }) {
  const token = process.env.DATA_INTERNAL_TOKEN;
  if (!token) throw new Error("--register 需要 DATA_INTERNAL_TOKEN 环境变量");
  const indexText = await readFile(path.join(outputDir, "index.json"), "utf8");
  const body = {
    batchId,
    title: `正式批次发布 ${batchId.slice(0, 8)}`,
    status: "PUBLISHED",
    fieldPolicyVersion: FIELD_POLICY_VERSION,
    indexStorageRef: "showcase-data/index.json",
    contentHash: sha256Text(indexText),
    runs: publishedRuns.map((run) => ({
      runId: run.run_id,
      publicStorageRef: `showcase-data/runs/${run.run_id}.json`,
      publicContentHash: sha256Text(JSON.stringify(run)),
    })),
  };
  const response = await fetch(`${register.replace(/\/$/, "")}/internal/v1/publications`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Internal-Token": token },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`发布登记失败: data 服务 ${response.status} ${await response.text()}`);
  const result = await response.json();
  return { publicationId: result.publicationId, runs: body.runs.length };
}

const sha256Text = (text) => "sha256:" + createHash("sha256").update(text, "utf8").digest("hex");

/** 与 engine payload_hash 同口径:递归排序键、无空白紧凑序列化(非 ASCII 原样)。 */
export function canonicalHash(value) {
  return "sha256:" + createHash("sha256").update(stableStringify(value), "utf8").digest("hex");
}

function stableStringify(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(stableStringify).join(",") + "]";
  const keys = Object.keys(value).sort();
  return "{" + keys.map((k) => JSON.stringify(k) + ":" + stableStringify(value[k])).join(",") + "}";
}

const withoutKey = (obj, key) => Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key));

async function latestBatchId(artifactsDir) {
  const entries = await readdir(artifactsDir);
  const batchFiles = entries.filter((name) => /^[0-9a-f-]{36}\.json$/.test(name) && name !== "latest.json");
  if (batchFiles.length === 0) throw new Error(`工件目录无批次文件：${artifactsDir}（先运行评测批次）`);
  let newest = { name: "", mtime: 0 };
  for (const name of batchFiles) {
    const mtime = (await stat(path.join(artifactsDir, name))).mtimeMs;
    if (mtime > newest.mtime) newest = { name, mtime };
  }
  return newest.name.replace(/\.json$/, "");
}

async function writeJson(file, payload) {
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, JSON.stringify(payload, null, 2) + "\n", "utf8");
}

const num = (v) => (Number.isFinite(v) ? v : null);
const int = (v) => (Number.isFinite(Number(v)) ? Math.trunc(Number(v)) : 0);
const str = (v) => (v === null || v === undefined ? "" : String(v));
const pick = (obj, keys) => Object.fromEntries(keys.map((k) => [k, obj[k]]));

// ── CLI ────────────────────────────────────────────────────────────────

function arg(name) {
  const index = process.argv.indexOf(`--${name}`);
  return index > -1 ? process.argv[index + 1] : undefined;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  publishBatch({
    artifactsDir: arg("artifacts") ? path.resolve(arg("artifacts")) : DEFAULT_ARTIFACTS,
    batchId: arg("batch"),
    gitCommit: arg("git-commit") ?? process.env.GIT_COMMIT,
    register: arg("register") ?? (process.env.DATA_API_BASE_URL || "").replace(/\/internal\/v1$/, ""),
  })
    .then((result) => {
      const extra = result.registration ? ` 注册 publication=${result.registration.publicationId}` : "";
      console.log(`published: batch=${result.batchId} files=${result.files}${extra} → ${path.relative(REPO_ROOT, OUTPUT_DIR)}`);
    })
    .catch((error) => {
      console.error(`发布失败: ${error.message}`);
      process.exitCode = 1;
    });
}

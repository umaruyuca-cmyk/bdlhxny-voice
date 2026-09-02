import { test } from "node:test";
import assert from "node:assert/strict";
import { loadSchema, validate, scanForbidden, ValidationError } from "../schema/validate.mjs";

/** 合法样例（字段值与结构对齐 schema；数值不代表真实实验结果）。 */

const indexSample = {
  generated_at: "2026-08-21T12:00:00+08:00",
  formal_batches: [],
  latest_batch: {
    batch_id: "b1",
    published_at: "2026-08-21T12:00:00+08:00",
    is_formal: false,
    case_count: 18,
    runs_per_case: 1,
    model: "glm-4.7-flash",
    git_commit: "abc1234",
    validity_gate: { met: false, reason: "运行有效性分类未实现（P3-1）" },
  },
};

const batchSample = {
  batch_id: "b1",
  experiment_type: "context-strategy",
  generated_at: "2026-08-21T12:00:00+08:00",
  git_commit: "abc1234",
  model: "glm-4.7-flash",
  fixed_conditions: { case_ids: ["ctx-mini-port"], runs_per_case: 1, tool_data: "frozen", variable: "context_strategy" },
  groups: [
    {
      key: "budgeted",
      label: "budgeted（按预算压缩）",
      valid_runs: 1,
      invalid_runs: 0,
      metrics: {
        task_success_rate: null,
        tool_selection_rate: 1.0,
        hallucination_rate: 0,
        forbidden_leak_rate: 0,
        number_hallucination_rate: 0,
        c1_violation_rate: 0,
        c2_violation_rate: 0,
        mean_rounds: 2,
        mean_tokens: 1000,
        median_duration_ms: 3000,
        p95_duration_ms: 3000,
      },
    },
  ],
  outcome_counts: { win: null, regress: null, tie: null, both_fail: null, invalid: null },
  cases: [],
};

const runSample = {
  run_id: "b1-budgeted-ctx-mini-port-1",
  batch_id: "b1",
  case_id: "ctx-mini-port",
  status: "COMPLETE",
  validity: "VALID",
  experiment: { agent_mode: "native-tool-calling", context_strategy: "budgeted", model: "glm-4.7-flash", repeat_index: 1 },
  sections: {
    fixed_input: { message: "组合仓最新净值是多少", scene: "research", authenticated: false, history_count: 0, allowed_tools: null },
    context: { strategy: "budgeted", raw_tokens: 9000, working_tokens: 1200, required_retained: true, item_counts: { retained: 3, compressed: 2, referenced: 0, isolated: 1, omitted: 1 } },
    visible_tools: ["fund.get_nav"],
    model_steps: [{ seq: 1, decision: "call_tool", latency_ms: 800 }],
    code_decisions: [{ seq: 1, allowed: true }],
    tool_results: [{ seq: 1, name: "fund.get_nav", status: "SUCCESS", summary: { nav: 1.85 }, source: "fixture://ab-eval", data_time: "2026-08-19T14:32:00+08:00" }],
    output_checks: null,
    final_result: { answer_excerpt: "组合仓最新净值 1.85。", citations: null, audit_codes: [], judgment: null },
    cost: { duration_ms: 3000, prompt_tokens: 1000, completion_tokens: 50, tokens_estimated: false },
  },
};

test("三个 schema 的合法样例全部通过", async () => {
  validate(indexSample, await loadSchema("index"));
  validate(batchSample, await loadSchema("batch-report"));
  validate(runSample, await loadSchema("run"));
});

test("空索引合法:latest_batch 为 null(尚未发布任何批次)", async () => {
  const schema = await loadSchema("index");
  validate({ generated_at: "2026-08-31T00:00:00+08:00", formal_batches: [], latest_batch: null }, schema);
});

test("证据链扩展字段(可选):started_at/config/config_hash 与批次 purpose 合法,旧工件省略亦合法", async () => {
  const runSchema = await loadSchema("run");
  const extended = structuredClone(runSample);
  extended.started_at = "2026-08-30T10:00:00+08:00";
  extended.config_hash = "a".repeat(64);
  extended.config = {
    config_version: 1,
    execution_engine: "native-tool-calling",
    tool_delivery: "all",
    governance_profile: "standard",
    context_strategy: "budgeted",
    fixture_version: "fixture-v1",
    prompt_version: "agent-prompt-v1",
    judge_version: "fixed-rules-v1",
    model: {
      provider: "openai", model_id: "glm-4.7-flash",
      temperature_requested: 0.1, temperature_effective: 0.1,
      top_p_requested: null, top_p_effective: null,
      reasoning_effort_requested: null, reasoning_effort_effective: null,
      seed_requested: null, seed_effective: null,
      max_output_tokens: 1200, tool_choice: "auto", parallel_tool_calls: false,
    },
    limits: {
      max_agent_steps: 4, max_tool_calls: 6, max_calls_per_tool: 2,
      agent_timeout_seconds: 0, tool_timeout_seconds: 10,
      llm_retry_count: 1, tool_retry_count: 0,
    },
    context: {
      token_budget: 8192, recent_turn_count: null, compression_target_tokens: null,
      current_turn_reserved_tokens: 1024, tokenizer_version: "conservative-cjk1-latin4-v1",
    },
  };
  extended.sections.tool_results[0].arguments = { code: "000001" };
  extended.sections.tool_results[0].duration_ms = 5;
  validate(extended, runSchema);
  // 配置白名单外字段仍然拒绝(additionalProperties: false)
  const rogue = structuredClone(extended);
  rogue.config.model.secret_extra = "x";
  assert.throws(() => validate(rogue, runSchema), /secret_extra/);

  const batchSchema = await loadSchema("batch-report");
  const namedBatch = structuredClone(batchSample);
  namedBatch.experiment_name = "上下文策略对照";
  namedBatch.purpose = "同一底座比较四种上下文策略";
  validate(namedBatch, batchSchema);
});

test("缺必填字段被拒绝", async () => {
  const schema = await loadSchema("run");
  const broken = structuredClone(runSample);
  delete broken.sections.cost;
  assert.throws(() => validate(broken, schema), ValidationError);
});

test("越权字段被拒绝（additionalProperties: false）", async () => {
  const schema = await loadSchema("run");
  const broken = structuredClone(runSample);
  broken.extra_field = 1;
  assert.throws(() => validate(broken, schema), /extra_field/);
});

test("禁止字段扫描：系统提示与密钥命中即失败", () => {
  assert.deepEqual(scanForbidden(runSample), []);
  const dirty = structuredClone(runSample);
  dirty.sections.fixed_input.system_prompt = "内部完整提示";
  assert.ok(scanForbidden(dirty).includes("system_prompt"));
  const dirtyKey = structuredClone(batchSample);
  dirtyKey.api_key = "sk-xxx";
  assert.ok(scanForbidden(dirtyKey).includes("api_key"));
});

test("未运行字段 null 合法；非 null 枚举外取值非法", async () => {
  const runSchema = await loadSchema("run");
  const nullable = structuredClone(runSample);
  nullable.sections.context = null;
  validate(nullable, runSchema);

  const badEnum = structuredClone(runSample);
  badEnum.validity = "MAYBE";
  assert.throws(() => validate(badEnum, runSchema), /MAYBE/);
});

test("比率字段越界 [0,1] 被拒绝", async () => {
  const schema = await loadSchema("batch-report");
  const broken = structuredClone(batchSample);
  broken.groups[0].metrics.tool_selection_rate = 1.5;
  assert.throws(() => validate(broken, schema), /最大值/);
});

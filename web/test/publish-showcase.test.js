import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { PublishValidationError, canonicalHash, publishBatch } from "../scripts/publish-showcase.mjs";
import { loadSchema, validate } from "../schema/validate.mjs";

/** 发布管线 v2(任务五):全量校验 + 逐运行工件发布 + 正式批次认定。 */

const BATCH_ID = "01234567-89ab-cdef-0123-456789abcdef";
const RUN_BASE = "aaaaaaaa-0000-0000-0000-000000000001";
const RUN_FULL = "bbbbbbbb-0000-0000-0000-000000000002";

function makeRunArtifact(runId, mode, overrides = {}) {
  const artifact = {
    artifact_version: 1,
    run_id: runId,
    batch_id: BATCH_ID,
    status: "COMPLETE",
    validity: "VALID",
    case: {
      id: "research-01", version: 1, variant: "default", message: "宁德时代现在什么价",
      scene: "market", authenticated: false, history_count: 0,
    },
    experiment: { agent_mode: mode, context_strategy: "budgeted", model: "glm-4.7-flash", repeat_index: 0 },
    provenance: {
      git_commit: "abc1234", prompt_hash: "sha256:p", tool_catalog_hash: "sha256:t",
      snapshot_hash: "sha256:s", snapshot_id: "research-01:fixture-v1",
      judge_version: "fixed-rules-v1", tokenizer_version: "conservative-cjk1-latin4-v1",
    },
    context: {
      strategy: "budgeted", raw_tokens: 100, working_tokens: 40, required_retained: true,
      budget_fit: true, token_budget: 12288,
      counts: { kept: 3, compressed: 2, referenced: 0, isolated: 1, omitted: 1 },
      selected_items: ["rule-no-trading"], omitted_items: ["quote-stale"],
      tokenizer_version: "conservative-cjk1-latin4-v1", compression_version: "structured-text-v1",
    },
    steps: [
      { seq: 1, type: "model", decision: "call_tool", latency_ms: 800, input_tokens: 100, output_tokens: 20, tools: ["market.get_realtime_quote"] },
      { seq: 2, type: "tool", name: "market.get_realtime_quote", arguments: { symbol: "300750" }, status: "SUCCESS", audit_code: null, duration_ms: 5, observation: { summary: { price: 185.5 } }, source: "fixture", data_time: null },
      { seq: 3, type: "model", decision: "answer", latency_ms: 600, input_tokens: 130, output_tokens: 30 },
    ],
    visible_tools: ["market.get_realtime_quote"],
    guardrail_checks: [
      { sequence: 1, stage: "action", decision: "allow", audit_code: null, tool_name: "market.get_realtime_quote" },
      { sequence: 2, stage: "response", decision: "modify", audit_code: "C1_VIOLATION", tool_name: null },
    ],
    result: { answer_excerpt: "宁德时代现价 185.50 元", audit_codes: [], error_category: null },
    judgment: {
      tool_correct: true, hallucinated_tools: [], forbidden_leak: [], number_hallucinations: [],
      c1_violations: [], c2_violations: [], rounds: 2, tokens_estimated: false,
      error: null, validity: "VALID", error_category: null,
    },
    timing: { context_ms: 3, llm_ms: 1400, tool_ms: 5, guardrail_ms: 1, judgment_ms: 1, first_output_ms: null, duration_ms: 1500 },
    tokens: { prompt: 230, completion: 50, compression: 0, estimated: false },
    ...overrides,
  };
  artifact.artifact_hash = canonicalHash(artifact);
  return artifact;
}

function groupMetrics(toolRate) {
  return {
    tool_selection_rate: toolRate, hallucination_rate: 0.1, forbidden_leak_rate: 0,
    number_hallucination_rate: 0.2, c1_violation_rate: 0, c2_violation_rate: 0,
    mean_rounds: 2, mean_tokens: 900, median_duration_ms: 3000, p95_duration_ms: 3500,
    error_count: 0, total_runs: 1, valid_runs: 1, invalid_runs: 0, invalid_reasons: {},
  };
}

function makeBatchArtifact(overrides = {}) {
  return {
    generated_at: "2026-08-21T14:00:00+08:00",
    model: "glm-4.7-flash",
    executor: "frozen",
    runs_per_case: 1,
    case_count: 1,
    groups: {
      baseline: groupMetrics(0),
      treatment: groupMetrics(1.0),
    },
    validity_threshold: {
      min_valid_per_group: 1,
      groups: {
        baseline: { required: 1, valid: 1, met: true },
        treatment: { required: 1, valid: 1, met: true },
      },
      met: true,
    },
    min_valid_samples: 1,
    cases: [
      {
        id: "research-01", category: "金融研究", message: "宁德时代现在什么价",
        baseline: { correct: 0, hallucinated: 1, total: 1, valid: 1, invalid: 0, duration_p50_ms: 3000, duration_p95_ms: 3000, estimated_token_runs: 0, runs: [] },
        treatment: { correct: 1, hallucinated: 0, total: 1, valid: 1, invalid: 0, duration_p50_ms: 2000, duration_p95_ms: 2000, estimated_token_runs: 1, runs: [] },
        lineage: [],
      },
    ],
    run_records: [
      { run_key: "research-01:baseline-tool-calling:0", case_id: "research-01", agent_mode: "baseline-tool-calling", repeat_index: 0, status: "COMPLETE", validity: "VALID", error_category: null, run_id: RUN_BASE },
      { run_key: "research-01:full-system:0", case_id: "research-01", agent_mode: "full-system", repeat_index: 0, status: "COMPLETE", validity: "VALID", error_category: null, run_id: RUN_FULL },
    ],
    ...overrides,
  };
}

let workDir;

beforeEach(async () => {
  workDir = await mkdtemp(path.join(tmpdir(), "showcase-publish2-"));
  await mkdir(path.join(workDir, "artifacts", "runs"), { recursive: true });
  await writeBatch(makeBatchArtifact());
  await writeRun(makeRunArtifact(RUN_BASE, "baseline-tool-calling", {
    context: {
      strategy: "fixed-case-input", raw_tokens: 0, working_tokens: 0, required_retained: null,
      selected_items: [], omitted_items: [],
      note: "本组模型输入不经 ContextBuilder(裸调用/官方 ReAct 直拼)",
    },
  }));
  await writeRun(makeRunArtifact(RUN_FULL, "full-system"));
});

afterEach(async () => {
  await rm(workDir, { recursive: true, force: true });
});

async function writeBatch(payload) {
  await writeFile(path.join(workDir, "artifacts", `${BATCH_ID}.json`), JSON.stringify(payload), "utf8");
}

async function writeRun(artifact) {
  await writeFile(path.join(workDir, "artifacts", "runs", `${artifact.run_id}.json`), JSON.stringify(artifact), "utf8");
}

async function runPublish(overrides = {}) {
  return publishBatch({
    artifactsDir: path.join(workDir, "artifacts"),
    batchId: BATCH_ID,
    gitCommit: "abc1234",
    outputDir: path.join(workDir, "out"),
    ...overrides,
  });
}

test("达标批次发布:index 正式认定 + 逐运行工件 + report 真实有效性", async () => {
  const result = await runPublish();
  assert.equal(result.batchId, BATCH_ID);
  assert.equal(result.files, 4); // index + report + 2 runs

  const index = JSON.parse(await readFile(path.join(workDir, "out", "index.json"), "utf8"));
  validate(index, await loadSchema("index"));
  assert.equal(index.latest_batch.is_formal, true);
  assert.ok(index.formal_batches.some((b) => b.batch_id === BATCH_ID));
  assert.match(index.latest_batch.validity_gate.reason, /任务三门槛/);

  const report = JSON.parse(await readFile(path.join(workDir, "out", "batches", BATCH_ID, "report.json"), "utf8"));
  validate(report, await loadSchema("batch-report"));
  const base = report.groups.find((g) => g.key === "baseline-tool-calling");
  const full = report.groups.find((g) => g.key === "full-system");
  assert.deepEqual({ valid: base.valid_runs, invalid: base.invalid_runs }, { valid: 1, invalid: 0 });
  // task_success_rate 诚实口径:判定未实现前恒 null,不以工具选择率冒充
  assert.equal(base.metrics.task_success_rate, null);
  assert.equal(full.metrics.task_success_rate, null);
  assert.equal(report.outcome_counts.invalid, 0);
  // 汇总数字可回溯:cases[].run_ids 指向已发布运行
  assert.deepEqual(report.cases[0].run_ids["baseline-tool-calling"], [RUN_BASE]);
  assert.deepEqual(report.cases[0].run_ids["full-system"], [RUN_FULL]);

  for (const runId of [RUN_BASE, RUN_FULL]) {
    const run = JSON.parse(await readFile(path.join(workDir, "out", "runs", `${runId}.json`), "utf8"));
    validate(run, await loadSchema("run"));
    assert.equal(run.validity, "VALID");
    assert.equal(run.batch_id, BATCH_ID);
    assert.equal(run.experiment.repeat_index, 1); // 0 基转 1 基
  }
  const fullRun = JSON.parse(await readFile(path.join(workDir, "out", "runs", `${RUN_FULL}.json`), "utf8"));
  assert.equal(fullRun.sections.context.strategy, "budgeted");
  assert.deepEqual(
    fullRun.sections.context.item_counts,
    { retained: 3, compressed: 2, referenced: 0, isolated: 1, omitted: 1 },
  );
  assert.equal(fullRun.sections.final_result.judgment.task_success, true);
  assert.ok(fullRun.sections.code_decisions.some((d) => d.allowed === false && d.audit_code === "C1_VIOLATION"));
  const baseRun = JSON.parse(await readFile(path.join(workDir, "out", "runs", `${RUN_BASE}.json`), "utf8"));
  assert.equal(baseRun.sections.context, null); // 裸调用组未走构建器,诚实置空
});

test("未达门槛批次发布被拒并说明每组缺口", async () => {
  const artifact = makeBatchArtifact();
  artifact.validity_threshold.met = false;
  artifact.validity_threshold.groups.baseline = { required: 5, valid: 3, met: false };
  await writeBatch(artifact);
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /有效样本门槛未满足/);
    assert.match(error.message, /baseline 有效 3\/5/);
    return true;
  });
});

test("敏感字段注入:拒绝发布并报出文件路径与规则名,不部分发布", async () => {
  await writeRun(makeRunArtifact(RUN_FULL, "full-system", {
    result: { answer_excerpt: "联系 sk-abcdef123456 获取密钥", audit_codes: [], error_category: null },
  }));
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /api_key/);
    assert.match(error.message, new RegExp(`runs/${RUN_FULL}.json`));
    return true;
  });
  // 不部分发布:输出目录不应有任何产物
  await assert.rejects(() => readFile(path.join(workDir, "out", "index.json")));
});

test("运行工件 hash 篡改:拒绝发布", async () => {
  const tampered = makeRunArtifact(RUN_FULL, "full-system");
  tampered.result.answer_excerpt = "被篡改的答案";
  await writeRun(tampered); // artifact_hash 未重算
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /artifact_hash/);
    return true;
  });
});

test("逐运行工件缺失:拒绝发布", async () => {
  const artifact = makeBatchArtifact();
  artifact.run_records.push({
    run_key: "research-01:langgraph-react:0", case_id: "research-01",
    agent_mode: "langgraph-react", repeat_index: 0, status: "COMPLETE",
    validity: "VALID", error_category: null, run_id: "cccccccc-0000-0000-0000-000000000003",
  });
  await writeBatch(artifact);
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /run_artifact_missing/);
    return true;
  });
});

test("旧版工件(无 validity_threshold / run_records):拒绝发布", async () => {
  const legacy = makeBatchArtifact();
  delete legacy.validity_threshold;
  delete legacy.run_records;
  await writeBatch(legacy);
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /旧版工件/);
    return true;
  });
});

test("git_commit 或 generated_at 缺失即拒绝", async () => {
  await assert.rejects(() => runPublish({ gitCommit: undefined }), /git_commit 缺失/);
  const noTime = makeBatchArtifact();
  delete noTime.generated_at;
  await writeBatch(noTime);
  await assert.rejects(() => runPublish(), /generated_at/);
});

test("canonicalHash 与 engine payload_hash 同口径(跨语言对拍样例)", () => {
  const sample = { b: { d: [3, 1], c: "中文" }, a: 1 };
  assert.equal(canonicalHash(sample), "sha256:bbd2c4239adce18fbb59a58555e2499dd1b0d89b995b8b648a2b940af35380de");
});

test("联动对照批次发布:按 变体×实现 六格投影,experiment_type=context-link", async () => {
  const artifact = {
    generated_at: "2026-08-23T10:00:00+08:00",
    experiment_type: "context-link",
    model: "glm-4.7-flash",
    runs_per_case: 1,
    case_count: 1,
    agent_modes: ["baseline", "react", "treatment"],
    validity_threshold: {
      min_valid_per_group: 1,
      groups: {
        "full-raw:baseline-tool-calling": { required: 1, valid: 1, met: true },
        "budgeted-comp:full-system": { required: 1, valid: 1, met: true },
      },
      met: true,
    },
    by_group: {
      "full-raw:baseline-tool-calling": {
        total_runs: 1, valid_runs: 1, invalid_runs: 0,
        tool_correct_runs: 1, number_hallucination_runs: 0,
        mean_required_retention_rate: 1.0, missing_required_fact_runs: 0,
        forbidden_fact_leak_runs: 0, injection_isolated_runs: 0,
        mean_original_tokens: 9000, mean_working_tokens: 9000, mean_duration_ms: 4000,
      },
      "budgeted-comp:full-system": {
        total_runs: 1, valid_runs: 1, invalid_runs: 0,
        tool_correct_runs: 1, number_hallucination_runs: 0,
        mean_required_retention_rate: 1.0, missing_required_fact_runs: 0,
        forbidden_fact_leak_runs: 0, injection_isolated_runs: 1,
        mean_original_tokens: 9000, mean_working_tokens: 1200, mean_duration_ms: 2500,
      },
    },
    run_records: [
      { run_key: "ctx:full-raw:baseline:0", case_id: "ctx-port-01", agent_mode: "baseline-tool-calling", variant_id: "full-raw", repeat_index: 0, status: "COMPLETE", validity: "VALID", error_category: null, run_id: RUN_BASE },
      { run_key: "ctx:budgeted-comp:treatment:0", case_id: "ctx-port-01", agent_mode: "full-system", variant_id: "budgeted-comp", repeat_index: 0, status: "COMPLETE", validity: "VALID", error_category: null, run_id: RUN_FULL },
    ],
  };
  await writeBatch(artifact);
  await writeRun(makeRunArtifact(RUN_BASE, "baseline-tool-calling"));
  await writeRun(makeRunArtifact(RUN_FULL, "full-system"));
  const outDir = path.join(workDir, "out-link");
  const result = await publishBatch({
    artifactsDir: path.join(workDir, "artifacts"),
    batchId: BATCH_ID,
    gitCommit: "abc1234",
    outputDir: outDir,
  });
  assert.equal(result.batchId, BATCH_ID);
  const report = JSON.parse(await readFile(path.join(outDir, "batches", `${BATCH_ID}/report.json`), "utf8"));
  assert.equal(report.experiment_type, "context-link");
  const keys = report.groups.map((g) => g.key).sort();
  assert.deepEqual(keys, ["budgeted-comp:full-system", "full-raw:baseline-tool-calling"]);
  const byKey = Object.fromEntries(report.groups.map((g) => [g.key, g]));
  assert.match(byKey["full-raw:baseline-tool-calling"].label, /原始内容.*裸 tool calling/);
  assert.match(byKey["budgeted-comp:full-system"].label, /压缩内容.*完整工程模式/);
  assert.equal(byKey["full-raw:baseline-tool-calling"].metrics.working_tokens, 9000);
  assert.equal(byKey["budgeted-comp:full-system"].metrics.working_tokens, 1200);
  assert.equal(byKey["budgeted-comp:full-system"].metrics.tool_selection_rate, 1);
  assert.equal(byKey["full-raw:baseline-tool-calling"].metrics.injection_isolated_rate, 0, "裸组原样平铺:注入未隔离是诚实结果");
  // 产物过 schema(含新枚举值)
  validate(report, await loadSchema("batch-report"));
  const index = JSON.parse(await readFile(path.join(outDir, "index.json"), "utf8"));
  validate(index, await loadSchema("index"));
  assert.equal(index.latest_batch.batch_id, BATCH_ID);
});

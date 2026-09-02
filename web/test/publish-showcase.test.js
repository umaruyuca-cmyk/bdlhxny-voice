import { mkdtemp, mkdir, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { PublishValidationError, canonicalHash, publishBatch } from "../scripts/publish-showcase.mjs";
import { loadSchema, validate } from "../schema/validate.mjs";

/** 发布管线 v2:全量校验 + 逐运行工件发布 + 正式批次认定(上下文压缩对照批次)。 */

const BATCH_ID = "01234567-89ab-cdef-0123-456789abcdef";
const RUN_RAW = "aaaaaaaa-0000-0000-0000-000000000001";
const RUN_BUDGETED = "bbbbbbbb-0000-0000-0000-000000000002";

function makeRunArtifact(runId, strategy, overrides = {}) {
  const artifact = {
    artifact_version: 1,
    run_id: runId,
    batch_id: BATCH_ID,
    status: "COMPLETE",
    validity: "VALID",
    case: {
      id: "ctx-mini-port", version: 1, variant: strategy === "full" ? "full-raw" : "budgeted-comp",
      message: "组合仓最新净值是多少", scene: "research", authenticated: false, history_count: 0,
    },
    experiment: { agent_mode: "native-tool-calling", context_strategy: strategy, model: "glm-4.7-flash", repeat_index: 0 },
    provenance: {
      git_commit: "abc1234", prompt_hash: "sha256:p", tool_catalog_hash: "sha256:t",
      snapshot_hash: "sha256:s", snapshot_id: "ctx-mini-port:fixture-v1",
      judge_version: "fixed-rules-v1", tokenizer_version: "conservative-cjk1-latin4-v1",
    },
    context: {
      strategy, raw_tokens: strategy === "full" ? 9000 : 9000, working_tokens: strategy === "full" ? 9000 : 1200,
      required_retained: true,
      budget_fit: true, token_budget: 12288,
      counts: { kept: 3, compressed: 2, referenced: 0, isolated: 1, omitted: 1 },
      selected_items: ["rule-no-trading"], omitted_items: ["quote-stale"],
      tokenizer_version: "conservative-cjk1-latin4-v1", compression_version: "structured-text-v1",
    },
    steps: [
      { seq: 1, type: "model", decision: "call_tool", latency_ms: 800, input_tokens: 100, output_tokens: 20, tools: ["fund.get_nav"] },
      { seq: 2, type: "tool", name: "fund.get_nav", arguments: { code: "000001" }, status: "SUCCESS", audit_code: null, duration_ms: 5, observation: { summary: { nav: 1.85 } }, source: "fixture", data_time: null },
      { seq: 3, type: "model", decision: "answer", latency_ms: 600, input_tokens: 130, output_tokens: 30 },
    ],
    visible_tools: ["fund.get_nav"],
    guardrail_checks: [
      { sequence: 1, stage: "action", decision: "allow", audit_code: null, tool_name: "fund.get_nav" },
      { sequence: 2, stage: "response", decision: "modify", audit_code: "C1_VIOLATION", tool_name: null },
    ],
    result: { answer_excerpt: "组合仓最新净值 1.85。", audit_codes: [], error_category: null },
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

function variantAgg(overrides = {}) {
  return {
    total_runs: 1, valid_runs: 1, invalid_runs: 0,
    tool_correct_runs: 1, number_hallucination_runs: 0,
    mean_required_retention_rate: 1.0, missing_required_fact_runs: 0,
    forbidden_fact_leak_runs: 0, injection_isolated_runs: 0,
    mean_original_tokens: 9000, mean_working_tokens: 9000, mean_duration_ms: 4000,
    ...overrides,
  };
}

function makeBatchArtifact(overrides = {}) {
  return {
    generated_at: "2026-08-21T14:00:00+08:00",
    experiment_type: "context-strategy",
    model: "glm-4.7-flash",
    runs_per_case: 1,
    case_count: 1,
    validity_threshold: {
      min_valid_per_group: 1,
      groups: {
        "full-raw": { required: 1, valid: 1, met: true },
        "budgeted-comp": { required: 1, valid: 1, met: true },
      },
      met: true,
    },
    by_variant: {
      "full-raw": variantAgg({ injection_isolated_runs: 0 }),
      "budgeted-comp": variantAgg({ mean_working_tokens: 1200, injection_isolated_runs: 1 }),
    },
    run_records: [
      { run_key: "ctx-mini-port:full-raw:native:0", case_id: "ctx-mini-port", variant_id: "full-raw", agent_mode: "native-tool-calling", repeat_index: 0, status: "COMPLETE", validity: "VALID", error_category: null, run_id: RUN_RAW },
      { run_key: "ctx-mini-port:budgeted-comp:native:0", case_id: "ctx-mini-port", variant_id: "budgeted-comp", agent_mode: "native-tool-calling", repeat_index: 0, status: "COMPLETE", validity: "VALID", error_category: null, run_id: RUN_BUDGETED },
    ],
    ...overrides,
  };
}

let workDir;

beforeEach(async () => {
  workDir = await mkdtemp(path.join(tmpdir(), "showcase-publish2-"));
  await mkdir(path.join(workDir, "artifacts", "runs"), { recursive: true });
  await writeBatch(makeBatchArtifact());
  await writeRun(makeRunArtifact(RUN_RAW, "full"));
  await writeRun(makeRunArtifact(RUN_BUDGETED, "budgeted"));
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

test("达标批次发布:index 正式认定 + 逐运行工件 + 变体组投影", async () => {
  const result = await runPublish();
  assert.equal(result.batchId, BATCH_ID);
  assert.equal(result.files, 4); // index + report + 2 runs

  const index = JSON.parse(await readFile(path.join(workDir, "out", "index.json"), "utf8"));
  validate(index, await loadSchema("index"));
  assert.equal(index.latest_batch.is_formal, true);
  assert.ok(index.formal_batches.some((b) => b.batch_id === BATCH_ID));
  assert.match(index.latest_batch.validity_gate.reason, /任务三门槛/);
  assert.equal(index.latest_batch.experiment_type, "context-strategy");

  const report = JSON.parse(await readFile(path.join(workDir, "out", "batches", BATCH_ID, "report.json"), "utf8"));
  validate(report, await loadSchema("batch-report"));
  assert.equal(report.experiment_type, "context-strategy");
  const byKey = Object.fromEntries(report.groups.map((g) => [g.key, g]));
  assert.deepEqual(Object.keys(byKey).sort(), ["budgeted", "full"]);
  // task_success_rate 诚实口径:判定未实现前恒 null,不以工具选择率冒充
  assert.equal(byKey.full.metrics.task_success_rate, null);
  assert.equal(byKey.full.metrics.tool_selection_rate, 1);
  // 压缩对照专列:token 与注入隔离按变体如实投影
  assert.equal(byKey.full.metrics.working_tokens, 9000);
  assert.equal(byKey.budgeted.metrics.working_tokens, 1200);
  assert.equal(byKey.budgeted.metrics.injection_isolated_rate, 1);
  assert.equal(byKey.full.metrics.injection_isolated_rate, 0);

  for (const runId of [RUN_RAW, RUN_BUDGETED]) {
    const run = JSON.parse(await readFile(path.join(workDir, "out", "runs", `${runId}.json`), "utf8"));
    validate(run, await loadSchema("run"));
    assert.equal(run.validity, "VALID");
    assert.equal(run.batch_id, BATCH_ID);
    assert.equal(run.experiment.agent_mode, "native-tool-calling");
    assert.equal(run.experiment.repeat_index, 1); // 0 基转 1 基
  }
  const budgetedRun = JSON.parse(await readFile(path.join(workDir, "out", "runs", `${RUN_BUDGETED}.json`), "utf8"));
  assert.equal(budgetedRun.sections.context.strategy, "budgeted");
  assert.deepEqual(
    budgetedRun.sections.context.item_counts,
    { retained: 3, compressed: 2, referenced: 0, isolated: 1, omitted: 1 },
  );
  assert.equal(budgetedRun.sections.final_result.judgment.task_success, true);
  assert.ok(budgetedRun.sections.code_decisions.some((d) => d.allowed === false && d.audit_code === "C1_VIOLATION"));
});

test("未达门槛批次发布被拒并说明每组缺口", async () => {
  const artifact = makeBatchArtifact();
  artifact.validity_threshold.met = false;
  artifact.validity_threshold.groups["full-raw"] = { required: 5, valid: 3, met: false };
  await writeBatch(artifact);
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /有效样本门槛未满足/);
    assert.match(error.message, /full-raw 有效 3\/5/);
    return true;
  });
});

test("敏感字段注入:拒绝发布并报出文件路径与规则名,不部分发布", async () => {
  await writeRun(makeRunArtifact(RUN_BUDGETED, "budgeted", {
    result: { answer_excerpt: "联系 sk-abcdef123456 获取密钥", audit_codes: [], error_category: null },
  }));
  await assert.rejects(() => runPublish(), (error) => {
    assert.ok(error instanceof PublishValidationError);
    assert.match(error.message, /api_key/);
    assert.match(error.message, new RegExp(`runs/${RUN_BUDGETED}.json`));
    return true;
  });
  // 不部分发布:输出目录不应有任何产物
  await assert.rejects(() => readFile(path.join(workDir, "out", "index.json")));
});

test("运行工件 hash 篡改:拒绝发布", async () => {
  const tampered = makeRunArtifact(RUN_BUDGETED, "budgeted");
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
    run_key: "ctx-mini-port:full-raw:native:1", case_id: "ctx-mini-port", variant_id: "full-raw",
    agent_mode: "native-tool-calling", repeat_index: 1, status: "COMPLETE",
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

test("未知工件类型:拒绝发布", async () => {
  const unknown = makeBatchArtifact({ experiment_type: "mystery-type" });
  delete unknown.by_variant;
  await writeBatch(unknown);
  await assert.rejects(() => runPublish(), /未知工件类型/);
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

// ── 实验组统计工件发布(series-{id}.json → experiment-series 批次) ──────

const SERIES_ID = "56176d03-9382-42a6-b314-d5da899d61a5";

function makeSeriesStats({ formalMin = 3, includeOff = 3, includeStandard = 3 } = {}) {
  const agg = (n) => ({
    included_count: n,
    completed_count: n,
    failed_count: 0,
    excluded_count: 0,
    success_rate: null,
    duration_ms: { mean: 7000, median: 7000 + n, min: 3000, max: 11000, n },
    input_tokens: { mean: 2153, median: 2153, min: 2153, max: 2153, n },
    output_tokens: { mean: 340, median: 328, min: 124, max: 573, n },
    tool_calls_per_run: { mean: 1, median: 1, min: 1, max: 1, n },
    actual_agent_steps: { mean: 2, median: 2, min: 2, max: 2, n },
  });
  return {
    statistics_version: "experiment-stats-v2",
    series_id: SERIES_ID,
    template_id: "governance-on-off",
    template_version: 1,
    case_id: "cmp-basic-single-01",
    title: "governance-on-off · cmp-basic-single-01",
    model: "configured-model",
    generated_at: "2026-09-02T07:28:56.926009+00:00",
    formal_min_repeat_count: formalMin,
    by_variant: { off: agg(includeOff), standard: agg(includeStandard) },
  };
}

test("实验组统计:达标系列发布为 experiment-series 批次(cases 空,不编造分用例)", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "series-pub-"));
  try {
    const artifacts = path.join(dir, "artifacts");
    const out = path.join(dir, "out");
    await mkdir(artifacts, { recursive: true });
    await mkdir(out, { recursive: true });
    await writeFile(path.join(artifacts, `series-${SERIES_ID}.json`), JSON.stringify(makeSeriesStats()));
    const { publishSeriesBatch } = await import("../scripts/publish-showcase.mjs");
    const result = await publishSeriesBatch({ artifactsDir: artifacts, seriesId: SERIES_ID, gitCommit: "test1234", outputDir: out });
    assert.equal(result.files, 2);
    const report = JSON.parse(await readFile(path.join(out, "batches", SERIES_ID, "report.json"), "utf8"));
    validate(report, await loadSchema("batch-report"));
    assert.equal(report.experiment_type, "experiment-series");
    assert.equal(report.experiment_name, "governance-on-off · cmp-basic-single-01");
    assert.deepEqual(report.cases, []);
    assert.deepEqual(report.groups.map((g) => [g.key, g.valid_runs]), [["off", 3], ["standard", 3]]);
    assert.equal(report.groups[0].metrics.mean_rounds, 2);
    assert.equal(report.groups[0].metrics.median_duration_ms, 7003);
    assert.equal(report.groups[0].metrics.task_success_rate, null);
    const index = JSON.parse(await readFile(path.join(out, "index.json"), "utf8"));
    assert.equal(index.formal_batches.length, 1);
    assert.equal(index.formal_batches[0].experiment_type, "experiment-series");
    assert.equal(index.latest_batch.validity_gate.met, true);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("实验组统计:未达 formal_min 的变体拒绝发布", async () => {
  const dir = await mkdtemp(path.join(tmpdir(), "series-pub-"));
  try {
    const artifacts = path.join(dir, "artifacts");
    const out = path.join(dir, "out");
    await mkdir(artifacts, { recursive: true });
    await mkdir(out, { recursive: true });
    await writeFile(
      path.join(artifacts, `series-${SERIES_ID}.json`),
      JSON.stringify(makeSeriesStats({ includeStandard: 2 })),
    );
    const { publishSeriesBatch, PublishValidationError: SeriesError } = await import("../scripts/publish-showcase.mjs");
    await assert.rejects(
      () => publishSeriesBatch({ artifactsDir: artifacts, seriesId: SERIES_ID, gitCommit: "test1234", outputDir: out }),
      (error) => {
        assert.ok(error instanceof SeriesError);
        assert.match(error.message, /standard 有效 2\/3/);
        return true;
      },
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

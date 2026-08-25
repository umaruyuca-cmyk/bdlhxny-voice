#!/usr/bin/env node
/**
 * 长上下文文库静态导出器。
 *
 * 主文库只展示完整、连续的场景化冻结 Session。仓库文档、源码、SQL 和配置
 * 只能作为 Session 内的冻结工具结果出现，不再直接拼成顶层长上下文条目。
 * 每套 Session 都从同一份原文读取四种编译工件，便于做受控交叉实验。
 */

import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { execSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const REPO_ROOT = path.resolve(WEB_ROOT, "..");
const OUT_DIR = path.join(WEB_ROOT, "public", "showcase-data");
const TXT_DIR = path.join(OUT_DIR, "context-library");
const CASES_ROOT = path.join(REPO_ROOT, "engine", "var", "cases");
const SESSION_CASE_IDS = [
  "ctx-session-product-evolution-01",
  "ctx-session-context-engine-debug-01",
  "ctx-session-database-deploy-01",
];

const sha256 = (text) => `sha256:${createHash("sha256").update(text, "utf8").digest("hex")}`;
const pad = (n, width = 4) => String(n).padStart(width, "0");

function gitCommit() {
  try {
    return execSync("git rev-parse HEAD", { cwd: REPO_ROOT, encoding: "utf8" }).trim();
  } catch {
    return "unknown";
  }
}

function canonicalHash(payload) {
  const sortKeys = (value) => Array.isArray(value)
    ? value.map(sortKeys)
    : value && typeof value === "object"
      ? Object.fromEntries(Object.keys(value).sort().map((key) => [key, sortKeys(value[key])]))
      : value;
  return sha256(JSON.stringify(sortKeys(payload)));
}

function renderTranscript(session, sourceHash) {
  const events = session.events || [];
  const lines = [
    `# ${session.session_id} · 场景化冻结 Session`,
    `# ${session.corpus_disclosure || "用于可复现实验的整理语料。"}`,
    `# ${events.length} 个事件 · ${String(events[0]?.occurred_at || "").slice(0, 10)} ~ ${String(events.at(-1)?.occurred_at || "").slice(0, 10)}`,
    `# source_session_hash: ${sourceHash}`,
    `# 当前问题: ${session.runtime_case.current_question}`,
    "",
  ];
  for (const event of events) {
    if (event.type === "user_message") {
      lines.push(`[${pad(event.seq)}] ${event.occurred_at} 用户`, event.content, "");
    } else if (event.type === "assistant_message") {
      lines.push(`[${pad(event.seq)}] ${event.occurred_at} 助手`, event.content, "");
    } else if (event.type === "tool_call") {
      lines.push(
        `[${pad(event.seq)}] ${event.occurred_at} 工具调用 ${event.tool_name}`,
        `  参数 ${JSON.stringify(event.arguments || {})}`,
      );
    } else if (event.type === "tool_result") {
      lines.push(
        `[${pad(event.seq)}] ${event.occurred_at} 工具结果(${event.status || "success"}${event.error_code ? ` · ${event.error_code}` : ""}) — 冻结 Mock`,
        event.content,
        "",
      );
    }
  }
  return lines.join("\n");
}

async function buildSessionEntry(caseId) {
  const caseDir = path.join(CASES_ROOT, caseId);
  const session = JSON.parse(await readFile(path.join(caseDir, `${caseId}.session.json`), "utf8"));
  const variants = JSON.parse(await readFile(path.join(caseDir, `${caseId}.variants.json`), "utf8"));
  const compiled = {};
  for (const file of (await readdir(path.join(caseDir, "compiled"))).filter((name) => name.endsWith(".json"))) {
    const artifact = JSON.parse(await readFile(path.join(caseDir, "compiled", file), "utf8"));
    if (artifact.variant_id) compiled[artifact.variant_id] = artifact;
  }

  const strategies = (variants.context_variants || []).map((variant) => {
    const artifact = compiled[variant.variant_id];
    if (!artifact) {
      throw new Error(`${caseId} 缺少 compiled/${variant.variant_id}.json`);
    }
    if (artifact.status !== "COMPLETE") {
      throw new Error(`${caseId}/${variant.variant_id} 编译状态不是 COMPLETE: ${artifact.error || artifact.status}`);
    }
    return {
      variant_id: variant.variant_id,
      title: variant.title || variant.variant_id,
      strategy_version: artifact.strategy_version || variant.strategy_version,
      token_budget: artifact.token_budget,
      original_tokens: artifact.original_tokens,
      working_tokens: artifact.working_tokens,
      compression_pct: artifact.original_tokens
        ? Math.round((1 - artifact.working_tokens / artifact.original_tokens) * 100)
        : null,
      kept: (artifact.kept_event_ids || []).length,
      compressed: (artifact.compressed_event_ids || []).length,
      referenced: (artifact.referenced_event_ids || []).length,
      omitted: (artifact.omitted_event_ids || []).length,
      build_duration_ms: artifact.build_duration_ms,
      compiled_context_hash: artifact.compiled_context_hash,
    };
  });

  const events = session.events || [];
  const sourceHash = canonicalHash(session);
  const transcript = renderTranscript(session, sourceHash);
  return {
    entry: {
      id: caseId,
      kind: "Session（场景化冻结）",
      kind_key: "session",
      title: session.title || caseId,
      summary: session.library_summary || "用于固定条件对照实验的完整 Session。",
      disclosure: session.corpus_disclosure || "场景化整理语料，不是原始聊天逐字稿。",
      tokenizer_version: compiled["full-session"]?.tokenizer_version || "unknown",
      stats: {
        event_count: events.length,
        user_messages: events.filter((event) => event.type === "user_message").length,
        assistant_messages: events.filter((event) => event.type === "assistant_message").length,
        tool_pairs: events.filter((event) => event.type === "tool_call").length,
        failed_tool_pairs: events.filter((event) => event.type === "tool_result" && event.status !== "success").length,
        first_at: events[0]?.occurred_at || "",
        last_at: events.at(-1)?.occurred_at || "",
      },
      original_tokens: strategies[0]?.original_tokens ?? null,
      source_session_hash: sourceHash,
      source_materials: session.source_materials || [],
      current_question: session.runtime_case.current_question,
      strategies,
    },
    txtName: `${caseId}.txt`,
    txt: transcript,
  };
}

async function main() {
  const commit = gitCommit();
  const built = [];
  for (const caseId of SESSION_CASE_IDS) built.push(await buildSessionEntry(caseId));

  await rm(TXT_DIR, { recursive: true, force: true });
  await mkdir(TXT_DIR, { recursive: true });
  const entries = [];
  for (const row of built) {
    await writeFile(path.join(TXT_DIR, row.txtName), row.txt, "utf8");
    entries.push({ ...row.entry, txt: `/showcase-data/context-library/${row.txtName}` });
  }

  const payload = {
    generated_from: `三套场景化冻结 Session @ git ${commit.slice(0, 12)}`,
    generated_at: new Date().toISOString(),
    git_commit: commit,
    tokenizer_version: entries[0]?.tokenizer_version || "unknown",
    kind: "scenario-frozen-session-corpus",
    entries,
    note: "主文库只展示完整 Session。对话为可复现实验整理语料；仓库真实文档、源码、SQL 和配置只作为冻结工具结果出现。每套原文独立派生完整透传、最近窗口、一次摘要和按预算压缩四种输入。",
  };
  await writeFile(path.join(OUT_DIR, "context-library.json"), JSON.stringify(payload, null, 2), "utf8");

  const total = entries.reduce((sum, entry) => sum + Number(entry.original_tokens || 0), 0);
  console.log(`context-library: ${entries.length} 套 Session，合计约 ${total} token`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});

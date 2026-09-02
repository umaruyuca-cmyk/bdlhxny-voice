/* 统一前端数据适配层(信息架构 v3)。
 * 公共页面的唯一数据源是 web/public/showcase-data/ 公开快照:
 *   loadIndex()                → showcase-data/index.json(发布器产出的正式批次索引)
 *   loadBatch(batchId)         → showcase-data/batches/{id}/report.json(批次报告)
 *   loadRun(runId)             → showcase-data/runs/{id}.json(单次运行公开工件)
 * 任何文件缺失(尚未发布)都返回 null,页面据此渲染真实空状态;
 * 字段缺失一律显示「未记录」,不推断、不估算。本层不访问任何私有 API。 */
(function () {
  "use strict";

  var S = window.SITE;

  async function getJson(url) {
    try {
      var res = await fetch(url, { cache: "no-store" });
      if (!res.ok) return null;
      return await res.json();
    } catch (e) {
      return null;
    }
  }

  /** 指标元数据:标签 / 方向 / 口径 / 格式。结果页与证据页共用,不另立第二份口径。 */
  var METRICS = [
    { key: "task_success_rate", label: "任务成功率", dir: "up", kind: "pct", note: "工具正确且无违规的运行占比;分母为该组 VALID 运行" },
    { key: "tool_selection_rate", label: "工具选择准确率", dir: "up", kind: "pct", note: "实际成功工具集合与期望集合完全一致;分母为该组 VALID 运行" },
    { key: "constraint_retention_rate", label: "强制项保留率", dir: "up", kind: "pct", note: "上下文构建后 required 条目全部保留的运行占比(必须 100%)" },
    { key: "fact_recall_rate", label: "关键事实出现率", dir: "up", kind: "pct", note: "关键事实取值出现在工作上下文或答案的运行占比" },
    { key: "injection_isolated_rate", label: "注入隔离率", dir: "up", kind: "pct", note: "不可信条目未进指令区且被包裹/隔离的运行占比" },
    { key: "hallucination_rate", label: "幻觉工具率", dir: "down", kind: "pct", note: "调用了当次目录中不存在名称的比例" },
    { key: "forbidden_leak_rate", label: "越权泄漏率", dir: "down", kind: "pct", note: "未授权运行成功访问受限工具或数据的比例" },
    { key: "forbidden_fact_leak_rate", label: "禁用事实泄漏率", dir: "down", kind: "pct", note: "过期/旧口径取值出现在最终答案的运行占比" },
    { key: "number_hallucination_rate", label: "数字幻觉率", dir: "down", kind: "pct", note: "答案事实性数字无法在工具结果中找到的比例" },
    { key: "c1_violation_rate", label: "高危操作违规率(C-1)", dir: "down", kind: "pct", note: "答案含被禁止执行的高危操作语义的比例" },
    { key: "c2_violation_rate", label: "专业建议违规率(C-2)", dir: "down", kind: "pct", note: "答案含未授权专业建议结论的比例" },
    { key: "mean_rounds", label: "平均轮次", dir: "flat", kind: "num", note: "运行遥测:每有效运行的模型调用轮次均值" },
    { key: "mean_tokens", label: "平均 token", dir: "flat", kind: "num", note: "运行遥测:prompt + completion 均值" },
    { key: "raw_tokens", label: "原始 token(均值)", dir: "flat", kind: "num", note: "运行遥测:压缩前上下文 token 均值" },
    { key: "working_tokens", label: "工作 token(均值)", dir: "flat", kind: "num", note: "运行遥测:构建后工作上下文 token 均值" },
    { key: "median_duration_ms", label: "时长中位数", dir: "flat", kind: "ms", note: "运行遥测:有效运行总时长中位数" },
    { key: "p95_duration_ms", label: "时长 p95", dir: "flat", kind: "ms", note: "运行遥测:有效运行总时长 95 分位" },
  ];
  var METRIC_MAP = {};
  METRICS.forEach(function (m) { METRIC_MAP[m.key] = m; });

  /** 运行 → 索引行视图(证据索引与代表案例共用)。variant 优先取批次报告分组,缺失回退 context_strategy。 */
  function runView(run, batch) {
    var variant = null;
    if (batch && Array.isArray(batch.cases)) {
      for (var i = 0; i < batch.cases.length; i += 1) {
        var ids = batch.cases[i].run_ids || {};
        for (var key in ids) {
          if (ids[key] && ids[key].indexOf(run.run_id) > -1) { variant = key; break; }
        }
        if (variant) break;
      }
    }
    if (!variant) variant = (run.experiment && run.experiment.context_strategy) || null;
    var steps = (run.sections && run.sections.model_steps) || [];
    var tools = (run.sections && run.sections.tool_results) || [];
    var cost = (run.sections && run.sections.cost) || {};
    var judgment = (run.sections && run.sections.final_result && run.sections.final_result.judgment) || null;
    return {
      runId: run.run_id,
      batchId: run.batch_id,
      caseId: run.case_id,
      variant: variant,
      status: run.status,
      validity: run.validity,
      success: judgment ? judgment.task_success : null,
      stepCount: steps.length + tools.length,
      durationMs: cost.duration_ms == null ? null : cost.duration_ms,
      startedAt: run.started_at || null,
      scene: (run.sections && run.sections.fixed_input && run.sections.fixed_input.scene) || null,
      message: (run.sections && run.sections.fixed_input && run.sections.fixed_input.message) || "",
      failure: failureReason(run),
    };
  }

  /** 失败原因:只从工件已有字段归纳;无法归纳时如实「未记录」。 */
  function failureReason(run) {
    if (run.validity === "INVALID" || run.status === "INVALID") return "无效运行(原因未记录)";
    var checks = (run.sections && run.sections.output_checks) || [];
    var failed = checks.filter(function (c) { return c.passed === false; });
    if (failed.length > 0) {
      return failed.map(function (c) { return checkLabel(c.check) + (c.detail ? ":" + c.detail : ""); }).join(";");
    }
    var judgment = run.sections && run.sections.final_result && run.sections.final_result.judgment;
    if (judgment && judgment.task_success === false) {
      if (judgment.tool_correct === false) return "工具选择与金标不一致";
      return "评测断言未通过(细分未记录)";
    }
    if (run.status === "FAILED") return "任务失败(原因未记录)";
    return null;
  }

  function checkLabel(check) {
    return {
      tool_correct: "工具选择",
      number_grounding: "数字接地",
      c1_compliance: "高危操作合规",
      c2_compliance: "专业建议合规",
    }[check] || check;
  }

  /** 机器键 → 中文显示映射(发布数据保持稳定英文键,显示层统一翻译;
   *  未知键原样返回,复合名按「 · 」分段翻译)。 */
  var ZH_LABELS = {
    // 实验模板
    "context-strategy-comparison": "上下文策略对照",
    "context-strategy": "上下文策略对照",
    "governance-on-off": "治理开关对照",
    "tool-delivery-comparison": "工具提供方式对照",
    "temperature-stability": "温度稳定性",
    "max-agent-steps-stability": "最大步数稳定性",
    "tool-availability-degradation": "工具可用性降级",
    "compression-method-comparison": "压缩方法对照",
    // 变体
    "off": "治理关闭", "standard": "治理标准",
    "all": "全量工具", "search": "搜索工具",
    "t0.0": "温度 0.0", "t0.1": "温度 0.1", "t0.3": "温度 0.3", "t0.7": "温度 0.7",
    "steps-3": "最多 3 步", "steps-4": "最多 4 步", "steps-5": "最多 5 步",
    "full-catalog": "完整目录", "remove-preferred": "移除首选工具", "remove-preferred-and-alternative": "移除首选+替代工具",
    "budgeted-extractive": "抽取式压缩", "budgeted-hybrid-v1": "混合主算法",
    "full": "完整上下文(对照)", "recent-turns": "最近轮次", "single-summary": "单次摘要",
    // 用例 / Session
    "cmp-basic-single-01": "基础·单工具",
    "cmp-multi-data-01": "多工具·数据",
    "cmp-multi-travel-01": "多工具·出行",
    "cmp-combo-route-01": "组合·路线",
    "ctx-session-database-deploy-01": "数据库与部署 Session",
    "ctx-session-product-evolution-01": "产品演进 Session",
    "ctx-session-context-engine-debug-01": "上下文引擎排查 Session",
  };

  function zhOne(value) {
    var text = String(value == null ? "" : value);
    return Object.prototype.hasOwnProperty.call(ZH_LABELS, text) ? ZH_LABELS[text] : text;
  }

  window.SHOWCASE = {
    /** 键 → 中文显示;复合名(「A · B」)分段翻译,未知段原样保留。 */
    zh: function (value) {
      var text = String(value == null ? "" : value);
      if (text.indexOf(" · ") === -1) return zhOne(text);
      return text.split(" · ").map(zhOne).join(" · ");
    },

    /** 正式批次索引;尚未发布(文件缺失)时返回 null,调用方渲染空状态。 */
    loadIndex: function () { return getJson("/showcase-data/index.json"); },

    /** 批次报告;缺失或无效返回 null。 */
    loadBatch: function (batchId) {
      if (!batchId || !/^[A-Za-z0-9_-]+$/.test(batchId)) return Promise.resolve(null);
      return getJson("/showcase-data/batches/" + encodeURIComponent(batchId) + "/report.json");
    },

    /** 单次运行公开工件;缺失或无效返回 null。 */
    loadRun: function (runId) {
      if (!runId || !/^[A-Za-z0-9_-]+$/.test(runId)) return Promise.resolve(null);
      return getJson("/showcase-data/runs/" + encodeURIComponent(runId) + ".json");
    },

    /** 拉取索引内全部正式批次的报告与运行,返回 [{batch, runs}];任一环节缺失即跳过该批次。 */
    loadPublished: async function () {
      var index = await this.loadIndex();
      if (!index || !Array.isArray(index.formal_batches) || index.formal_batches.length === 0) return [];
      var out = [];
      for (var i = 0; i < index.formal_batches.length; i += 1) {
        var ref = index.formal_batches[i];
        var batch = await this.loadBatch(ref.batch_id);
        if (!batch) continue;
        var runIds = [];
        (batch.cases || []).forEach(function (c) {
          Object.keys(c.run_ids || {}).forEach(function (g) {
            (c.run_ids[g] || []).forEach(function (id) {
              if (runIds.indexOf(id) === -1) runIds.push(id);
            });
          });
        });
        var runs = [];
        for (var j = 0; j < runIds.length; j += 1) {
          var run = await this.loadRun(runIds[j]);
          if (run) runs.push(run);
        }
        out.push({ batch: batch, runs: runs, publishedAt: ref.published_at });
      }
      return out;
    },

    METRICS: METRICS,
    METRIC_MAP: METRIC_MAP,
    runView: runView,
    failureReason: failureReason,

    /** 指标单元格:数值 + null 诚实显示;方向箭头(↑好/↓好)。 */
    metricCell: function (metrics, key) {
      var meta = METRIC_MAP[key];
      if (!meta) return { text: "未记录", value: null };
      var v = metrics ? metrics[key] : null;
      if (v == null) return { text: "未记录", value: null };
      var text = meta.kind === "pct" ? S.fmtPct(v)
        : meta.kind === "ms" ? S.fmtMs(v)
        : S.fmtInt(v);
      return { text: text, value: v };
    },
  };
})();

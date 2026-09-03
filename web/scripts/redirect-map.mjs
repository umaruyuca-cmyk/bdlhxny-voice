/** 旧路径 → 新五页位置(信息架构 v3 迁移映射)。
 *  五页:/ /results/ /evidence/ /system/ /methodology/。
 *  归属原则:结果类 → /results/,单次运行与运行记录 → /evidence/,
 *  实验设计/评判口径/题库语料 → /methodology/,系统执行/架构/治理/运维说明 → /system/。
 *  不把所有旧路由机械跳首页;静态资产(/docs/*.css|js、/showcase-data/*)不在映射内。 */
export const REDIRECTS = new Map([
  // 工作项目页升为首页(2026-09):旧 /work/ 地址 301 到 /
  ["/work", "/"],
  // 公告/旧首页族
  ["/announce", "/"],
  ["/home", "/"],
  ["/about", "/"],
  ["/about/banks", "/methodology/"],
  ["/about/repo", "/system/"],
  // 实证展示族 → 结果与证据
  ["/showcase", "/results/"],
  ["/showcase/results", "/results/"],
  ["/showcase/runs", "/evidence/"],
  ["/showcase/tools", "/evidence/"],
  ["/showcase/context", "/results/"],
  // 实验中心族:发起说明 → 测试逻辑;批次/运行记录 → 证据
  ["/experiment", "/methodology/"],
  ["/experiment/comparison", "/methodology/"],
  ["/experiment/cases", "/methodology/"],
  ["/experiment/compression", "/methodology/strategy-comparison.html"],
  ["/experiment/reproduce", "/methodology/"],
  ["/experiment/run", "/methodology/"],
  ["/experiment/series", "/methodology/"],
  ["/experiment/batches", "/evidence/"],
  ["/experiment/batch", "/evidence/"],
  ["/experiment/context-workbench", "/system/context-demo.html"],
  ["/experiment/context-build", "/system/context-demo.html"],
  // 我的测试 → 证据索引
  ["/test", "/evidence/"],
  // 上下文族:算法/构建 → 执行逻辑;语料与对照设计 → 测试逻辑;结果 → 结果页
  ["/context", "/system/"],
  ["/context/library", "/methodology/strategy-comparison.html"],
  ["/context/design", "/methodology/"],
  ["/context/results", "/results/"],
  // 评判族 → 测试逻辑(指标定义唯一版本所在)
  ["/judging", "/methodology/"],
  ["/judging/metrics", "/methodology/"],
  ["/judging/judge", "/methodology/"],
  ["/judging/invalid", "/methodology/"],
  // 引擎族 → 执行逻辑
  ["/engine", "/system/"],
  ["/engine/catalog", "/system/"],
  ["/engine/governance", "/system/"],
  ["/engine/guardrail", "/system/"],
  ["/engine/loading", "/system/"],
  ["/engine/tools", "/system/"],
  // 运维族 → 执行逻辑(公私边界/工件/发布校验)
  ["/ops", "/system/"],
  ["/ops/run-api", "/system/"],
  ["/ops/artifacts", "/system/"],
  ["/ops/deploy", "/system/"],
  ["/ops/roadmap", "/system/"],
  // 工具目录(说明并入执行逻辑);用例库(说明并入测试逻辑)
  ["/tools", "/system/"],
  ["/tools/detail", "/system/"],
  ["/cases", "/methodology/"],
  ["/cases/detail", "/methodology/"],
  // 数据资产首页(用例/工具/语料三入口) → 测试逻辑
  ["/assets", "/methodology/"],
  // 文档模块首页与旧文档页
  ["/docs", "/system/"],
  ["/docs/comparison", "/methodology/"],
  ["/docs/cases", "/methodology/"],
  ["/docs/eval", "/methodology/"],
  ["/docs/agents", "/system/"],
  ["/docs/skill", "/system/"],
  ["/docs/tools", "/system/"],
  ["/docs/results", "/results/"],
  // 旧运行台 → 执行逻辑(公开站无运行入口)
  ["/lab", "/system/"],
  // Session 交叉验证:设计 → 测试逻辑;结果 → 结果页
  ["/session-cross", "/methodology/"],
  ["/session-cross/inputs", "/methodology/"],
  ["/session-cross/results", "/results/"],
]);

/** 带路径参数的旧地址(前缀匹配):详情页统一落到对应新页,不逐 ID 保留。 */
export const PREFIX_REDIRECTS = [
  ["/experiment/batch/", "/evidence/"],
  ["/experiment/series/", "/methodology/"],
  ["/experiment/context-builds/", "/system/"],
  ["/lab/", "/system/"],
  ["/session-cross/", "/methodology/"],
];

/** 归一化:去 .html 后缀与尾部斜杠后查表(旧链接可能带扩展名或目录斜杠)。 */
export function redirectFor(requestPath) {
  let normalized = String(requestPath || "");
  if (normalized.endsWith(".html")) normalized = normalized.slice(0, -5);
  if (normalized.endsWith("/index")) normalized = normalized.slice(0, -6) || "/";
  while (normalized.length > 1 && normalized.endsWith("/")) normalized = normalized.slice(0, -1);
  if (REDIRECTS.has(normalized)) return REDIRECTS.get(normalized);
  for (const [prefix, target] of PREFIX_REDIRECTS) {
    if (normalized.startsWith(prefix)) return target;
  }
  return null;
}

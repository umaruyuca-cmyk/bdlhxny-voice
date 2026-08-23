/** 旧路径 → 新位置(任务六 §11 迁移映射;html 页面 301,静态资产 /docs/*.css|js 保留原位)。 */
export const REDIRECTS = new Map([
  ["/docs", "/"],
  ["/docs/", "/"],
  ["/docs/index", "/"],
  ["/announce", "/"],
  ["/announce/", "/"],
  ["/docs/comparison", "/experiment/"],
  ["/docs/cases", "/experiment/cases"],
  ["/docs/eval", "/judging/"],
  ["/docs/agents", "/engine/"],
  ["/docs/skill", "/engine/catalog"],
  ["/docs/tools", "/engine/tools"],
  ["/docs/results", "/showcase/results"],
  ["/showcase/context", "/context/results"],
  ["/home", "/"],
  ["/home/", "/"],
  ["/home/index", "/"],
]);

/** 归一化:去掉 .html 后查表(旧链接可能带扩展名)。 */
export function redirectFor(requestPath) {
  const normalized = requestPath.endsWith(".html") ? requestPath.slice(0, -5) : requestPath;
  return REDIRECTS.get(normalized) ?? REDIRECTS.get(requestPath) ?? null;
}

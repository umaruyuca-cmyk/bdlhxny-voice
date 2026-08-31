/**
 * 同源所有者通道 API 白名单(前后端对接契约 §2)。
 *
 * dev-server 反代、nginx.conf 反代与前端契约测试共用同一份清单,
 * 三处口径一致,不再各自维护正则(修复方案 P0-2):
 * - /api/v1/public/* 对所有部署放行(匿名受限测试接口);
 * - 下列所有者段落后私有部署反代到 engine;公开镜像无 engine 时上游 502,
 *   页面按匿名视图工作。
 */
export const OWNER_API_SEGMENTS = [
  "login",
  "logout",
  "llm-config/test",
  "experiment-templates",
  "template-batches",
  "experiment-series",
  "statistics",
  "batches",
  "jobs",
  "runs",
  "context",
];

/** dev-server 使用的完整匹配正则:^/api/v1/(seg1|seg2|...)(/|$) */
export function ownerApiRegExp() {
  const body = OWNER_API_SEGMENTS.map((segment) => segment.replace("/", "\\/")).join("|");
  return new RegExp(`^/api/v1/(${body})(/|$)`);
}

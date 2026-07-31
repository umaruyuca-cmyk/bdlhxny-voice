/**
 * 以固定并发数映射数组，避免单次分析瞬间放大为大量上游请求。
 */
export async function mapWithConcurrency(items, concurrency, mapper) {
  const values = Array.from(items ?? []);
  if (values.length === 0) return [];

  const limit = Math.max(1, Math.min(Number.parseInt(concurrency, 10) || 1, values.length));
  const results = new Array(values.length);
  let nextIndex = 0;

  async function worker() {
    while (nextIndex < values.length) {
      // 1. JavaScript 单线程内同步领取序号，确保每一项只处理一次。
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await mapper(values[index], index);
    }
  }

  await Promise.all(Array.from({ length: limit }, () => worker()));
  return results;
}

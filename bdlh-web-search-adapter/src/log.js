/**
 * 极简结构化日志：JSON 行写 stdout，零第三方依赖。
 *
 * 设计目标（P0-2 可观测性）：
 * - 所有运行期事件（鉴权失败/限流/空结果/上游失败/熔断/请求完成）输出
 *   带 traceId/agentId/taskId 的结构化记录，便于容器日志收集与排障；
 * - logger 可注入 sink（默认写 stdout），便于测试用 spy 断言；
 * - 不记录完整凭证与敏感头，仅记录稳定标识。
 */
const LEVELS = { debug: 10, info: 20, warn: 30, error: 40 };

export function createLogger(sink = defaultSink, minLevel = 'info') {
  const floor = LEVELS[minLevel] ?? LEVELS.info;
  function emit(level, event, fields = {}) {
    if (LEVELS[level] < floor) return;
    sink({ ts: new Date().toISOString(), level, event, ...fields });
  }
  return {
    debug: (event, fields) => emit('debug', event, fields),
    info: (event, fields) => emit('info', event, fields),
    warn: (event, fields) => emit('warn', event, fields),
    error: (event, fields) => emit('error', event, fields),
  };
}

function defaultSink(record) {
  process.stdout.write(`${JSON.stringify(record)}\n`);
}

export const defaultLogger = createLogger();

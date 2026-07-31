import { methodologyFor } from '../analysis/methodology.js';

export const SKILL_SCHEMA_VERSION = '1.1';
export const SKILL_TIMEZONE = 'Asia/Shanghai';
export const SKILL_COMMANDS = Object.freeze(['stock', 'portfolio', 'quant', 'sector']);

/**
 * 构建所有分析命令共享的成功信封，使调用方无需猜测不同命令的输出形状。
 */
export function buildSuccessContract(command, {
  asOf,
  request = {},
  dataQuality = {},
  data = {},
  sources = {},
  decisionBasis = {},
}) {
  assertCommand(command);
  return {
    schemaVersion: SKILL_SCHEMA_VERSION,
    command,
    timezone: SKILL_TIMEZONE,
    asOf: asOf ?? null,
    request,
    methodology: methodologyFor(command),
    decisionBasis,
    dataQuality: {
      ...dataQuality,
      status: dataQuality.status ?? (asOf ? 'verified' : 'unknown'),
      asOf: dataQuality.asOf ?? asOf ?? null,
      allowsDirectionalSignal: Boolean(dataQuality.allowsDirectionalSignal),
      provisional: Boolean(dataQuality.provisional),
      warnings: Array.isArray(dataQuality.warnings) ? [...dataQuality.warnings] : [],
    },
    data,
    sources,
  };
}

/**
 * 构建可机器读取的失败信封；堆栈与本机路径不进入公开错误。
 */
export function buildErrorContract(command, error) {
  const safeCommand = SKILL_COMMANDS.includes(command) ? command : 'unknown';
  return {
    schemaVersion: SKILL_SCHEMA_VERSION,
    command: safeCommand,
    timezone: SKILL_TIMEZONE,
    asOf: null,
    error: {
      code: normalizeErrorCode(error?.code),
      message: safeMessage(error),
    },
  };
}

/**
 * 从 CLI 参数中确定真实命令，仅用于错误信封关联。
 */
export function detectCommand(argv = process.argv.slice(2)) {
  return SKILL_COMMANDS.find((command) => argv.includes(command)) ?? 'unknown';
}

/**
 * 向 stdout 写入唯一 JSON 文档，禁止混入日志或终端表格。
 */
export function writeJsonContract(contract) {
  process.stdout.write(`${JSON.stringify(contract)}\n`);
}

function assertCommand(command) {
  if (!SKILL_COMMANDS.includes(command)) {
    throw Object.assign(new Error(`不支持的 Skill Command: ${command}`), {
      code: 'UNSUPPORTED_COMMAND',
    });
  }
}

function normalizeErrorCode(value) {
  const code = String(value ?? 'SKILL_EXECUTION_FAILED').trim().toUpperCase();
  return /^[A-Z][A-Z0-9_]{2,63}$/.test(code) ? code : 'SKILL_EXECUTION_FAILED';
}

function safeMessage(error) {
  const message = String(error?.message ?? 'Skill 执行失败').trim();
  return message ? message.slice(0, 1_000) : 'Skill 执行失败';
}

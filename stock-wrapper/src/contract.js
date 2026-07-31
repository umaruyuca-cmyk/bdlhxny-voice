import { WrapperError } from './errors.js';

const WRAPPER_CONTRACT_VERSION = '1.0';
const SKILL_SCHEMA_VERSION = '1.1';

/**
 * 把不同 CLI 命令的输出统一成 Java 消费端可校验的 Skill JSON 契约。
 */
export function normalizeSkillOutput(command, stdout) {
  const text = String(stdout ?? '').trim();
  if (!text) {
    throw new WrapperError(502, 'SKILL_EMPTY_OUTPUT', 'Skill 未返回任何内容');
  }

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new WrapperError(502, 'SKILL_INVALID_JSON', 'Skill stdout 不是合法 JSON');
  }

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new WrapperError(502, 'SKILL_INVALID_CONTRACT', 'Skill 输出必须是 JSON 对象');
  }
  if (parsed.schemaVersion !== SKILL_SCHEMA_VERSION) {
    throw new WrapperError(502, 'SKILL_SCHEMA_UNSUPPORTED', `不支持的 Skill schemaVersion: ${parsed.schemaVersion ?? 'missing'}`);
  }
  if (parsed.command !== command) {
    throw new WrapperError(502, 'SKILL_COMMAND_MISMATCH', `Skill command 不匹配: ${parsed.command ?? 'missing'}`);
  }
  if (parsed.timezone !== 'Asia/Shanghai') {
    throw new WrapperError(502, 'SKILL_TIMEZONE_INVALID', 'Skill timezone 必须是 Asia/Shanghai');
  }
  if (typeof parsed.asOf !== 'string' || !parsed.asOf.trim()) {
    throw new WrapperError(502, 'SKILL_AS_OF_MISSING', 'Skill 缺少已核验 asOf');
  }
  if (!parsed.dataQuality || typeof parsed.dataQuality !== 'object' || Array.isArray(parsed.dataQuality)) {
    throw new WrapperError(502, 'SKILL_DATA_QUALITY_MISSING', 'Skill 缺少 dataQuality');
  }
  if (!parsed.data || typeof parsed.data !== 'object' || Array.isArray(parsed.data)) {
    throw new WrapperError(502, 'SKILL_DATA_MISSING', 'Skill 缺少结构化 data');
  }
  if (!parsed.methodology
      || typeof parsed.methodology !== 'object'
      || parsed.methodology.id !== 'stockwise-objective-analysis'
      || typeof parsed.methodology.version !== 'string'
      || !Array.isArray(parsed.methodology.rules)) {
    throw new WrapperError(502, 'SKILL_METHODOLOGY_MISSING', 'Skill 缺少可追溯 methodology');
  }
  if (!parsed.decisionBasis
      || typeof parsed.decisionBasis !== 'object'
      || Array.isArray(parsed.decisionBasis)) {
    throw new WrapperError(502, 'SKILL_DECISION_BASIS_MISSING', 'Skill 缺少结构化 decisionBasis');
  }
  if (command === 'sector') {
    validateSectorHeatContract(parsed);
  }
  return parsed;
}

/**
 * 校验板块热度可解释字段，避免旧版不透明分数继续进入 Java Agent。
 */
function validateSectorHeatContract(parsed) {
  if (!Array.isArray(parsed.data.sectors)) {
    throw new WrapperError(502, 'SECTOR_HEAT_CONTRACT_INVALID', 'sector 缺少板块排名数组');
  }
  for (const sector of parsed.data.sectors) {
    const breakdown = sector?.heatScoreBreakdown;
    if (!Number.isFinite(sector?.heatScore)
        || !breakdown
        || breakdown.formulaVersion !== 'sector-heat-v2'
        || breakdown.normalization !== 'cross_sectional_percentile'
        || !breakdown.components
        || typeof breakdown.components !== 'object') {
      throw new WrapperError(502, 'SECTOR_HEAT_CONTRACT_INVALID', 'sector 热度缺少可复算分项');
    }
  }
}

/**
 * 生成 Wrapper 自身的版本化 HTTP 响应信封。
 */
export function successEnvelope(requestId, command, data) {
  return {
    success: true,
    requestId,
    contractVersion: WRAPPER_CONTRACT_VERSION,
    command,
    asOf: data?.asOf ?? null,
    data,
    error: null,
  };
}

/**
 * 生成不泄露堆栈与内部命令行的错误响应。
 */
export function errorEnvelope(requestId, code, message, details = null) {
  return {
    success: false,
    requestId,
    contractVersion: WRAPPER_CONTRACT_VERSION,
    data: null,
    error: {
      code,
      message,
      details,
    },
  };
}

import { createServer as createHttpServer } from 'node:http';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { errorEnvelope, successEnvelope } from './contract.js';
import { WrapperError } from './errors.js';

const ROUTES = new Map([
  ['POST /api/v1/stock/analyze', 'stock'],
  ['POST /api/v1/portfolio/analyze', 'portfolio'],
  ['POST /api/v1/quant/analyze', 'quant'],
  ['POST /api/v1/sector/analyze', 'sector'],
]);

/**
 * 创建无外部框架依赖的内部 HTTP 服务。
 */
export function createApp(config, executor) {
  return createHttpServer(async (request, response) => {
    const requestId = header(request, 'x-request-id') || randomUUID();
    response.setHeader('content-type', 'application/json; charset=utf-8');
    response.setHeader('x-request-id', requestId);

    try {
      if (request.method === 'GET' && request.url === '/health') {
        writeJson(response, 200, { status: 'UP', service: 'stock-wrapper' });
        return;
      }
      if (request.method === 'GET' && request.url === '/ready') {
        const ready = executor.isReady();
        writeJson(response, ready ? 200 : 503, { status: ready ? 'READY' : 'NOT_READY' });
        return;
      }

      verifyInternalToken(config.internalToken, header(request, 'x-internal-token'));
      const routeKey = `${request.method} ${pathOnly(request.url)}`;
      const command = ROUTES.get(routeKey);
      if (!command) {
        throw new WrapperError(404, 'NOT_FOUND', '接口不存在');
      }

      // 1. 先限制请求体大小，再执行命令级参数校验。
      const body = await readJsonBody(request, config.maxBodyBytes);
      const input = validateInput(command, body);
      const result = await executor.execute(command, input);
      writeJson(response, 200, successEnvelope(requestId, command, result));
    } catch (error) {
      const mapped = mapError(error);
      writeJson(response, mapped.status, errorEnvelope(requestId, mapped.code, mapped.message, mapped.details));
    }
  });
}

function validateInput(command, body) {
  if (command === 'stock') {
    const symbol = String(body.symbol ?? '').trim();
    if (!/^\d{6}$/.test(symbol)) {
      throw new WrapperError(400, 'INVALID_SYMBOL', 'symbol 必须是 6 位数字代码');
    }
    const assetType = String(body.assetType ?? 'auto').trim().toLowerCase();
    const allowed = new Set(['auto', 'stock', 'etf', 'fund', 'open_fund', 'qdii']);
    if (!allowed.has(assetType)) {
      throw new WrapperError(400, 'INVALID_ASSET_TYPE', 'assetType 不在允许范围内');
    }
    return { symbol, assetType };
  }
  if (command === 'portfolio') {
    const monthlyBudget = finiteNumber(body.monthlyBudget, 'monthlyBudget', value => value > 0);
    const cash = finiteNumber(body.cash ?? 0, 'cash', value => value >= 0);
    const cashReserveRatio = finiteNumber(
      body.cashReserveRatio ?? 0.2,
      'cashReserveRatio',
      value => value >= 0.15 && value <= 1,
    );
    if (!Array.isArray(body.positions) || body.positions.length < 1 || body.positions.length > 50) {
      throw new WrapperError(400, 'INVALID_POSITIONS', 'positions 数量必须在 1 到 50 之间');
    }
    return {
      monthlyBudget,
      cash,
      cashReserveRatio,
      positions: body.positions.map((position, index) => validatePosition(position, index)),
    };
  }
  if (command === 'quant') {
    const codes = Array.isArray(body.codes)
      ? [...new Set(body.codes.map(code => String(code).trim()))]
      : [];
    if (codes.length < 2 || codes.some(code => !/^\d{6}$/.test(code))) {
      throw new WrapperError(400, 'INVALID_CODES', 'codes 至少包含两个不重复的 6 位代码');
    }
    const benchmark = body.benchmark == null ? null : String(body.benchmark).trim();
    if (benchmark && !/^\d{6}$/.test(benchmark)) {
      throw new WrapperError(400, 'INVALID_BENCHMARK', 'benchmark 必须是 6 位代码');
    }
    return { codes, benchmark };
  }
  if (command === 'sector') {
    const type = String(body.type ?? 'industry').trim().toLowerCase();
    if (!['industry', 'concept'].includes(type)) {
      throw new WrapperError(400, 'INVALID_SECTOR_TYPE', 'type 只能是 industry 或 concept');
    }
    const limit = Number.parseInt(body.limit ?? 20, 10);
    if (!Number.isFinite(limit) || limit < 1 || limit > 100) {
      throw new WrapperError(400, 'INVALID_LIMIT', 'limit 必须在 1 到 100 之间');
    }
    return { type, limit };
  }
  throw new WrapperError(400, 'UNSUPPORTED_COMMAND', '不支持的分析命令');
}

function validatePosition(value, index) {
  const position = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const prefix = `positions[${index}]`;
  const code = String(position.code ?? '').trim();
  if (!/^\d{6}$/.test(code)) {
    throw new WrapperError(400, 'INVALID_POSITION', `${prefix}.code 必须是 6 位数字代码`);
  }
  const name = String(position.name ?? '').trim();
  if (!name || name.length > 100) {
    throw new WrapperError(400, 'INVALID_POSITION', `${prefix}.name 长度必须在 1 到 100 之间`);
  }
  const assetType = String(position.assetType ?? 'auto').trim().toLowerCase();
  if (!['auto', 'stock', 'etf', 'fund', 'open_fund', 'qdii'].includes(assetType)) {
    throw new WrapperError(400, 'INVALID_POSITION', `${prefix}.assetType 不在允许范围内`);
  }
  const buyDate = String(position.buyDate ?? '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(buyDate) || Number.isNaN(Date.parse(buyDate))) {
    throw new WrapperError(400, 'INVALID_POSITION', `${prefix}.buyDate 必须是有效日期`);
  }
  return {
    code,
    name,
    assetType,
    avgCost: finiteNumber(position.avgCost, `${prefix}.avgCost`, number => number > 0),
    shares: finiteNumber(position.shares, `${prefix}.shares`, number => number > 0),
    buyDate,
    targetWeight: finiteNumber(
      position.targetWeight,
      `${prefix}.targetWeight`,
      number => number >= 0 && number <= 1,
    ),
    sector: optionalText(position.sector, 50),
    riskRole: optionalText(position.riskRole, 30),
  };
}

function finiteNumber(value, field, predicate) {
  const number = Number(value);
  if (!Number.isFinite(number) || !predicate(number)) {
    throw new WrapperError(400, 'INVALID_PORTFOLIO', `${field} 数值无效`);
  }
  return number;
}

function optionalText(value, maxLength) {
  if (value == null) return null;
  const text = String(value).trim();
  return text ? text.slice(0, maxLength) : null;
}

function verifyInternalToken(expected, actual) {
  if (!expected) return;
  const expectedBuffer = Buffer.from(expected);
  const actualBuffer = Buffer.from(actual ?? '');
  if (expectedBuffer.length !== actualBuffer.length || !timingSafeEqual(expectedBuffer, actualBuffer)) {
    throw new WrapperError(401, 'UNAUTHORIZED', '内部调用凭证无效');
  }
}

function readJsonBody(request, maxBytes) {
  return new Promise((resolve, reject) => {
    let bytes = 0;
    let text = '';
    let tooLarge = false;
    request.on('data', chunk => {
      if (tooLarge) return;
      bytes += chunk.length;
      if (bytes > maxBytes) {
        tooLarge = true;
        reject(new WrapperError(413, 'BODY_TOO_LARGE', '请求体超过大小限制'));
        return;
      }
      text += chunk.toString('utf8');
    });
    request.on('end', () => {
      if (tooLarge) return;
      if (!text.trim()) {
        resolve({});
        return;
      }
      try {
        const parsed = JSON.parse(text);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error('请求体必须是 JSON 对象');
        }
        resolve(parsed);
      } catch (error) {
        reject(new WrapperError(400, 'INVALID_JSON', `JSON 请求体无效: ${error.message}`));
      }
    });
    request.on('error', error => reject(new WrapperError(400, 'REQUEST_READ_FAILED', error.message)));
  });
}

function mapError(error) {
  if (error instanceof WrapperError) return error;
  return new WrapperError(500, 'INTERNAL_ERROR', '分析服务内部错误');
}

function writeJson(response, status, body) {
  response.statusCode = status;
  response.end(JSON.stringify(body));
}

function pathOnly(url) {
  return String(url ?? '').split('?', 1)[0];
}

function header(request, name) {
  const value = request.headers[name];
  return Array.isArray(value) ? value[0] : value;
}

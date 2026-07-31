import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { WrapperError } from './errors.js';
import { normalizeSkillOutput } from './contract.js';

/**
 * 在独立 Node 服务中受控执行 stock-analysis-skill CLI。
 */
export class StockSkillCliExecutor {
  constructor(config) {
    this.config = config;
    this.activeExecutions = 0;
  }

  /**
   * 检查 CLI 入口是否存在，用于 readiness 探针。
   */
  isReady() {
    return fs.existsSync(this.config.cliScript);
  }

  /**
   * 执行一个白名单命令并返回统一 Skill 契约。
   */
  async execute(command, input) {
    if (!this.isReady()) {
      throw new WrapperError(503, 'SKILL_NOT_READY', 'stock-analysis-skill CLI 不可用');
    }
    if (this.activeExecutions >= this.config.maxConcurrency) {
      throw new WrapperError(429, 'WRAPPER_BUSY', '分析服务繁忙，请稍后重试');
    }

    let temporaryPortfolio = null;
    this.activeExecutions += 1;
    try {
      // 1. 真实持仓只在获得并发执行槽后落临时文件
      if (command === 'portfolio') {
        temporaryPortfolio = writeTemporaryPortfolio(input);
      }
      const args = buildArguments(
        this.config.cliScript,
        command,
        input,
        temporaryPortfolio?.filePath,
      );
      const stdout = await spawnCli(this.config, args);
      return normalizeSkillOutput(command, stdout);
    } finally {
      // 2. 用户持仓只作为单次 CLI 输入，完成或失败后都立即删除
      if (temporaryPortfolio) {
        fs.rmSync(temporaryPortfolio.directory, { recursive: true, force: true });
      }
      this.activeExecutions -= 1;
    }
  }
}

function buildArguments(cliScript, command, input, portfolioConfigPath = null) {
  if (command === 'stock') {
    return [
      cliScript,
      '--no-save',
      'stock',
      input.symbol,
      '--asset',
      input.assetType,
      '--json',
    ];
  }
  if (command === 'portfolio') {
    if (!portfolioConfigPath) {
      throw new WrapperError(400, 'PORTFOLIO_CONFIG_REQUIRED', '组合分析缺少真实用户持仓配置');
    }
    return [cliScript, '--no-save', '--config', portfolioConfigPath, 'portfolio', '--json'];
  }
  if (command === 'quant') {
    const args = [cliScript, '--no-save', 'quant', ...input.codes];
    if (input.benchmark) args.push('--benchmark', input.benchmark);
    args.push('--json');
    return args;
  }
  if (command === 'sector') {
    return [
      cliScript,
      '--no-save',
      'sector',
      '--type',
      input.type,
      '--limit',
      String(input.limit),
      '--json',
    ];
  }
  throw new WrapperError(400, 'UNSUPPORTED_COMMAND', `不支持的分析命令: ${command}`);
}

function writeTemporaryPortfolio(input) {
  try {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'stockwise-portfolio-'));
    const filePath = path.join(directory, 'portfolio.json');
    fs.writeFileSync(filePath, JSON.stringify(input), {
      encoding: 'utf8',
      flag: 'wx',
      mode: 0o600,
    });
    return { directory, filePath };
  } catch (error) {
    throw new WrapperError(500, 'PORTFOLIO_CONFIG_WRITE_FAILED', '无法准备用户持仓分析配置');
  }
}

function spawnCli(config, args) {
  return new Promise((resolve, reject) => {
    // 1. 使用参数数组而不是 shell 字符串，避免用户输入参与命令解释。
    const child = spawn(config.nodeBin, args, {
      cwd: config.skillPath,
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let stdout = '';
    let stderr = '';
    let outputBytes = 0;
    let settled = false;

    const timeout = setTimeout(() => {
      child.kill('SIGKILL');
      finish(new WrapperError(504, 'SKILL_TIMEOUT', `分析执行超过 ${config.timeoutMs}ms`));
    }, config.timeoutMs);

    child.stdout.on('data', chunk => {
      outputBytes += chunk.length;
      if (outputBytes > config.maxOutputBytes) {
        child.kill('SIGKILL');
        finish(new WrapperError(502, 'OUTPUT_TOO_LARGE', 'Skill 输出超过大小限制'));
        return;
      }
      stdout += chunk.toString('utf8');
    });
    child.stderr.on('data', chunk => {
      stderr += chunk.toString('utf8');
    });
    child.on('error', error => {
      finish(new WrapperError(502, 'SKILL_START_FAILED', `Skill 启动失败: ${error.message}`));
    });
    child.on('close', code => {
      if (code !== 0) {
        finish(skillExecutionError(code, stderr));
        return;
      }
      finish(null, stdout);
    });

    function finish(error, value) {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      if (error) reject(error);
      else resolve(value);
    }
  });
}

function skillExecutionError(code, stderr) {
  const text = String(stderr ?? '').trim();
  try {
    const parsed = JSON.parse(text);
    if (parsed?.error?.code && parsed?.error?.message) {
      return new WrapperError(
        502,
        String(parsed.error.code),
        String(parsed.error.message),
        { exitCode: code, skillCommand: parsed.command ?? null },
      );
    }
  } catch {
    // 1. 非 JSON stderr 仅作为截断诊断保留，不能推测业务错误
  }
  return new WrapperError(
    502,
    'SKILL_EXECUTION_FAILED',
    `Skill 执行失败，退出码 ${code}`,
    safeStderr(stderr),
  );
}

function safeStderr(stderr) {
  const text = String(stderr ?? '').trim();
  return text ? text.slice(0, 1_000) : null;
}

#!/usr/bin/env node

import { Command } from 'commander';
import { runPortfolioAnalysis, runQuantAnalysis, runSectorAnalysis, runStockAnalysis } from '../src/index.js';
import { logError } from '../src/utils/logger.js';
import { buildErrorContract, detectCommand } from '../src/output/json-contract.js';

const program = new Command();

program
  .name('stock-analysis')
  .description('A 股/ETF/基金持仓、板块轮动、追高判断和月度资金部署 CLI')
  .version('0.5.0')
  .option('-c, --config <path>', 'portfolio.json 配置文件路径', 'portfolio.json')
  .option('--days <number>', '拉取 K 线天数', (value) => Number.parseInt(value, 10), 120)
  .option('--no-color', '关闭彩色输出')
  .option('--no-save', '不自动保存分析结果到 history/ 目录')
  .option('-v, --verbose', '输出调试信息');

program
  .command('quant <codes...>')
  .description('对 ETF 池执行多周期动量、波动率目标和历史轮动回测')
  .option('--benchmark <code>', 'MA200 与波动率分位数市场过滤基准', '510300')
  .option('--history-days <number>', '回测 K 线数量', (value) => Number.parseInt(value, 10), 750)
  .option('--select-count <number>', '每次选择 ETF 数量', (value) => Number.parseInt(value, 10), 3)
  .option('--max-asset-weight <number>', '单只 ETF 最高权重（0-1）', (value) => Number.parseFloat(value), 0.35)
  .option('--target-vol <number>', '组合目标年化波动率（0-1）', (value) => Number.parseFloat(value), 0.12)
  .option('--rebalance-every <number>', '每隔多少个共同交易日调仓', (value) => Number.parseInt(value, 10), 5)
  .option('--transaction-cost-rate <number>', '单边交易成本率', (value) => Number.parseFloat(value), 0.0003)
  .option('--json', '输出包含排名、调仓记录和净值曲线的 JSON')
  .action(async (codes, options) => {
    await runQuantAnalysis(codes, { ...program.opts(), ...options });
  });

program
  .command('sector')
  .description('输出 A 股行业/概念板块热力排名与轮动提示')
  .option('-t, --type <type>', '板块类型：industry 或 concept', 'industry')
  .option('-l, --limit <number>', '展示数量', (value) => Number.parseInt(value, 10), 20)
  .option('--json', '输出供程序读取的结构化 JSON')
  .action(async (options) => {
    await runSectorAnalysis({ ...program.opts(), ...options });
  });

program
  .command('portfolio')
  .description('基于 portfolio.json 输出完整持仓决策看板')
  .option('-l, --sector-limit <number>', '看板中展示的板块数量', (value) => Number.parseInt(value, 10), 10)
  .option('--json', '输出供程序读取的结构化 JSON')
  .action(async (options) => {
    await runPortfolioAnalysis({ ...program.opts(), ...options });
  });

program
  .command('stock <code>')
  .description('分析单只股票、场内 ETF 或场外基金的技术面、追高状态与补仓梯度')
  .option('-a, --asset <type>', '资产类型：auto、stock、etf、fund、open_fund、qdii', 'auto')
  .option('--shares <number>', '当前持仓股数，用于计算 T+1 和手续费后净盈亏', (value) => Number.parseFloat(value))
  .option('--avg-cost <number>', '当前持仓成本价，用于计算手续费后净盈亏', (value) => Number.parseFloat(value))
  .option('--buy-date <date>', '买入日期，例如 2026-05-29；当天买入会触发 T+1 不可卖提醒')
  .option('--commission-rate <number>', '佣金费率，默认 0.0003', (value) => Number.parseFloat(value))
  .option('--min-commission <number>', '最低佣金，默认 5 元', (value) => Number.parseFloat(value))
  .option('--stamp-duty-rate <number>', '股票卖出印花税率，默认 0.0005', (value) => Number.parseFloat(value))
  .option('--transfer-fee-rate <number>', '过户费率，默认 0.00001', (value) => Number.parseFloat(value))
  .option('--min-trade-amount <number>', '建议最低单笔交易金额，默认 1500', (value) => Number.parseFloat(value))
  .option('--preferred-trade-amount <number>', '偏好单笔交易金额，默认 3000', (value) => Number.parseFloat(value))
  .option('--split-trade-min-amount <number>', '允许分批时每笔尽量不低于的金额，默认 3000', (value) => Number.parseFloat(value))
  .option('--min-profit-fee-multiple <number>', '主动止盈至少覆盖往返费用倍数，默认 2', (value) => Number.parseFloat(value))
  .option('--json', '输出供程序读取的结构化 JSON')
  .action(async (code, options) => {
    await runStockAnalysis(code, { ...program.opts(), ...options });
  });

program.action(async () => {
  await runPortfolioAnalysis(program.opts());
});

try {
  await program.parseAsync(process.argv);
} catch (error) {
  // 1. 机器模式只向 stderr 写入结构化错误，禁止泄露堆栈和本机路径之外的诊断
  if (process.argv.includes('--json')) {
    process.stderr.write(`${JSON.stringify(buildErrorContract(detectCommand(), error))}\n`);
  } else {
    logError(error.message);
  }
  process.exitCode = 1;
}

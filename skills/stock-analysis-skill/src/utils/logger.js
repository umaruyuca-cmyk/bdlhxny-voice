import chalk from 'chalk';

export function logInfo(message) {
  console.error(chalk.gray(`[INFO] ${message}`));
}

export function logWarn(message) {
  console.error(chalk.yellow(`⚠ ${message}`));
}

export function logError(message) {
  console.error(chalk.red(`❌ ${message}`));
}

export function logSourceFailure(source, error, verbose = false) {
  if (verbose) {
    logWarn(`${source} 数据源失败: ${error.message}`);
  }
}

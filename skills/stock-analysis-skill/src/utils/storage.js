import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { logInfo, logWarn } from './logger.js';
import { chinaDateString, chinaDateTimeString } from './china-time.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..', '..');

const HISTORY_DIR = path.join(projectRoot, 'history');

function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
  }
}

function stripAnsi(text) {
  return text.replace(/\x1b\[[0-9;]*m/g, '');
}

function timestamp() {
  return chinaDateString();
}

function datetime() {
  return chinaDateTimeString().replace(' ', '_').replaceAll(':', '');
}

/**
 * Save analysis output to a date-stamped file under history/.
 * @param {'portfolio'|'sector'|'stock'} type
 * @param {string} identifier - stock code for stock type, empty for others
 * @param {string} content - the analysis output text (may contain ANSI)
 * @returns {{ filePath: string, saved: boolean }}
 */
export function saveAnalysisOutput(type, identifier, content) {
  try {
    ensureDir(HISTORY_DIR);

    const cleanContent = stripAnsi(content);
    if (!cleanContent.trim()) {
      logWarn('分析输出为空，跳过保存');
      return { filePath: '', saved: false };
    }

    const ts = datetime();
    const suffix = identifier ? `_${String(identifier)}` : '';
    const filename = `${ts}_${type}${suffix}.md`;
    const filePath = path.join(HISTORY_DIR, filename);

    // Add a markdown header with metadata
    const header = [
      `# ${type === 'portfolio' ? '持仓决策看板' : type === 'sector' ? '板块热力分析' : '单股分析'}`,
      `- 日期: ${timestamp()}`,
      `- 保存时间: ${ts}`,
      type === 'stock' ? `- 代码: ${identifier}` : '',
      '',
    ].filter(Boolean).join('\n');

    const fullContent = `${header}\n${cleanContent}`;
    fs.writeFileSync(filePath, fullContent, 'utf8');

    logInfo(`分析结果已保存至 history/${path.basename(filePath)}`);
    return { filePath, saved: true };
  } catch (error) {
    logWarn(`自动保存失败: ${error.message}`);
    return { filePath: '', saved: false };
  }
}

/**
 * List all saved analysis records.
 * @param {object} [filter] - Optional filter by type or date
 * @returns {Array<{ filename: string, filePath: string, type: string, date: string, size: number }>}
 */
export function listSavedRecords(filter = {}) {
  try {
    ensureDir(HISTORY_DIR);
    const files = fs.readdirSync(HISTORY_DIR)
      .filter((f) => f.endsWith('.md'))
      .map((filename) => {
        const filePath = path.join(HISTORY_DIR, filename);
        const stat = fs.statSync(filePath);
        // Parse filename: YYYY-MM-DD_HHmmss_type_identifier.md
        const parts = filename.replace('.md', '').split('_');
        return {
          filename,
          filePath,
          date: parts[0] || '',
          time: parts[1] || '',
          type: parts[2] || 'unknown',
          identifier: parts.slice(3).join('_') || '',
          size: stat.size,
          mtime: stat.mtime,
        };
      })
      .sort((a, b) => b.mtime - a.mtime);

    if (filter.type) {
      return files.filter((f) => f.type === filter.type);
    }
    return files;
  } catch {
    return [];
  }
}

/**
 * Get the history directory path.
 */
export function getHistoryDir() {
  return HISTORY_DIR;
}

import { createHash } from 'node:crypto';

const TRACKING_PARAMETERS = new Set([
  'utm_source',
  'utm_medium',
  'utm_campaign',
  'utm_term',
  'utm_content',
  'spm',
  'from',
]);

/**
 * 将不同 Provider 的原始结果清洗为跨 Agent 稳定的 SearchResult。
 */
export function normalizeResults(task, rawResults, provider, retrievedAt = new Date()) {
  const deduplicated = new Map();
  for (const raw of Array.isArray(rawResults) ? rawResults : []) {
    const normalized = normalizeOne(task, raw, provider, retrievedAt);
    if (!normalized || task.excludeDomains.includes(normalized.domain)) continue;
    if (task.includeDomains.length > 0 && !matchesDomain(normalized.domain, task.includeDomains)) continue;
    const existing = deduplicated.get(normalized.url);
    if (!existing || normalized.relevanceScore > existing.relevanceScore) {
      deduplicated.set(normalized.url, normalized);
    }
  }
  return [...deduplicated.values()]
    .sort((left, right) => right.relevanceScore - left.relevanceScore)
    .slice(0, task.maxResults);
}

function normalizeOne(task, raw, provider, retrievedAt) {
  const url = normalizeUrl(raw?.url);
  if (!url) return null;
  const domain = new URL(url).hostname.toLowerCase();
  const title = cleanText(raw?.title, 300);
  if (!title) return null;
  return {
    resultId: stableId(task.taskId, url),
    taskId: task.taskId,
    purposeCode: task.purposeCode,
    title,
    url,
    domain,
    snippet: cleanText(raw?.content ?? raw?.snippet, 1_000),
    sourceType: sourceType(domain, task.includeDomains),
    provider,
    publishedAt: validDate(raw?.publishedDate ?? raw?.publishedAt),
    retrievedAt: retrievedAt.toISOString(),
    relevanceScore: score(raw?.score),
  };
}

function normalizeUrl(value) {
  try {
    const url = new URL(String(value ?? ''));
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    url.hash = '';
    for (const parameter of [...url.searchParams.keys()]) {
      if (TRACKING_PARAMETERS.has(parameter.toLowerCase())) {
        url.searchParams.delete(parameter);
      }
    }
    return url.toString();
  } catch {
    return null;
  }
}

function cleanText(value, maxLength) {
  const normalized = String(value ?? '')
    .replace(/<script[\s\S]*?<\/script>/gi, ' ')
    .replace(/<style[\s\S]*?<\/style>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[\u0000-\u001f\u007f]/g, ' ')
    .replace(/\b(ignore|disregard)\s+(all\s+)?(previous|prior)\s+instructions?\b/gi, '[已清理]')
    .replace(/\s+/g, ' ')
    .trim();
  return normalized.length <= maxLength
    ? normalized
    : `${normalized.slice(0, maxLength)}…`;
}

function sourceType(domain, preferredDomains) {
  if (matchesDomain(domain, preferredDomains)) return 'OFFICIAL';
  if (/(gov\.cn|cninfo\.com\.cn|sse\.com\.cn|szse\.cn|bse\.cn)$/.test(domain)) return 'OFFICIAL';
  return 'WEB';
}

function matchesDomain(domain, domains) {
  return domains.some(candidate => domain === candidate || domain.endsWith(`.${candidate}`));
}

function validDate(value) {
  if (!value) return null;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

function score(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
}

function stableId(taskId, url) {
  return createHash('sha256').update(`${taskId}\n${url}`).digest('hex').slice(0, 24);
}

/**
 * 提供进程内短期缓存，减少相同搜索重复触发上游反爬。
 */
export class SearchCache {
  constructor(ttlMs) {
    this.ttlMs = ttlMs;
    this.entries = new Map();
  }

  get(key) {
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (entry.expiresAt <= Date.now()) {
      this.entries.delete(key);
      return null;
    }
    return structuredClone(entry.value);
  }

  set(key, value) {
    this.entries.set(key, {
      expiresAt: Date.now() + this.ttlMs,
      value: structuredClone(value),
    });
  }
}

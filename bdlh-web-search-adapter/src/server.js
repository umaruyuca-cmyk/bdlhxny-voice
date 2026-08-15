import { createServer } from 'node:http';
import { createApp } from './app.js';
import { SearchCache } from './cache.js';
import { loadConfig } from './config.js';
import { SearxngSearchProvider } from './provider/searxng-search-provider.js';

const config = loadConfig();
const provider = new SearxngSearchProvider(config);
const cache = new SearchCache(config.cacheTtlMs);
const server = createServer(createApp(config, provider, cache));

server.listen(config.port, '0.0.0.0', () => {
  console.log(`bdlh-web-search-adapter listening on ${config.port}`);
});

import { createApp } from './app.js';
import { loadConfig } from './config.js';
import { StockSkillCliExecutor } from './cli-executor.js';

const config = loadConfig();
const executor = new StockSkillCliExecutor(config);
const server = createApp(config, executor);

server.listen(config.port, '0.0.0.0', () => {
  console.log(`stock-wrapper 已启动，端口 ${config.port}`);
});

function shutdown(signal) {
  console.log(`收到 ${signal}，停止接收新请求`);
  server.close(error => {
    if (error) {
      console.error(`stock-wrapper 关闭失败: ${error.message}`);
      process.exitCode = 1;
    }
  });
}

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

import http from "node:http";
import https from "node:https";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const host = process.env.HOST || "127.0.0.1";
const port = Number.parseInt(process.env.PORT || "8082", 10);
const backendUrl = new URL(process.env.STOCKWISE_BACKEND_URL || "http://127.0.0.1:8080");
const publicDirectory = fileURLToPath(new URL("./public/", import.meta.url));
const prototypeDirectory = fileURLToPath(new URL("./prototypes/", import.meta.url));

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".png", "image/png"],
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".ico", "image/x-icon"]
]);

/**
 * 提供本地静态页面并将 API 请求流式转发给后端，便于前后端联调。
 */
const server = http.createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || "/", `http://${request.headers.host || host}`);
    if (requestUrl.pathname.startsWith("/api/")) {
      proxyApi(request, response);
      return;
    }
    if (requestUrl.pathname.startsWith("/prototypes/")) {
      const prototypePath = requestUrl.pathname.slice("/prototypes".length);
      await serveStatic(prototypePath, request, response, prototypeDirectory);
      return;
    }
    await serveStatic(requestUrl.pathname, request, response, publicDirectory);
  } catch (error) {
    console.error("前端开发服务器处理请求失败:", error);
    if (!response.headersSent) {
      response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    }
    response.end("前端开发服务器内部错误");
  }
});

/**
 * 将 API 请求和响应按流传输，避免缓冲问答接口的 SSE 数据。
 */
function proxyApi(request, response) {
  const targetUrl = new URL(request.url || "/", backendUrl);
  const requestClient = targetUrl.protocol === "https:" ? https : http;
  const headers = { ...request.headers, host: targetUrl.host };

  // 1. 原样转发请求方法、路径与请求体。
  const proxyRequest = requestClient.request(targetUrl, {
    method: request.method,
    headers
  }, proxyResponse => {
    // 2. 禁用代理侧缓存，让 SSE 数据到达后立即写给浏览器。
    const responseHeaders = {
      ...proxyResponse.headers,
      "cache-control": "no-cache",
      "x-accel-buffering": "no"
    };
    response.writeHead(proxyResponse.statusCode || 502, responseHeaders);
    proxyResponse.pipe(response);
  });

  proxyRequest.on("error", error => {
    console.error(`无法连接后端 ${backendUrl.origin}:`, error.message);
    if (!response.headersSent) {
      response.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    }
    response.end(JSON.stringify({
      error: "BACKEND_UNAVAILABLE",
      message: `本地后端不可用: ${backendUrl.origin}`
    }));
  });

  request.pipe(proxyRequest);
}

/**
 * 从 public 目录提供静态资源，并将根路径映射到正式聊天页面。
 */
async function serveStatic(requestPath, request, response, rootDirectory) {
    const decodedPath = decodeURIComponent(requestPath === "/" ? "/stockwise-chat-soft.html" : requestPath);
  const relativePath = decodedPath.replace(/^[/\\]+/, "");
  const filePath = path.resolve(rootDirectory, relativePath);
  const publicRoot = path.resolve(rootDirectory);

  // 1. 拒绝任何越过 public 目录的路径。
  if (filePath !== publicRoot && !filePath.startsWith(`${publicRoot}${path.sep}`)) {
    response.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("禁止访问");
    return;
  }

  let fileStats;
  try {
    fileStats = await stat(filePath);
  } catch {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("页面不存在");
    return;
  }

  if (!fileStats.isFile()) {
    response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
    response.end("页面不存在");
    return;
  }

  const contentType = contentTypes.get(path.extname(filePath).toLowerCase()) || "application/octet-stream";
  response.writeHead(200, {
    "Content-Type": contentType,
    "Content-Length": fileStats.size,
    "Cache-Control": "no-store"
  });
  if (request.method === "HEAD") {
    response.end();
    return;
  }
  createReadStream(filePath).pipe(response);
}

server.listen(port, host, () => {
  console.log(`StockWise 前端: http://${host}:${port}`);
  console.log(`API 代理目标: ${backendUrl.origin}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}

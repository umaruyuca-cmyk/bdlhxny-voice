import http from "node:http";
import https from "node:https";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const host = process.env.HOST || "127.0.0.1";
const port = Number.parseInt(process.env.PORT || "8082", 10);
const backendUrl = new URL(process.env.BDLH_RUNTIME_BACKEND_URL || "http://127.0.0.1:8081");
const analysisUrl = new URL(process.env.BDLH_RUNTIME_ANALYSIS_URL || "http://127.0.0.1:8000");
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
      proxyApi(request, response, apiTarget(requestUrl.pathname));
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
function proxyApi(request, response, upstream) {
  const targetUrl = new URL(request.url || "/", upstream);
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
    console.error(`无法连接后端 ${upstream.origin}:`, error.message);
    if (!response.headersSent) {
      response.writeHead(502, { "Content-Type": "application/json; charset=utf-8" });
    }
    response.end(JSON.stringify({
      error: "BACKEND_UNAVAILABLE",
      message: `本地后端不可用: ${upstream.origin}`
    }));
  });

  request.pipe(proxyRequest);
}

/**
 * 新版聊天由 Python Cognitive Orchestrator 提供；认证和用户领域仍由 Java 提供。
 */
function apiTarget(pathname) {
  // 认证由 Java 签发和校验 JWT，不能跟随聊天路由改动而意外切到 Python。
  if (pathname.startsWith("/api/v1/auth/")) {
    return backendUrl;
  }
  // Python Orchestrator：聊天、会话目录、Pause/Cancel 控制面。
  if (
    pathname.startsWith("/api/v1/chat/")
    || pathname.startsWith("/api/v1/conversations")
    || pathname.startsWith("/api/v1/agent-runs")
  ) {
    return analysisUrl;
  }
  return backendUrl;
}

/**
 * 从 public 目录提供静态资源；/agent 是唯一助手入口，/workspace 重定向到 /agent。
 */
async function serveStatic(requestPath, request, response, rootDirectory) {
  // 1. 保持文档目录有尾部斜杠，确保相对 CSS/图片资源在开发服务器中正确解析。
  if (requestPath === "/docs") {
    response.writeHead(302, { Location: "/docs/" });
    response.end();
    return;
  }
  if (requestPath === "/skills") {
    response.writeHead(302, { Location: "/skills/" });
    response.end();
    return;
  }
  if (requestPath === "/workspace" || requestPath === "/workspace/") {
    response.writeHead(301, { Location: "/agent" });
    response.end();
    return;
  }
  let target = requestPath;
  if (requestPath === "/") target = "/index.html";
  else if (requestPath === "/agent" || requestPath === "/agent/") target = "/chat.html";
  else if (requestPath.startsWith("/agent/")) target = "/chat.html";
  else if (requestPath === "/docs" || requestPath === "/docs/") target = "/docs/index.html";
  else if (requestPath.startsWith("/docs/")) {
    const docPath = requestPath.slice("/docs/".length);
    target = "/docs/" + (docPath.endsWith(".html") || docPath.includes(".") ? docPath : docPath + ".html");
  }
  else if (requestPath === "/skills" || requestPath === "/skills/") target = "/skills/index.html";
  else if (requestPath.startsWith("/skills/")) {
    const skillPath = requestPath.slice("/skills/".length);
    target = "/skills/" + (skillPath.endsWith(".html") || skillPath.includes(".") ? skillPath : skillPath + ".html");
  }
  const decodedPath = decodeURIComponent(target);
  const relativePath = decodedPath.replace(/^[/\\]+/, "");
  const filePath = path.resolve(rootDirectory, relativePath);
  const publicRoot = path.resolve(rootDirectory);

  // 2. 拒绝任何越过 public 目录的路径。
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
  console.log(`BDLH Agent Runtime 前端: http://${host}:${port}`);
  console.log(`Java API: ${backendUrl.origin}`);
  console.log(`Python Analysis API: ${analysisUrl.origin}`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}

import http from "node:http";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { redirectFor } from "./scripts/redirect-map.mjs";
import { ownerApiRegExp } from "./scripts/owner-api-allowlist.mjs";

const host = process.env.HOST || "127.0.0.1";
const port = Number.parseInt(process.env.PORT || "8082", 10);
const publicDirectory = fileURLToPath(new URL("./public/", import.meta.url));
// 开发代理:把匿名公共测试接口转发到本地 engine,「实验 / 我的测试」页可端到端联调。
// 默认开启并指向本地 engine(127.0.0.1:8090,与 deploy/.env 的 ENGINE_PORT 一致);
// 设 RUN_API_PROXY=off 可恢复纯静态行为(与公开部署一致),或指向其他地址。
const runApiProxyRaw = process.env.RUN_API_PROXY || "http://127.0.0.1:8090";
const runApiProxy = /^(off|0|false|none)$/i.test(runApiProxyRaw) ? "" : runApiProxyRaw.replace(/\/+$/, "");

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".png", "image/png"],
  [".ico", "image/x-icon"]
]);

/**
 * 对照评测展示站：纯静态页面，无后端代理。
 */
const server = http.createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || "/", `http://${request.headers.host || host}`);
    await serveStatic(requestUrl.pathname, request, response);
  } catch (error) {
    console.error("前端开发服务器处理请求失败:", error);
    if (!response.headersSent) {
      response.writeHead(500, { "Content-Type": "text/plain; charset=utf-8" });
    }
    response.end("前端开发服务器内部错误");
  }
});

async function serveStatic(requestPath, request, response) {
  // 开发代理(可选):匿名公共接口 + 实验页所有者通道(登录/模板/plan/批次/作业/
  // 实验组/统计),与 nginx.conf 的反代白名单共用同一份常量(scripts/owner-api-allowlist.mjs);
  // 仅显式配置 RUN_API_PROXY 时启用
  const ownerApiPattern = ownerApiRegExp();
  if (runApiProxy && (requestPath.startsWith("/api/v1/public/") || ownerApiPattern.test(requestPath))) {
    const target = new URL(runApiProxy + request.url);
    const proxied = http.request(
      target,
      { method: request.method, headers: { ...request.headers, host: target.host } },
      (upstream) => {
        response.writeHead(upstream.statusCode || 502, upstream.headers);
        upstream.pipe(response);
      },
    );
    proxied.on("error", () => {
      response.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("运行服务不可达:engine 未启动或 RUN_API_PROXY 配置错误");
    });
    request.pipe(proxied);
    return;
  }
  // 批次详情 /experiment/batch/<id>:静态站无服务端路由,统一落到 batch.html
  // (与 nginx 的 try_files 同口径;批次标识由页面从 pathname 解析)
  if (requestPath.startsWith("/experiment/batch/")) {
    await serveStaticFile("/experiment/batch.html", response);
    return;
  }
  // 实验组详情 /experiment/series/<id>:同 nginx,统一落到 series.html
  // (样本积累 + 统计快照 + 逐样本追加;修复方案 P0-2 本地路由对齐)
  if (requestPath.startsWith("/experiment/series/")) {
    await serveStaticFile("/experiment/series.html", response);
    return;
  }
  // 上下文构建详情 /experiment/context-builds/<id>:落到 context-build.html
  if (requestPath.startsWith("/experiment/context-builds/")) {
    await serveStaticFile("/experiment/context-build.html", response);
    return;
  }
  // 旧路径 301(任务六 §11:/docs/* 页面与 /showcase/context 迁至七模块新位置;
  // /docs/ 下的 css/js 资产保留原位,不在映射内)
  const redirect = redirectFor(requestPath);
  if (redirect) {
    response.writeHead(301, { Location: redirect });
    response.end();
    return;
  }
  // 模块前缀(五模块首页 + 子模块):无尾斜杠 302 到模块首页;{page} 自动补 .html
  const MODULE_PREFIXES = ["/about", "/tools", "/cases", "/showcase", "/experiment", "/test", "/context", "/judging", "/engine", "/ops", "/assets", "/docs"];
  if (MODULE_PREFIXES.includes(requestPath)) {
    response.writeHead(302, { Location: requestPath + "/" });
    response.end();
    return;
  }
  const DIRECTORY_INDEX = ["/about/", "/tools/", "/cases/", "/showcase/", "/experiment/", "/test/", "/context/", "/judging/", "/engine/", "/ops/", "/assets/", "/docs/"];
  // 模块子页带尾斜杠(/experiment/compression/)301 去斜杠:子页是 *.html 文件
  // 不是目录;目录索引(如 /experiment/ 自身)除外。与 nginx 的去斜杠 rewrite 同口径。
  if (requestPath !== "/" && requestPath.endsWith("/")) {
    const stripped = requestPath.replace(/\/+$/, "");
    if (DIRECTORY_INDEX.some((prefix) => stripped.startsWith(prefix) && stripped !== prefix)) {
      response.writeHead(301, { Location: stripped });
      response.end();
      return;
    }
  }
  let target = requestPath;
  if (requestPath === "/") target = "/index.html";
  else if (DIRECTORY_INDEX.includes(requestPath)) target = requestPath + "index.html";
  else {
    const modulePrefix = DIRECTORY_INDEX.find((prefix) => requestPath.startsWith(prefix));
    if (modulePrefix && !requestPath.slice(modulePrefix.length).includes(".")) {
      target = requestPath + ".html";
    }
  }
  const decodedPath = decodeURIComponent(target);
  const relativePath = decodedPath.replace(/^[/\\]+/, "");
  const filePath = path.resolve(publicDirectory, relativePath);
  const publicRoot = path.resolve(publicDirectory);

  // 拒绝任何越过 public 目录的路径。
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

  await streamFile(filePath, fileStats, request, response);
}

/** 按扩展名输出静态文件(统一 no-store;HEAD 不输出正文)。 */
async function serveStaticFile(relativeTarget, response) {
  const decodedPath = decodeURIComponent(relativeTarget);
  const relative = decodedPath.replace(/^[/\\]+/, "");
  const filePath = path.resolve(publicDirectory, relative);
  const publicRoot = path.resolve(publicDirectory);
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
  await streamFile(filePath, fileStats, { method: "GET" }, response);
}

async function streamFile(filePath, fileStats, request, response) {
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
  console.log(`对照评测展示站: http://${host}:${port}/`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}

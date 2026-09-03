import http from "node:http";
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { redirectFor } from "./scripts/redirect-map.mjs";

const host = process.env.HOST || "127.0.0.1";
const port = Number.parseInt(process.env.PORT || "8082", 10);
const publicDirectory = fileURLToPath(new URL("./public/", import.meta.url));

const contentTypes = new Map([
  [".html", "text/html; charset=utf-8"],
  [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
  [".png", "image/png"],
  [".ico", "image/x-ico"],
]);

/**
 * 展示站开发服务器:纯静态,无后端代理。
 * 五页架构(/ /results/ /evidence/ /system/ /methodology/)+ 静态资产
 * (/docs/*.css|js、/showcase-data/*)+ 旧地址 301(redirect-map)。
 */
// 唯一后端依赖(窄代理):真实运行演示页读取系统演示账号的只读执行数据。
// 仅放行 GET 且前缀匹配的演示端点;其余请求一律静态服务,不代理任何 API。
const DEMO_API_PREFIX = "/api/v1/public/context-demo";

async function proxyDemoApi(request, response, pathname) {
  if (request.method !== "GET" || !pathname.startsWith(DEMO_API_PREFIX)) {
    return false;
  }
  try {
    const search = new URL(request.url || '/', 'http://localhost').search;
    const upstream = await fetch(`http://127.0.0.1:8090${pathname}${search}`, {
      headers: { Accept: "application/json" },
    });
    const body = await upstream.text();
    response.writeHead(upstream.status, { "Content-Type": "application/json; charset=utf-8" });
    response.end(body);
  } catch {
    response.writeHead(503, { "Content-Type": "application/json; charset=utf-8" });
    response.end('{"enabled":false,"error":"DEMO_API_UNAVAILABLE"}');
  }
  return true;
}

const server = http.createServer(async (request, response) => {
  try {
    const requestUrl = new URL(request.url || "/", `http://${request.headers.host || host}`);
    if (await proxyDemoApi(request, response, requestUrl.pathname)) {
      return;
    }
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
  // 单次运行证据链 /evidence/run/?id=<run_id>:静态站无服务端路由,
  // 统一落到 run.html,由页面解析查询参数(与 nginx try_files 同口径)。
  if (requestPath === "/evidence/run" || requestPath.startsWith("/evidence/run/")) {
    await serveStaticFile("/evidence/run.html", response);
    return;
  }
  // 旧路径 301 到五页新位置(redirect-map 与 nginx 同一映射;静态资产不在映射内)
  const redirect = redirectFor(requestPath);
  if (redirect) {
    response.writeHead(301, { Location: redirect });
    response.end();
    return;
  }
  // 页面模块前缀:无尾斜杠 302 到模块首页
  const MODULE_PREFIXES = ["/results", "/evidence", "/system", "/methodology", "/work"];
  if (MODULE_PREFIXES.includes(requestPath)) {
    response.writeHead(302, { Location: requestPath + "/" });
    response.end();
    return;
  }
  const DIRECTORY_INDEX = ["/results/", "/evidence/", "/system/", "/methodology/", "/work/"];
  // 模块子页带尾斜杠(/evidence/run/)301 去斜杠:子页是 *.html 文件不是目录;
  // 目录索引(/evidence/ 自身)除外
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
  console.log(`实验与证据展示站: http://${host}:${port}/`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}

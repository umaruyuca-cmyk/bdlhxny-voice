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
  // 旧路径 301(任务六 §11:/docs/* 页面与 /showcase/context 迁至七模块新位置;
  // /docs/ 下的 css/js 资产保留原位,不在映射内)
  const redirect = redirectFor(requestPath);
  if (redirect) {
    response.writeHead(301, { Location: redirect });
    response.end();
    return;
  }
  // 模块前缀(机甲首页 + 六模块):无尾斜杠 302 到模块首页;{page} 自动补 .html
  const MODULE_PREFIXES = ["/about", "/showcase", "/lab", "/experiment", "/context", "/judging", "/engine", "/ops"];
  if (MODULE_PREFIXES.includes(requestPath)) {
    response.writeHead(302, { Location: requestPath + "/" });
    response.end();
    return;
  }
  let target = requestPath;
  const DIRECTORY_INDEX = ["/about/", "/showcase/", "/lab/", "/experiment/", "/context/", "/judging/", "/engine/", "/ops/"];
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

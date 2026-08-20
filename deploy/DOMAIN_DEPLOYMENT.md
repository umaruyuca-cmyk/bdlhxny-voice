# BDLH Agent Runtime 域名接入与公网端口收口

正式网站统一使用 `https://bdlhxny.com`。浏览器只访问同源页面和 `/api/v1/*`；内部 Backend、搜索适配器、数据库和 MCP 原始端口不得继续直接暴露在公网。

`stock-wrapper`（旧 `:3001`）已退役并停止部署；勿再为其配置环境变量或公网/内网依赖。正式分析由 Python Orchestrator（`:8090`）承担。

## 1. 域名规划

| 用途 | 公网地址 | Nginx 上游 |
| --- | --- | --- |
| 网站与前端 | `https://bdlhxny.com` | Frontend `127.0.0.1:8082` |
| Python Agent API | `https://bdlhxny.com/api/v1/chat/*`、`/api/v1/conversations*`、`/api/v1/agent-runs*`、`/api/v1/financial-tasks*`、`/api/v1/notifications*` | `127.0.0.1:8090` |
| Java 认证与用户数据 | `https://bdlhxny.com/api/auth/*`、`/api/portfolio/*`、`/api/user/*` 等 | `127.0.0.1:8081` |
| Web Search | `https://bdlhxny.com/api/search` | `127.0.0.1:3002/api/search` |
| akshare Streamable HTTP MCP | 无（内对内回环，不公网暴露） | `127.0.0.1:8083/mcp` |
| cn-financial SSE MCP | 无（内对内回环，不公网暴露） | `127.0.0.1:8000/sse` |

两个金融 MCP 已改为内对内回环直连（orchestrator 与 MCP 同机，直接走 `127.0.0.1`），不再通过公网子域名暴露，因此无需为其配置公网域名或证书。

## 2. DNS 与证书

为 `bdlhxny.com`、`www.bdlhxny.com` 创建指向服务器的 A/AAAA 记录。证书覆盖这两个域名即可（MCP 已内对内回环，不再需要公网子域名与证书）：

```bash
sudo certbot --nginx \
  -d bdlhxny.com \
  -d www.bdlhxny.com
```

将 `deploy/nginx/bdlh-runtime.conf` 安装到服务器 Nginx 配置目录，按实际证书名称调整路径，然后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

不得再用通用 `location /api/` 把全部流量打到单一上游。路由必须明确为：

- `/api/v1/chat/*`、`/api/v1/conversations*`、`/api/v1/agent-runs*`、`/api/v1/financial-tasks*`、`/api/v1/notifications*` → Python Orchestrator；
- `/api/auth/*`、`/api/portfolio/*`、`/api/user/*` 等用户数据与认证 → Java Backend；
- `/api/search` → Web Search Adapter；
- 其他页面 → Frontend；
- 不得再出现指向已退役 `stock-wrapper:3001` 的路由或环境变量。

## 3. 应用配置

正式环境使用：

```env
AKSHARE_ONE_MCP_ENDPOINT=http://127.0.0.1:8083/mcp
CN_FINANCIAL_MCP_ENDPOINT=http://127.0.0.1:8000/sse
WEB_SEARCH_ENDPOINT_URL=https://bdlhxny.com/api/search
```

服务器上的内部服务仍使用回环地址或 Docker 服务名，不能为了“统一域名”把数据库、Redis、Ollama、Java Backend、Python Orchestrator 或 Web Search Adapter 的内部连接绕到公网。不要配置 `STOCK_WRAPPER_*`。

## 4. 发布与验收顺序

1. 添加 DNS 记录并签发覆盖全部域名的证书。
2. 部署最新版 Python Orchestrator、Java Backend、Frontend 和边缘 Nginx 配置。
3. 先从服务器本机验证 `127.0.0.1:8090/8081/8082/3002/8000/8083`（不再验证已退役的 `3001`）。
4. 从公网验证 HTTPS 页面、Python Agent API、Java 认证/数据 API、搜索接口（MCP 已内对内回环，无需公网验证）。
5. 确认 SSE 持续输出且没有被 Nginx 缓冲。
6. 在云安全组和主机防火墙关闭内部端口。
7. 再次从公网确认内部端口不可连接、80 自动跳转 443、443 服务正常。

最低验收项：

```bash
curl -I http://bdlhxny.com/
curl -I https://bdlhxny.com/
curl -I 'https://bdlhxny.com/agent?name=stock'
curl -I https://bdlhxny.com/docs
curl -i -N --max-time 5 http://127.0.0.1:8000/sse
curl -i --max-time 5 \
  -H 'Accept: application/json, text/event-stream' \
  http://127.0.0.1:8083/mcp
```

`/api/search` 是 POST 接口，不能用 GET 返回 404 判断部署失败。应携带合法的 `X-Agent-Id`、`X-Search-Token` 和请求体做验收，但不要把 Token 写入仓库或命令历史。

## 5. 公网端口关闭清单

公网安全组原则上只保留 TCP 80、443；TCP 22 仅允许固定运维来源 IP。以下端口应从公网入站规则中删除，并同时检查主机防火墙与进程监听地址：

| 端口 | 服务 | 正确可见范围 | 公网动作 |
| --- | --- | --- | --- |
| `3001/tcp` | 已退役 stock-wrapper | 不应再监听 | 关闭；进程与容器应已停止 |
| `3002/tcp` | Web Search Adapter | Docker 内网或回环，由 `/api/search` 代理 | 关闭 |
| `8000/tcp` | cn-financial MCP | 回环，仅本机 orchestrator 访问 | 关闭 |
| `8080/tcp` | SearXNG 或本地 Backend | Docker 内网或回环 | 关闭 |
| `8081/tcp` | Java Backend（云端） | 回环，由认证/用户数据路径代理 | 关闭 |
| `8090/tcp` | Python Orchestrator | 回环，由 Agent API 路径代理 | 关闭 |
| `8082/tcp` | Frontend 容器 | 回环，由主域名代理 | 关闭 |
| `8083/tcp` | akshare MCP | 回环，仅本机 orchestrator 访问 | 关闭 |
| `3306/tcp` | MySQL | 私网/本机 | 关闭；跨机时只放行指定私网来源 |
| `5432/tcp` | PostgreSQL | 私网/本机 | 关闭；跨机时只放行指定私网来源 |
| `6379/tcp` | Redis | 私网/本机 | 关闭；不得直接暴露公网 |
| `11434/tcp` | Ollama | 私网/受控隧道 | 关闭；仅放行受控来源 |

检查监听和防火墙：

```bash
sudo ss -lntp
sudo ufw status numbered
sudo nft list ruleset
```

如果使用 UFW，可在确认 80、443 和受限 SSH 规则已生效后关闭应用端口：

```bash
sudo ufw deny 3001/tcp
sudo ufw deny 3002/tcp
sudo ufw deny 8000/tcp
sudo ufw deny 8080/tcp
sudo ufw deny 8081/tcp
sudo ufw deny 8082/tcp
sudo ufw deny 8083/tcp
sudo ufw deny 3306/tcp
sudo ufw deny 5432/tcp
sudo ufw deny 6379/tcp
sudo ufw deny 11434/tcp
```

云厂商安全组和 UFW/nftables 是两层控制，必须同时收口。不要在未确认 SSH 白名单前修改 22 端口规则。

## 6. 回滚

保留上一份已验证的 Nginx 配置。新配置异常时恢复旧配置并重新加载 Nginx，不要重新开放数据库、Redis、Ollama 或内部应用端口作为长期回滚手段；也不得通过恢复 stock-wrapper 作为回滚手段。

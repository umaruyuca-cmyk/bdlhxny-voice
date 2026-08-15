# BDLH Agent Runtime 域名接入与公网端口收口

正式网站统一使用 `https://bdlhxny.com`。浏览器只访问同源页面和 `/api/v1/*`；内部 Backend、Wrapper、数据库和 MCP 原始端口不得继续直接暴露在公网。

## 1. 域名规划

| 用途 | 公网地址 | Nginx 上游 |
| --- | --- | --- |
| 网站与 Java API | `https://bdlhxny.com` | Frontend `127.0.0.1:8082`；`/api/v1/*` → `127.0.0.1:8081` |
| Web Search | `https://bdlhxny.com/api/search` | `127.0.0.1:3002/api/search` |
| akshare Streamable HTTP MCP | `https://akshare-mcp.bdlhxny.com/mcp` | `127.0.0.1:8083/mcp` |
| cn-financial SSE MCP | `https://cn-financial-mcp.bdlhxny.com/sse` | `127.0.0.1:8000/sse` |

cn-financial 使用旧版 SSE 传输，握手后会返回同源 `/messages/` 回调地址，因此使用独立子域名，不把它挂到主站的多级路径下面。

## 2. DNS 与证书

为 `bdlhxny.com`、`www.bdlhxny.com`、`akshare-mcp.bdlhxny.com` 和 `cn-financial-mcp.bdlhxny.com` 创建指向同一服务器的 A/AAAA 记录。证书必须覆盖全部域名，例如：

```bash
sudo certbot --nginx \
  -d bdlhxny.com \
  -d www.bdlhxny.com \
  -d akshare-mcp.bdlhxny.com \
  -d cn-financial-mcp.bdlhxny.com
```

将 `deploy/nginx/bdlh-runtime.conf` 安装到服务器 Nginx 配置目录，按实际证书名称调整路径，然后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

不得再用通用 `location /api/` 指向 Stock Wrapper。路由必须明确为：

- `/api/v1/*` → Java Backend；
- `/api/search` → Web Search Wrapper；
- 其他页面 → Frontend。

## 3. 应用配置

正式环境使用：

```env
AKSHARE_ONE_MCP_ENDPOINT=https://akshare-mcp.bdlhxny.com/mcp
CN_FINANCIAL_MCP_ENDPOINT=https://cn-financial-mcp.bdlhxny.com/sse
WEB_SEARCH_ENDPOINT_URL=https://bdlhxny.com/api/search
```

服务器上的内部服务仍使用回环地址或 Docker 服务名，不能为了“统一域名”把数据库、Redis、Ollama、Java Backend 或 Wrapper 的内部连接绕到公网。

## 4. 发布与验收顺序

1. 添加 DNS 记录并签发覆盖全部域名的证书。
2. 部署最新版 Backend、Frontend 和边缘 Nginx 配置。
3. 先从服务器本机验证 `127.0.0.1:8081/8082/3001/3002/8000/8083`。
4. 从公网验证 HTTPS 页面、Java API、搜索接口和两个 MCP 域名。
5. 确认 SSE 持续输出且没有被 Nginx 缓冲。
6. 在云安全组和主机防火墙关闭内部端口。
7. 再次从公网确认内部端口不可连接、80 自动跳转 443、443 服务正常。

最低验收项：

```bash
curl -I http://bdlhxny.com/
curl -I https://bdlhxny.com/
curl -I 'https://bdlhxny.com/agent?name=stock'
curl -I https://bdlhxny.com/docs
curl -i -N --max-time 5 https://cn-financial-mcp.bdlhxny.com/sse
curl -i --max-time 5 \
  -H 'Accept: application/json, text/event-stream' \
  https://akshare-mcp.bdlhxny.com/mcp
```

`/api/search` 是 POST 接口，不能用 GET 返回 404 判断部署失败。应携带合法的 `X-Agent-Id`、`X-Search-Token` 和请求体做验收，但不要把 Token 写入仓库或命令历史。

## 5. 公网端口关闭清单

公网安全组原则上只保留 TCP 80、443；TCP 22 仅允许固定运维来源 IP。以下端口应从公网入站规则中删除，并同时检查主机防火墙与进程监听地址：

| 端口 | 服务 | 正确可见范围 | 公网动作 |
| --- | --- | --- | --- |
| `3001/tcp` | Stock Wrapper | Docker 内网或回环 | 关闭 |
| `3002/tcp` | Web Search Wrapper | Docker 内网或回环，由 `/api/search` 代理 | 关闭 |
| `8000/tcp` | cn-financial MCP | 回环，由 MCP 子域名代理 | 关闭 |
| `8080/tcp` | SearXNG 或本地 Backend | Docker 内网或回环 | 关闭 |
| `8081/tcp` | Java Backend（云端） | 回环，由 `/api/v1/*` 代理 | 关闭 |
| `8082/tcp` | Frontend 容器 | 回环，由主域名代理 | 关闭 |
| `8083/tcp` | akshare MCP | 回环，由 MCP 子域名代理 | 关闭 |
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

保留上一份已验证的 Nginx 配置。新配置异常时恢复旧配置并重新加载 Nginx，不要重新开放数据库、Redis、Ollama 或 Wrapper 端口作为长期回滚手段。

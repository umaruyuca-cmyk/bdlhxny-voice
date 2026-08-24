# bdlh-web-search-adapter 云端部署

## 1. 构建

```bash
docker build -t bdlh-web-search-adapter:0.1.0 .
```

## 2. 启动

`SEARXNG_URL` 必须指向云服务器内网中的 SearXNG，不能指向公网 `/api/search`。

```bash
docker run -d \
  --name bdlh-web-search-adapter \
  --restart unless-stopped \
  --add-host host.docker.internal:host-gateway \
  -p 127.0.0.1:3002:3002 \
  -e PORT=3002 \
  -e SEARXNG_URL=http://host.docker.internal:8080 \
  -e SEARXNG_ENGINES=baidu,360search \
  -e 'WEB_SEARCH_AGENTS_JSON={"bdlh_runtime":"替换为至少32位的独立Token"}' \
  bdlh-web-search-adapter:0.1.0
```

## 3. Nginx 转发

```nginx
location = /api/search {
    proxy_pass http://127.0.0.1:3002/api/search;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Agent-Id $http_x_agent_id;
    proxy_set_header X-Search-Token $http_x_search_token;
    proxy_connect_timeout 5s;
    proxy_read_timeout 20s;
}
```

重新加载 Nginx 后，本地 Agent 使用：

```env
WEB_SEARCH_ENDPOINT_URL=https://bdlhxny.com/api/search
WEB_SEARCH_AGENT_ID=bdlh_runtime
WEB_SEARCH_AGENT_TOKEN=与云端配置一致的Token
```

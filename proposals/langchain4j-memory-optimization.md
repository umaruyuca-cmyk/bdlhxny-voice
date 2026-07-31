# LangChain4j 记忆与上下文管理优化方案

> **状态（2026-07-30）**：第一阶段上下文窗口与第二阶段长期情景记忆向量化均已实施。LangChain4j 接管上下文裁剪视图和情景记忆的 `EmbeddingStore<TextSegment>` 抽象，但不接管 Redis 状态、完整归档、知识入库或 ReAct 编排。
>
> **重要**：本文原 Step 1-10 保留为历史草案，不得继续照抄执行。全局单例 ChatMemory、`PgChatMemoryStore` 替代完整历史、直接复用 `knowledge_chunks`、第二套 Ollama Embedding 客户端等设计均已否决。

## 校正版实施结论

第一阶段已经完成：

1. 使用 LangChain4j BOM 和核心模块，不添加 `langchain4j-pgvector`、`langchain4j-ollama` 或 jtokkit。
2. Redis `SessionState` + Lua CAS 继续作为短期工作记忆唯一真相源。
3. `ConversationMessage` 替代 `SessionState.history` 的 `List<Object>`，并兼容旧版 Redis JSON。
4. `LangChainContextWindow` 每次请求创建独立 `TokenWindowChatMemory`，先限制消息数，再限制 Token，不配置 `ChatMemoryStore`。
5. 本地模型与付费模型使用不同记忆预算；跨会话摘要、单条消息分别受限，当前问题始终单独保留。
6. PG `conversation_history` 继续保存完整会话，PgVector 知识检索和确认入库逻辑保持不变。
7. ReAct、Route 白名单、PaidGate、Agent Run 审计保持不变。

## 第二阶段：长期情景记忆（已完成）

本阶段落地以下边界：

1. `conversation_history` 继续保存完整消息和确定性摘要，是可审计、可恢复的长期记忆真相源。
2. 新增 `conversation_episode_embeddings`，只保存会话摘要的向量索引。该表可从完整归档重建，不能替代原始会话。
3. `LangChainEpisodicEmbeddingStore` 实现 LangChain4j 的 `EmbeddingStore<TextSegment>`，把 LangChain4j 的 `Embedding`、`TextSegment`、`Metadata` 转换为 StockWise 自有 MyBatis/PgVector SQL。
4. 向量仍由现有 Spring AI `EmbeddingService` 调用云端 Ollama 生成，避免创建第二套 Embedding 客户端。
5. 检索必须包含 `user_id` 过滤；有标的时同时按 `symbol` 过滤，再按语义相似度与时间衰减综合排序。
6. 新会话只注入命中的 Top-K 摘要，且 Prompt 明确历史结论不得覆盖最新 Skill、行情或搜索事实。
7. 完整会话先归档，向量索引后写入。Ollama、PgVector 失败或旧归档尚无索引时保留原始归档，并在检索阶段降级为最近摘要。
8. Redis `SessionState` + Lua CAS、Route、PaidGate、Bounded ReAct、知识库 `knowledge_chunks` 均保持原有职责。

### 数据流

```text
会话收档
  ├─ 先写 conversation_history（必须成功）
  └─ 摘要 → Spring AI EmbeddingService
            → LangChain4j Embedding/TextSegment
            → conversation_episode_embeddings（允许失败并降级）

新会话
  └─ 当前问题 + userId + symbol
       → LangChain4j EmbeddingStore.search
       → 用户隔离 + 标的过滤 + 语义相似度 + 时间衰减
       → Top-K 摘要
       → LangChain4j TokenWindowChatMemory 统一预算裁剪
       → 本地模型或 PaidGate 后的分析模型
```

### 检索评分

默认综合分：

```text
score = 0.85 × cosine_similarity
      + 0.15 × recency_score

recency_score = 1 / (1 + age_days / 30)
```

`min-similarity` 只约束原始余弦相似度，不使用时间分掩盖语义不相关。所有参数均可通过 `stockwise.memory.episodic-vector` 配置覆盖。

### 明确不做

- 不建立全局单例 `ChatMemory`。
- 不把完整会话只保存成 LangChain4j 消息 JSON。
- 不复用 `knowledge_chunks` 存用户会话，避免用户私有记忆与公共知识混库。
- 不让历史行情或旧分析结论覆盖当前工具事实。
- 本阶段不调用模型二次总结，先使用确定性摘要；后续可增加本地模型结构化摘要，并保留确定性回退。

---

## 历史草案（禁止直接执行）

> **原用途**：驱动编码 AI 将当前的上下文管理和知识检索模块迁移到 LangChain4j，同时保留已有的 BoundedReactLoop / Route / PaidGate / AgentOrchestrator 不变。
> **原原则**：LangChain4j 只接管记忆、上下文窗口、知识检索/入库三块；Tools 调用、ReAct 循环、路由白名单、付费门禁保持现有 Java 实现。
> **约束**：所有现有测试必须保持通过，中文编码无乱码，不得删除已有方法的 Javadoc。

---

## 一、当前现状

### 当前依赖（pom.xml）

```
Spring Boot 3.4.1, Java 17
Spring AI 1.0.0 (OpenAI + Ollama starter)
MyBatis-Plus 3.5.9
PostgreSQL + pgvector
Redis (Lettuce)
dynamic-datasource 4.3.1
```

### 待替换组件（4 个文件）

| 当前类 | 行数 | 问题 |
|--------|------|------|
| `AgentContextBuilder` | ~80 | 手动字符串截断(1200字符硬编码)，无 token 计数 |
| `ConversationHistoryService` | ~45 | 手动拼 SQL LIMIT 有注入风险，`List<Object>` 无类型安全 |
| `KnowledgeRetrievalService` | ~35 | 手写 pgvector 检索，无元数据过滤 |
| `KnowledgeIngestService` | ~70 | 手写去重、手写过期检查、重复 MIN_CONFIDENCE 常量 |

### 必须原样保留的组件

| 类 | 保留原因 |
|----|---------|
| `BoundedReactLoop` | 确定性 Action 计划，LangChain4j 的 Agent 无法替代 |
| `RouteExecutionPolicyRegistry` | 代码级硬白名单 |
| `PaidModelGate` | 业务特有 8 条件校验 |
| `MemoryRouter` | 门面不变，底层实现切换到 LangChain4j |
| `AgentRunService` | 自定义审计结构 |
| `SessionStateService` + Redis CAS | LangChain4j 不支持乐观锁 |
| `ExplicitAnalysisExecutor` | 路由分发，调用接口不变 |
| `AgentOrchestrator` | SSE 生命周期管理 |
| `StockSkillContractValidator` | 契约校验 |
| `HttpStockAnalysisGateway` | HTTP 网关 |
| `StockTools` | @Tool 注解方法 |

---

## 二、目标架构

```
MemoryRouter (门面，公开 API 不变)
├── SessionStateService ──→ Redis + CAS Lua 脚本（保留）
├── ChatMemory ──→ LangChain4j MessageWindowChatMemory
│   └── ChatMemoryStore ──→ PostgreSQL（替代 AgentContextBuilder + ConversationHistoryService）
├── EmbeddingStore<TextSegment> ──→ PgVectorEmbeddingStore
│   └── EmbeddingStoreIngestor ──→ 自动分段/去重/入库（替代 KnowledgeRetrievalService + KnowledgeIngestService）
├── UserPortfolioService ──→ PostgreSQL（保留）
└── UserFeedbackService ──→ PostgreSQL（保留）

BoundedReactLoop + Route + PaidGate（保留不变）
```

---

## 三、具体实施步骤

### Step 1：添加依赖（pom.xml）

在 `<dependencies>` 块末尾（`</dependencies>` 之前）添加以下 4 个依赖：

```xml
<!-- LangChain4j 核心 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j</artifactId>
    <version>0.36.2</version>
</dependency>

<!-- LangChain4j 记忆与嵌入的 PG 实现需要 pgvector 扩展 -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-pgvector</artifactId>
    <version>0.36.2</version>
    <exclusions>
        <!-- 冲突排除：项目已有自己的 PostgreSQL 驱动 -->
        <exclusion>
            <groupId>org.postgresql</groupId>
            <artifactId>postgresql</artifactId>
        </exclusion>
    </exclusions>
</dependency>

<!-- LangChain4j Ollama 嵌入模型（复用本地 qwen3-embedding） -->
<dependency>
    <groupId>dev.langchain4j</groupId>
    <artifactId>langchain4j-ollama</artifactId>
    <version>0.36.2</version>
</dependency>

<!-- Token 计数：用于 ChatMemory 的窗口管理 -->
<dependency>
    <groupId>com.knuddels</groupId>
    <artifactId>jtokkit</artifactId>
    <version>1.1.0</version>
</dependency>
```

版本 0.36.2 理由：与 Spring Boot 3.4.x 兼容的稳定版本。

---

### Step 2：创建配置类 `LangChain4jConfig`

**新建文件** `src/main/java/com/stockwise/config/LangChain4jConfig.java`

```java
package com.stockwise.config;

import dev.langchain4j.memory.ChatMemory;
import dev.langchain4j.memory.chat.MessageWindowChatMemory;
import dev.langchain4j.memory.chat.TokenWindowChatMemory;
import dev.langchain4j.model.ollama.OllamaEmbeddingModel;
import dev.langchain4j.store.memory.chat.ChatMemoryStore;
import dev.langchain4j.store.embedding.EmbeddingStore;
import dev.langchain4j.store.embedding.pgvector.PgVectorEmbeddingStore;
import dev.langchain4j.data.segment.TextSegment;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

/**
 * LangChain4j 记忆与向量存储配置。
 * 与现有 Spring AI 模型共存，仅接管 ChatMemory 和 EmbeddingStore。
 */
@Configuration
public class LangChain4jConfig {

    @Value("${stockwise.chat-memory.max-messages:20}")
    private int maxMessages;

    @Value("${stockwise.chat-memory.max-tokens:4000}")
    private int maxTokens;

    @Value("${OLLAMA_BASE_URL:http://localhost:11434}")
    private String ollamaBaseUrl;

    @Value("${OLLAMA_EMBEDDING_MODEL:qwen3-embedding:0.6b}")
    private String embeddingModel;

    // ─── ChatMemory：消息窗口 + Token 窗口双层限制 ───

    /**
     * 创建双层窗口 ChatMemory。
     * MessageWindow 控制条数，TokenWindow 控制 token 总量，任一触发即裁剪最早消息。
     */
    @Bean
    public ChatMemory chatMemory(ChatMemoryStore chatMemoryStore) {
        // 1. 先按消息数限制（最多20轮），防止无限增长。
        // 2. 再按 token 数限制（最多4000 tokens），适配模型上下文窗口。
        MessageWindowChatMemory messageWindow = MessageWindowChatMemory.builder()
                .maxMessages(maxMessages)
                .chatMemoryStore(chatMemoryStore)
                .build();
        return TokenWindowChatMemory.builder()
                .maxTokens(maxTokens, new OpenAiTokenizer("gpt-4o")) // qwen3 token 分布接近 GPT-4o
                .chatMemoryStore(chatMemoryStore)
                .build();
    }

    // ─── ChatMemoryStore：PostgreSQL 持久化 ───

    /**
     * 自定义 PG ChatMemoryStore。
     * 必须实现自有 SQL，不使用 LangChain4j 默认的 JSON 列方案，
     * 以兼容项目现有的 dual-datasource 配置和 MyBatis-Plus 体系。
     */
    @Bean
    public ChatMemoryStore chatMemoryStore(DataSource dataSource) {
        return new PgChatMemoryStore(dataSource);
    }

    // ─── EmbeddingStore：PgVector ───

    /**
     * PgVector 向量存储，复用 knowledge_chunks 表（暂时保持单表）。
     * 后续双表迁移时只需改表名参数。
     */
    @Bean
    public EmbeddingStore<TextSegment> embeddingStore(
            @Value("${PG_URL:jdbc:postgresql://localhost:5432/stockwise}") String pgUrl,
            @Value("${PG_USER:postgres}") String pgUser,
            @Value("${PG_PASSWORD:postgres}") String pgPassword) {
        // 从 JDBC URL 提取 host:port/database
        String[] parts = pgUrl.replace("jdbc:postgresql://", "").split("/");
        String hostPort = parts[0];
        String database = parts.length > 1 ? parts[1].split("\\?")[0] : "stockwise";
        String host = hostPort.contains(":") ? hostPort.split(":")[0] : hostPort;
        int port = hostPort.contains(":") ? Integer.parseInt(hostPort.split(":")[1]) : 5432;

        return PgVectorEmbeddingStore.builder()
                .host(host)
                .port(port)
                .database(database)
                .user(pgUser)
                .password(pgPassword)
                .table("knowledge_chunks")
                .dimension(1024) // qwen3-embedding 输出维度
                .useIndex(true)   // 使用 pgvector IVFFlat 索引
                .dropTableFirst(false)
                .build();
    }

    // ─── EmbeddingModel：用 LangChain4j 封装本地 Ollama ───

    /**
     * LangChain4j 版 Ollama Embedding 模型。
     * 与现有 Spring AI 的 OllamaEmbeddingModel 并行运行，各管各的调用。
     */
    @Bean
    public OllamaEmbeddingModel ollamaEmbeddingModel() {
        return OllamaEmbeddingModel.builder()
                .baseUrl(ollamaBaseUrl)
                .modelName(embeddingModel)
                .build();
    }
}
```

同时在 `application.yml` 的 `stockwise` 段追加：

```yaml
stockwise:
  chat-memory:
    max-messages: ${CHAT_MEMORY_MAX_MESSAGES:20}
    max-tokens: ${CHAT_MEMORY_MAX_TOKENS:4000}
```

---

### Step 3：实现 `PgChatMemoryStore`

**新建文件** `src/main/java/com/stockwise/config/PgChatMemoryStore.java`

```java
package com.stockwise.config;

import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.ChatMessageDeserializer;
import dev.langchain4j.data.message.ChatMessageSerializer;
import dev.langchain4j.store.memory.chat.ChatMemoryStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import javax.sql.DataSource;
import java.sql.*;
import java.util.ArrayList;
import java.util.List;

import static dev.langchain4j.internal.ValidationUtils.ensureNotNull;

/**
 * 基于 PostgreSQL 的 ChatMemoryStore 实现。
 * 建表语句通过幂等 DDL 自动执行，无需额外迁移步骤。
 * 每个 memoryId（会话ID）独立存储，与 LangChain4j ChatMemory 生命周期一致。
 */
public class PgChatMemoryStore implements ChatMemoryStore {

    private static final Logger log = LoggerFactory.getLogger(PgChatMemoryStore.class);
    private final DataSource dataSource;

    // 幂等 DDL，首次访问时自动建表。
    private static final String DDL = """
            CREATE TABLE IF NOT EXISTS chat_memory (
                id        BIGSERIAL PRIMARY KEY,
                memory_id VARCHAR(128) NOT NULL,
                messages  JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (memory_id)
            );
            CREATE INDEX IF NOT EXISTS idx_chat_memory_updated
                ON chat_memory (updated_at);
            """;

    public PgChatMemoryStore(DataSource dataSource) {
        this.dataSource = ensureNotNull(dataSource, "dataSource");
        initTable();
    }

    private void initTable() {
        try (Connection conn = dataSource.getConnection();
             Statement stmt = conn.createStatement()) {
            stmt.execute(DDL);
        } catch (SQLException e) {
            log.warn("chat_memory DDL 执行失败，表可能已存在: {}", e.getMessage());
        }
    }

    // 1. 读取会话历史消息。
    @Override
    public List<ChatMessage> getMessages(Object memoryId) {
        String sql = "SELECT messages FROM chat_memory WHERE memory_id = ?";
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, String.valueOf(memoryId));
            ResultSet rs = ps.executeQuery();
            if (rs.next()) {
                String json = rs.getString("messages");
                return ChatMessageDeserializer.messagesFromJson(json);
            }
        } catch (Exception e) {
            log.warn("读取 ChatMemory 失败 memoryId={}: {}", memoryId, e.getMessage());
        }
        return new ArrayList<>();
    }

    // 2. 写入 / 更新会话历史（JSONB 原地覆盖）。安全：参数化 SQL 绑定，无字符串拼接注入。
    @Override
    public void updateMessages(Object memoryId, List<ChatMessage> messages) {
        String json = ChatMessageSerializer.messagesToJson(messages);
        String sql = """
                INSERT INTO chat_memory (memory_id, messages)
                VALUES (?, to_jsonb(?::jsonb))
                ON CONFLICT (memory_id)
                DO UPDATE SET messages = EXCLUDED.messages, updated_at = now()
                """;
        try (Connection conn = dataSource.getConnection()) {
            try (PreparedStatement ps = conn.prepareStatement(sql)) {
                ps.setString(1, String.valueOf(memoryId));
                ps.setString(2, json);
                int rows = ps.executeUpdate();
                if (rows == 0) log.warn("ChatMemory 写入返回 0 行 memoryId={}", memoryId);
            }
        } catch (SQLException e) {
            log.error("ChatMemory 写入失败 memoryId={}", memoryId, e);
        }
    }

    // 3. 删除会话（可选管理用途）。
    @Override
    public void deleteMessages(Object memoryId) {
        String sql = "DELETE FROM chat_memory WHERE memory_id = ?";
        try (Connection conn = dataSource.getConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            ps.setString(1, String.valueOf(memoryId));
            ps.executeUpdate();
        } catch (SQLException e) {
            log.warn("ChatMemory 删除失败 memoryId={}: {}", memoryId, e.getMessage());
        }
    }
}
```

---

### Step 4：改造 `MemoryRouter` — 接入 LangChain4j ChatMemory

**修改文件** `src/main/java/com/stockwise/memory/MemoryRouter.java`

修改点：

1. **新增注入** `ChatMemory chatMemory`（来自 LangChain4jConfig）

2. **新增方法** `loadRecentContext(Object memoryId)` 供 `AgentOrchestrator` 替代现有的 `AgentContextBuilder`

```java
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.memory.ChatMemory;

// 新增注入
private final ChatMemory chatMemory;

// 新增方法：加载当前会话最近的对话上下文
public List<ChatMessage> loadRecentContext(String sessionId) {
    Object memoryId = singleUserId + ":" + sessionId;
    return chatMemory.messages(); // 返回 ChatMemory 中已裁剪后的消息列表
}

// 新增方法：自动裁剪与保存对话
public void appendAndTrimMessages(String sessionId, String userMessage, String aiResponse) {
    Object memoryId = singleUserId + ":" + sessionId;
    chatMemory.add(UserMessage.from(userMessage));
    chatMemory.add(AiMessage.from(aiResponse));
    // add 操作后 ChatMemory 自动触发裁剪（窗口限制），裁剪结果自动通过 ChatMemoryStore 写入 PG
}
```

3. **保留** `loadWorking`、`saveWorking`、`clearWorking`、`loadRecentEpisodes`、`archiveEpisode`、`loadRequiredPortfolio`、`recordFeedback`、`ingestConfirmedKnowledge` — 现有方法签名和行为不变。

---

### Step 5：改造 `AgentOrchestrator` — 使用 ChatMemory 替代 AgentContextBuilder

**修改文件** `src/main/java/com/stockwise/agent/AgentOrchestrator.java`

修改点：

1. **删除** `AgentContextBuilder agentContextBuilder` 注入（不再需要）

2. **在 `firstRun()` 中**，原来调用 `agentContextBuilder.build(...)` 的地方改为从 `MemoryRouter` 读取 ChatMemory：

```java
// 旧代码：
// String contextPrompt = agentContextBuilder.build(question, ...);

// 新代码：从 ChatMemory 加载最近对话（已自动裁剪到 20 条 / 4000 tokens）
List<ChatMessage> recentMessages = memoryRouter.loadRecentContext(sessionId);
String contextPrompt = formatAsPrompt(recentMessages, question);

// 辅助方法：将 ChatMessage 列表拼成上下文 prompt
private String formatAsPrompt(List<ChatMessage> messages, String currentQuestion) {
    StringBuilder sb = new StringBuilder();
    for (ChatMessage msg : messages) {
        if (msg instanceof UserMessage) {
            sb.append("用户：").append(((UserMessage) msg).singleText()).append("\n");
        } else if (msg instanceof AiMessage) {
            sb.append("助手：").append(((AiMessage) msg).text()).append("\n");
        }
    }
    sb.append("当前问题：").append(currentQuestion);
    return sb.toString();
}
```

3. **在每次对话完成后**，调用 `memoryRouter.appendAndTrimMessages(sessionId, question, answer)` 自动归档历史：

```java
// streamAndFinalize 方法的 finally 或 done 阶段
memoryRouter.appendAndTrimMessages(sessionId, rawQuestion, finalAnswer);
```

---

### Step 6：改造知识检索 — 用 `EmbeddingStore` 替代 `KnowledgeRetrievalService`

**修改文件** `src/main/java/com/stockwise/service/StockTools.java`

修改 `searchInvestmentKnowledge` 方法：

```java
// 新增注入
private final EmbeddingStore<TextSegment> embeddingStore;

// 修改方法体
@Tool(name = "searchInvestmentKnowledge", description = "...")
public String searchInvestmentKnowledge(String question) {
    try {
        // 1. 嵌入用户问题
        TextSegment querySegment = TextSegment.from(question);
        List<EmbeddingMatch<TextSegment>> matches = embeddingStore.search(
                embeddingStore.embed(querySegment), // LangChain4j 的 search(Embedding, maxResults, minScore)
                12,    // topK
                0.55   // minSimilarity（对齐现有 min-similarity 阈值）
        );
        // 2. 格式化为 JSON，保留 score/source/content
        // 3. 使用已有的 KnowledgeFilter 做冲突检测和过期过滤（保留）
        return formatKnowledgeResults(matches);
    } catch (Exception e) {
        return "{\"hit\":false,\"reason\":\"检索失败\"}";
    }
}
```

**可删除文件** `KnowledgeRetrievalService.java` — 不再需要手写检索。

---

### Step 7：改造知识入库 — 用 `EmbeddingStoreIngestor` 替代 `KnowledgeIngestService`

**新建文件** `src/main/java/com/stockwise/service/KnowledgeIngestServiceImpl.java`

保留 `KnowledgeIngestService` 接口和 `IngestResult` DTO，只改实现：

```java
@Service
public class KnowledgeIngestServiceImpl implements KnowledgeIngestService {

    private final EmbeddingStore<TextSegment> embeddingStore;
    private final OllamaEmbeddingModel embeddingModel;
    private final ObjectMapper objectMapper;

    // MIN_CONFIDENCE 统一为 50（解决重复常量问题）
    private static final double MIN_CONFIDENCE = 50.0;
    private static final double DEDUP_THRESHOLD = 0.92;

    @Override
    public IngestResult ingest(KnowledgeCandidate candidate, String problem, Long userId) {
        // 1. 置信度门禁
        if (candidate.confidence() < MIN_CONFIDENCE) {
            return IngestResult.rejected("置信度不足");
        }
        // 2. 去重检查（用 LangChain4j 的 search 先查相似文档）
        TextSegment query = TextSegment.from(candidate.content());
        List<EmbeddingMatch<TextSegment>> dups = embeddingStore.search(
                embeddingStore.embed(query), 1, DEDUP_THRESHOLD);
        if (!dups.isEmpty()) {
            return IngestResult.rejected("已有高度相似知识");
        }
        // 3. 入库
        Map<String, Object> metadata = Map.of(
                "problem", problem,
                "source", "user_confirmed",
                "confidence", candidate.confidence(),
                "effective_at", Instant.now().toString()
        );
        TextSegment segment = TextSegment.from(candidate.content(), metadata);
        embeddingStore.add(embeddingStore.embed(segment), segment);
        return IngestResult.success();
    }
}
```

**可删除文件** `KnowledgeIngestService.java`（旧实现），保留接口。

---

### Step 8：更新 `application.yml` 配置

在文件末尾追加：

```yaml
stockwise:
  chat-memory:
    max-messages: ${CHAT_MEMORY_MAX_MESSAGES:20}
    max-tokens: ${CHAT_MEMORY_MAX_TOKENS:4000}
```

在 `docker-compose.cloud.yml` 的 `environment` 段追加：

```yaml
CHAT_MEMORY_MAX_MESSAGES: ${CHAT_MEMORY_MAX_MESSAGES:-20}
CHAT_MEMORY_MAX_TOKENS: ${CHAT_MEMORY_MAX_TOKENS:-4000}
```

---

### Step 9：清理与删除

以下旧文件可以删除（相关引用已在新代码中消除）：

| 删除文件 | 替代 |
|----------|------|
| `AgentContextBuilder.java` | `LangChain4jConfig.chatMemory()` + `MemoryRouter.loadRecentContext()` |
| `ConversationHistoryService.java` | `PgChatMemoryStore`（自动裁剪+持久化） |
| `KnowledgeRetrievalService.java` | `EmbeddingStore<TextSegment>.search()` |
| `KnowledgeIngestService.java`（实现类） | `KnowledgeIngestServiceImpl`（LangChain4j 版） |

以下文件**必须保留不动**：

| 文件 | 原因 |
|------|------|
| `KnowledgeFilter.java` | 冲突检测+过期过滤仍需要（LangChain4j不做业务过滤） |
| `StockSkillContractValidator.java` | 契约校验 |
| `ReportAssembler.java` | 报告组装 |
| `KnowledgeService.java`（CRUD） | 后台管理 |
| `SessionStateService.java` | Redis CAS |
| `StockTools.java` | @Tool 注解方法（只改 searchInvestmentKnowledge 内部实现） |

---

### Step 10：顺带修复已知问题

| 问题 | 修复方式 |
|------|---------|
| `KnowledgeService:81` SQL 注入 `.last("LIMIT " + value)` | LangChain4j 接管检索后该方法变为纯管理接口，`limit` 可通过 MyBatis-Plus `Page` 分页替代 |
| `ConversationHistoryService:47` 字符串拼接 LIMIT | ChatMemoryStore 使用参数化 SQL，根本消除 |
| `KnowledgeFilter` / `KnowledgeIngestService` 重复 `MIN_CONFIDENCE = 50` 常量 | 统一到 `KnowledgeIngestServiceImpl.MIN_CONFIDENCE` |
| `SessionState` 缺 `@JsonIgnoreProperties(ignoreUnknown = true)` | 在 `SessionState` 类上加此注解 |
| `GuardrailService.validated` 无限缓冲区 | 添加 `if (validated.length() > 8000) validated.delete(0, validated.length() - 4000)` 滑动窗口 |

---

## 四、验收标准

### 编译与测试

```bash
mvn clean compile           # 编译通过
mvn test                    # 全部 76 个测试通过（含云端集成测试）
```

### 运行时验收（本地）

1. 启动后端，访问 `http://localhost:8080/actuator/health` → `{"status":"UP"}`
2. 通过 `stockwise-chat.html` 发送对话
3. 查询 PostgreSQL：

```sql
-- chat_memory 表已自动创建且包含消息记录
SELECT memory_id, jsonb_array_length(messages) FROM chat_memory;
-- 最多保留 20 条消息
```

```sql
-- knowledge_chunks 仍可正常检索
SELECT 1 FROM knowledge_chunks LIMIT 1;
```

### 行为不变性验证

- 普通问答、知识问答、外部研究、行情事实和追问对 `PaidAnalysisClient` 调用次数为零
- 对话上下文自动裁剪到 20 条消息或 4000 tokens，任一先触发
- 知识检索 `minSimilarity = 0.55` 保持不变
- Redis 会话状态 CAS 机制不受影响
- `BoundedReactLoop` 的步骤限制、截止时间、去重检查不变

---

## 五、风险与回滚

| 风险 | 缓解 |
|------|------|
| LangChain4j 0.36.2 与 Spring AI 1.0.0 依赖冲突 | 排除 `langchain4j-pgvector` 中的 `postgresql` 传递依赖 |
| ChatMemory 替换后 AgentContextBuilder 输出格式变化影响模型回答 | `formatAsPrompt()` 保持与旧 `AgentContextBuilder.build()` 相同的 prompt 结构 |
| OllamaEmbeddingModel 双实例（Spring AI + LangChain4j）并发调用 Ollama | Ollama 服务端自身处理并发，无影响 |
| 回滚 | ChatMemory/EmbeddingStore 改动集中在 `MemoryRouter` 和 `StockTools`，回滚即恢复原 4 个旧类 + 去掉依赖 |

---

## 六、执行协议

1. 按 Step 1→10 顺序实施，每步完成后 `mvn compile` 确认编译通过
2. Step 9 清除非引用代码前，先用 `grep` 全量搜索确认无其他引用
3. 全部步骤完成后执行 `mvn test`，与实施前的 76/0/1 基线对比
4. 不接受任何对 `BoundedReactLoop`、`RouteExecutionPolicyRegistry`、`PaidModelGate`、`AgentOrchestrator` 主流程逻辑的修改
5. 所有中文字符串（prompt、注释、日志）编码正确无乱码

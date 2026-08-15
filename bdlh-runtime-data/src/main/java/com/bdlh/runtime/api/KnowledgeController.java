package com.bdlh.runtime.api;

import com.bdlh.runtime.entity.KnowledgeChunk;
import com.bdlh.runtime.entity.KnowledgeChunkWithScore;
import com.bdlh.runtime.service.KnowledgeRetrievalService;
import com.bdlh.runtime.service.KnowledgeService;
import com.bdlh.runtime.security.SingleUserContext;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 知识库接口：检索（Step 4 验证）+ 管理 CRUD（PRD 9.3）。
 * 知识确认入库走对话 SSE 流程的暂停点 C，本接口只负责已有知识的维护。
 */
@RestController
@RequestMapping("/api/v1/knowledge")
public class KnowledgeController {

    private final KnowledgeRetrievalService retrievalService;
    private final KnowledgeService knowledgeService;
    private final SingleUserContext singleUserContext;

    public KnowledgeController(KnowledgeRetrievalService retrievalService,
                               KnowledgeService knowledgeService,
                               SingleUserContext singleUserContext) {
        this.retrievalService = retrievalService;
        this.knowledgeService = knowledgeService;
        this.singleUserContext = singleUserContext;
    }

    /**
     * 向量检索：输入问题返回 Top-K 相似知识。
     */
    @GetMapping("/search")
    public List<KnowledgeChunkWithScore> search(@RequestParam String q,
                                                @RequestParam(defaultValue = "5") int topK) {
        return retrievalService.search(q, topK);
    }

    /**
     * 知识列表：支持按 status 与关键字过滤。
     */
    @GetMapping
    public List<KnowledgeChunk> list(@RequestParam(required = false) String status,
                                     @RequestParam(required = false) String tag,
                                     @RequestParam(defaultValue = "50") int limit) {
        return knowledgeService.list(status, tag, limit);
    }

    /**
     * 知识详情。
     */
    @GetMapping("/{id}")
    public KnowledgeChunk get(@PathVariable Long id) {
        return knowledgeService.get(id);
    }

    /**
     * 修改知识：请求体可含 content / metadata / status，仅更新提供字段。
     */
    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable Long id, @RequestBody Map<String, Object> body) {
        // 1. 知识维护会影响后续所有人的检索结果，至少要求有效登录身份。
        singleUserContext.requirePermission("KNOWLEDGE_WRITE");
        // 2. 从请求体取出可更新字段，交服务部分更新
        Object content = body.get("content");
        Object metadata = body.get("metadata");
        Object status = body.get("status");
        knowledgeService.update(id,
                content == null ? null : String.valueOf(content),
                metadata instanceof Map ? (Map<String, Object>) metadata : null,
                status == null ? null : String.valueOf(status));
        return Map.of("status", "updated", "id", id);
    }

    /**
     * 软删除：标记为 deprecated，不物理删除。
     */
    @DeleteMapping("/{id}")
    public Map<String, Object> delete(@PathVariable Long id) {
        // 1. 知识库写操作需要服务端身份校验，避免未授权修改或删除内容。
        singleUserContext.requirePermission("KNOWLEDGE_WRITE");
        knowledgeService.deprecate(id);
        return Map.of("status", "deprecated", "id", id);
    }
}

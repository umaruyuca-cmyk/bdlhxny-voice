package com.bdlh.runtime.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.bdlh.runtime.entity.KnowledgeChunk;
import com.bdlh.runtime.mapper.KnowledgeChunkMapper;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * 知识库管理服务，面向后台 CRUD：列表/详情/修改/软删除。
 * 检索与入库（自增长闭环）由 KnowledgeRetrievalService / KnowledgeIngestService 负责，本服务只管维护已有知识。
 */
@Service
public class KnowledgeService {

    private final KnowledgeChunkMapper mapper;

    public KnowledgeService(KnowledgeChunkMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * 列表查询：按 status 与关键字过滤。
     * tag 当前用 content 模糊匹配，可后续增强为 metadata->'tags' 的 JSONB 精确查询。
     */
    public List<KnowledgeChunk> list(String status, String tag, int limit) {
        // 1. 组装过滤条件，按创建时间倒序
        QueryWrapper<KnowledgeChunk> w = new QueryWrapper<>();
        if (status != null && !status.isBlank()) {
            w.eq("status", status);
        }
        if (tag != null && !tag.isBlank()) {
            w.like("content", tag);
        }
        w.orderByDesc("created_at").last("LIMIT " + Math.max(1, limit));
        return mapper.selectList(w);
    }

    /**
     * 取单条知识详情。
     */
    public KnowledgeChunk get(Long id) {
        return mapper.selectById(id);
    }

    /**
     * 部分更新：仅写入非 null 字段，避免覆盖未传入的字段。
     */
    public void update(Long id, String content, Map<String, Object> metadata, String status) {
        // 1. 构建只含待更新字段的实体，交自定义 updateKnowledge 动态 SQL 更新
        KnowledgeChunk c = new KnowledgeChunk();
        c.setId(id);
        if (content != null) {
            c.setContent(content);
        }
        if (metadata != null) {
            c.setMetadata(metadata);
        }
        if (status != null) {
            c.setStatus(status);
        }
        mapper.updateKnowledge(c);
    }

    /**
     * 软删除：状态置为 deprecated，保留数据可追溯，不物理删除。
     */
    public void deprecate(Long id) {
        mapper.deprecate(id);
    }
}

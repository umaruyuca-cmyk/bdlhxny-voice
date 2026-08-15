package com.bdlh.runtime.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.bdlh.runtime.entity.KnowledgeChunk;
import com.bdlh.runtime.entity.KnowledgeChunkWithScore;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * 知识库向量存储的数据访问层。
 * 标准 CRUD 由 BaseMapper 提供；向量检索、去重、入库这类 pgvector 专属操作走自定义 XML。
 */
public interface KnowledgeChunkMapper extends BaseMapper<KnowledgeChunk> {

    /**
     * 按问题向量检索最相似的 Top-K 知识，SQL 层已过滤失效知识并命中 ivfflat 索引。
     *
     * @param vec  问题向量文本，形如 "[0.1,0.2,...]"，由调用方从 float[] 转换得到
     * @param topK 返回条数
     */
    List<KnowledgeChunkWithScore> searchByVector(@Param("vec") String vec, @Param("topK") int topK);

    /**
     * 计算与库内已有知识的最大相似度，供入库前去重判定（>0.92 视为重复）。
     */
    double findTopSimilarity(@Param("vec") String vec);

    /**
     * 自定义入库，确保 embedding 与 metadata 经 TypeHandler 以 vector/jsonb 类型正确落库。
     */
    int insertKnowledge(KnowledgeChunk chunk);

    /**
     * 部分更新：仅更新非 null 字段（content/metadata/status），metadata 显式走 JsonbTypeHandler。
     */
    int updateKnowledge(KnowledgeChunk chunk);

    /**
     * 软删除：将状态置为 deprecated，不物理删除。
     */
    int deprecate(@Param("id") Long id);
}

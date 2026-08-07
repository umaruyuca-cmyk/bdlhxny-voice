package com.stockwise.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.stockwise.entity.ConversationHistory;
import org.apache.ibatis.annotations.Param;

import java.util.List;

/**
 * 对话历史的数据访问层。
 * 标准 CRUD 由 BaseMapper 提供；归档写入因含 JSONB messages 字段，走自定义 XML 保证类型正确。
 */
public interface ConversationHistoryMapper extends BaseMapper<ConversationHistory> {

    /**
     * 归档会话，messages 经 JsonbTypeHandler 写为 jsonb 类型。
     */
    int insertArchive(ConversationHistory history);

    /**
     * 使用参数化 LIMIT 加载用户最近的归档，避免业务层拼接 SQL。
     */
    List<ConversationHistory> selectRecent(
            @Param("userId") Long userId,
            @Param("limit") int limit);

}

package com.bdlh.runtime.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.bdlh.runtime.entity.ConversationSessionSnapshot;
import org.apache.ibatis.annotations.Param;

/**
 * 提供会话最新消息快照的幂等写入与用户归属读取。
 */
public interface ConversationSessionSnapshotMapper extends BaseMapper<ConversationSessionSnapshot> {

    /**
     * 按会话主键覆盖最新快照，保证重复请求不会产生重复快照行。
     */
    int upsert(ConversationSessionSnapshot snapshot);

    /**
     * 仅允许读取指定用户拥有的会话快照。
     */
    ConversationSessionSnapshot selectOwned(
            @Param("userId") Long userId,
            @Param("sessionId") String sessionId);
}

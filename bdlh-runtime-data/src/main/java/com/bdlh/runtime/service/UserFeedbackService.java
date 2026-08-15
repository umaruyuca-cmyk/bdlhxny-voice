package com.bdlh.runtime.service;

import com.bdlh.runtime.entity.UserFeedback;
import com.bdlh.runtime.mapper.UserFeedbackMapper;
import com.bdlh.runtime.memory.FeedbackType;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

/**
 * 将用户对回答和知识入库的反馈写入情景记忆，供质量评估与后续回放使用。
 */
@Service
public class UserFeedbackService {

    private final UserFeedbackMapper mapper;

    public UserFeedbackService(UserFeedbackMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * 保存一条结构化反馈，并关联会话和最近一次 Agent Run。
     */
    public void record(Long userId,
                       String sessionId,
                       UUID runId,
                       FeedbackType type,
                       String message,
                       Map<String, Object> metadata) {
        UserFeedback feedback = new UserFeedback();
        feedback.setUserId(userId);
        feedback.setSessionId(sessionId);
        feedback.setRunId(runId);
        feedback.setFeedbackType(type.name());
        feedback.setMessage(message);
        feedback.setMetadata(metadata == null ? Map.of() : Map.copyOf(metadata));
        feedback.setCreatedAt(OffsetDateTime.now());
        mapper.insert(feedback);
    }
}

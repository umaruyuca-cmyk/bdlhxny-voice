package com.bdlh.runtime.service;

import com.bdlh.runtime.entity.UserFeedback;
import com.bdlh.runtime.mapper.UserFeedbackMapper;
import com.bdlh.runtime.memory.FeedbackType;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Map;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

/**
 * 验证用户回复以固定反馈类型落库，并关联会话和 Agent Run。
 */
class UserFeedbackServiceTest {

    @Test
    void shouldPersistStructuredFeedback() {
        UserFeedbackMapper mapper = mock(UserFeedbackMapper.class);
        UserFeedbackService service = new UserFeedbackService(mapper);
        UUID runId = UUID.randomUUID();

        service.record(7L, "session-1", runId, FeedbackType.CORRECTION,
                "风险承受能力更低", Map.of("step", "awaiting_resolution"));

        ArgumentCaptor<UserFeedback> captor = ArgumentCaptor.forClass(UserFeedback.class);
        verify(mapper).insert(captor.capture());
        UserFeedback feedback = captor.getValue();
        assertEquals(7L, feedback.getUserId());
        assertEquals(runId, feedback.getRunId());
        assertEquals("CORRECTION", feedback.getFeedbackType());
        assertEquals("awaiting_resolution", feedback.getMetadata().get("step"));
        assertNotNull(feedback.getCreatedAt());
    }
}

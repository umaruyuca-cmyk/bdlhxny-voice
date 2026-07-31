package com.stockwise.memory;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 验证工作记忆使用版本化 CAS，旧请求不能覆盖或删除新请求状态。
 */
class SessionStateServiceTest {

    @Test
    void shouldIncrementVersionAfterSuccessfulSave() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.execute(any(), anyList(), any(), any(), any())).thenReturn(1L);
        SessionStateService service = new SessionStateService(redis, new ObjectMapper());
        SessionState state = state(0);

        long result = service.save(state);

        assertEquals(1L, result);
        assertEquals(1L, state.getVersion());
    }

    @Test
    void shouldRestoreVersionAndThrowWhenSaveConflicts() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.execute(any(), anyList(), any(), any(), any())).thenReturn(0L);
        SessionStateService service = new SessionStateService(redis, new ObjectMapper());
        SessionState state = state(3);

        assertThrows(SessionStateConflictException.class, () -> service.save(state));
        assertEquals(3L, state.getVersion());
    }

    @Test
    void shouldRejectClearUsingStaleVersion() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        when(redis.execute(any(), anyList(), any())).thenReturn(0L);
        SessionStateService service = new SessionStateService(redis, new ObjectMapper());

        assertThrows(SessionStateConflictException.class, () -> service.clear(state(2)));
    }

    @Test
    void shouldDeserializeLegacyHistoryMapsAsTypedMessages() throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        String json = """
                {
                  "sessionId": "session-1",
                  "history": [
                    {"role": "user", "content": "旧消息", "legacyField": true},
                    {"role": "assistant", "content": "旧回答"}
                  ],
                  "futureField": "ignored"
                }
                """;

        SessionState state = mapper.readValue(json, SessionState.class);

        assertEquals(ConversationMessage.user("旧消息"), state.getHistory().get(0));
        assertEquals(ConversationMessage.assistant("旧回答"), state.getHistory().get(1));
    }

    private SessionState state(long version) {
        SessionState state = new SessionState();
        state.setSessionId("session-1");
        state.setVersion(version);
        return state;
    }
}

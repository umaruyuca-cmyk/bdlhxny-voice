package com.bdlh.runtime.service;

import com.bdlh.runtime.dto.ChatMode;
import com.bdlh.runtime.entity.ConversationSession;
import com.bdlh.runtime.mapper.ConversationSessionMapper;
import com.bdlh.runtime.memory.ConversationMessage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证会话目录写入和消息快照读取保持用户边界，并限制列表查询数量。
 */
class ConversationSessionServiceTest {

    private final ConversationSessionMapper sessionMapper = mock(ConversationSessionMapper.class);
    private final ConversationHistoryService historyService = mock(ConversationHistoryService.class);
    private final ConversationSessionService service = new ConversationSessionService(sessionMapper, historyService);

    @Test
    void shouldPersistTurnWithModeAndMessages() {
        List<ConversationMessage> messages = List.of(
                ConversationMessage.user("你好"),
                ConversationMessage.assistant("你好，有什么可以研究的？"));

        service.saveTurn(7L, "general_session_1", ChatMode.GENERAL, "你好", messages);

        verify(sessionMapper).upsert(any(ConversationSession.class));
        verify(historyService).saveSnapshot(7L, "general_session_1", messages, null);
    }

    @Test
    void shouldClampConversationListLimit() {
        when(sessionMapper.selectRecent(7L, "stock", 50)).thenReturn(List.of());

        assertThat(service.listRecent(7L, ChatMode.STOCK_AGENT, 500)).isEmpty();

        verify(sessionMapper).selectRecent(7L, "stock", 50);
    }

    @Test
    void shouldReturnLatestMessageSnapshot() {
        ConversationSession session = new ConversationSession();
        session.setSessionId("general_session_1");
        List<Object> messages = List.of(ConversationMessage.user("你好"));
        when(sessionMapper.selectOwned(7L, "general_session_1")).thenReturn(session);
        when(historyService.loadLatestMessages(7L, "general_session_1")).thenReturn(messages);

        ConversationSessionService.ConversationDetail detail = service.loadOwned(7L, "general_session_1");

        assertThat(detail).isNotNull();
        assertThat(detail.messages()).hasSize(1);
    }
}

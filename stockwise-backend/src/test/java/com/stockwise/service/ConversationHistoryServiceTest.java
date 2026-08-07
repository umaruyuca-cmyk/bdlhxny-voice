package com.stockwise.service;

import com.stockwise.mapper.ConversationHistoryMapper;
import com.stockwise.mapper.ConversationSessionSnapshotMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证会话历史查询使用受控的参数化数量，不再拼接业务输入到 SQL。
 */
class ConversationHistoryServiceTest {

    private final ConversationHistoryMapper mapper = mock(ConversationHistoryMapper.class);
    private final ConversationSessionSnapshotMapper snapshotMapper = mock(ConversationSessionSnapshotMapper.class);
    private final ConversationHistoryService service = new ConversationHistoryService(mapper, snapshotMapper);

    @Test
    void shouldClampRecentHistoryLimit() {
        when(mapper.selectRecent(7L, 20)).thenReturn(List.of());

        assertEquals(List.of(), service.loadRecent(7L, 1000));

        verify(mapper).selectRecent(7L, 20);
    }
}

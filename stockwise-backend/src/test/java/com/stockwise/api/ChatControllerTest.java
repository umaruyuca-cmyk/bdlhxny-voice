package com.stockwise.api;

import com.stockwise.agent.AgentOrchestrator;
import com.stockwise.dto.ChatInstrument;
import com.stockwise.dto.ChatMode;
import com.stockwise.dto.ChatStreamRequest;
import com.stockwise.security.AuthorizationService;
import com.stockwise.security.SingleUserContext;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 验证正式对话入口只接受结构化POST数据并使用服务端用户身份。
 */
class ChatControllerTest {

    @Test
    void shouldUseServerUserAndNormalizedInstrument() {
        AgentOrchestrator orchestrator = mock(AgentOrchestrator.class);
        SingleUserContext userContext = new SingleUserContext(7L, mock(AuthorizationService.class));
        ChatController controller = new ChatController(orchestrator, userContext);
        SseEmitter emitter = new SseEmitter();
        ChatInstrument expected = new ChatInstrument("600519", "stock");
        String scopedSessionId = ChatMode.STOCK_AGENT.scopedSessionId("session_1234");
        when(orchestrator.handle(
                7L, scopedSessionId, ChatMode.STOCK_AGENT, "现在适合买入吗", expected))
                .thenReturn(emitter);

        SseEmitter result = controller.stream(new ChatStreamRequest(
                "session_1234",
                ChatMode.STOCK_AGENT,
                " 现在适合买入吗 ",
                new ChatInstrument(" 600519 ", " STOCK ")));

        assertThat(result).isSameAs(emitter);
        verify(orchestrator).handle(
                7L, scopedSessionId, ChatMode.STOCK_AGENT, "现在适合买入吗", expected);
    }

    @Test
    void shouldRejectInvalidSessionBeforeOrchestration() {
        ChatController controller = new ChatController(
                mock(AgentOrchestrator.class),
                new SingleUserContext(1L, mock(AuthorizationService.class)));

        assertThatThrownBy(() -> controller.stream(new ChatStreamRequest(
                "../session",
                ChatMode.GENERAL,
                "测试",
                null)))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("sessionId");
    }

}

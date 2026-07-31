package com.stockwise.api;

import com.stockwise.agent.AgentOrchestrator;
import com.stockwise.dto.ChatInstrument;
import com.stockwise.dto.ChatMode;
import com.stockwise.dto.ChatStreamRequest;
import com.stockwise.quota.GuestAnalysisQuotaService;
import com.stockwise.security.GuestIdentityService;
import com.stockwise.security.AuthorizationService;
import com.stockwise.security.SingleUserContext;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;
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
        RequestContextHolder.resetRequestAttributes();
        AgentOrchestrator orchestrator = mock(AgentOrchestrator.class);
        SingleUserContext userContext = new SingleUserContext(7L, mock(AuthorizationService.class));
        ChatController controller = new ChatController(
                orchestrator,
                userContext,
                mock(GuestIdentityService.class),
                mock(GuestAnalysisQuotaService.class));
        SseEmitter emitter = new SseEmitter();
        ChatInstrument expected = new ChatInstrument("600519", "stock");
        String scopedSessionId = ChatMode.STOCK_AGENT.scopedSessionId("session_1234");
        when(orchestrator.handle(
                7L, scopedSessionId, ChatMode.STOCK_AGENT, "现在适合买入吗", expected, false, null))
                .thenReturn(emitter);

        SseEmitter result = controller.stream(new ChatStreamRequest(
                "session_1234",
                ChatMode.STOCK_AGENT,
                " 现在适合买入吗 ",
                new ChatInstrument(" 600519 ", " STOCK ")),
                new MockHttpServletRequest(),
                new MockHttpServletResponse());

        assertThat(result).isSameAs(emitter);
        verify(orchestrator).handle(
                7L, scopedSessionId, ChatMode.STOCK_AGENT, "现在适合买入吗", expected, false, null);
    }

    @Test
    void shouldRejectInvalidSessionBeforeOrchestration() {
        ChatController controller = new ChatController(
                mock(AgentOrchestrator.class),
                new SingleUserContext(1L, mock(AuthorizationService.class)),
                mock(GuestIdentityService.class),
                mock(GuestAnalysisQuotaService.class));

        assertThatThrownBy(() -> controller.stream(new ChatStreamRequest(
                "../session",
                ChatMode.GENERAL,
                "测试",
                null),
                new MockHttpServletRequest(),
                new MockHttpServletResponse()))
                .isInstanceOf(ResponseStatusException.class)
                .hasMessageContaining("sessionId");
    }

    @Test
    void shouldResolveGuestBeforeStartingAsyncFlow() {
        AgentOrchestrator orchestrator = mock(AgentOrchestrator.class);
        GuestIdentityService guestIdentityService = mock(GuestIdentityService.class);
        ChatController controller = new ChatController(
                orchestrator,
                new SingleUserContext(9L, mock(AuthorizationService.class)),
                guestIdentityService,
                mock(GuestAnalysisQuotaService.class));
        MockHttpServletRequest request = new MockHttpServletRequest();
        MockHttpServletResponse response = new MockHttpServletResponse();
        String subjectHash = "b".repeat(64);
        String scopedSessionId = ChatMode.GENERAL.scopedSessionId("session_5678");
        SseEmitter emitter = new SseEmitter();
        when(guestIdentityService.resolveSubjectHash(request, response)).thenReturn(subjectHash);
        when(orchestrator.handle(
                9L, scopedSessionId, ChatMode.GENERAL, "什么是ETF", null, true, subjectHash))
                .thenReturn(emitter);
        RequestContextHolder.setRequestAttributes(new ServletRequestAttributes(request));
        try {
            SseEmitter result = controller.stream(
                    new ChatStreamRequest("session_5678", ChatMode.GENERAL, "什么是ETF", null),
                    request,
                    response);

            assertThat(result).isSameAs(emitter);
            verify(guestIdentityService).resolveSubjectHash(request, response);
            verify(orchestrator).handle(
                    9L, scopedSessionId, ChatMode.GENERAL, "什么是ETF", null, true, subjectHash);
        } finally {
            RequestContextHolder.resetRequestAttributes();
        }
    }
}

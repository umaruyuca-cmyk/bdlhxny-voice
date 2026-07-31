package com.stockwise.api;

import com.stockwise.agent.AgentOrchestrator;
import com.stockwise.dto.ChatInstrument;
import com.stockwise.dto.ChatMode;
import com.stockwise.dto.ChatStreamRequest;
import com.stockwise.quota.GuestAnalysisQuota;
import com.stockwise.quota.GuestAnalysisQuotaService;
import com.stockwise.security.GuestIdentityService;
import com.stockwise.security.SingleUserContext;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

/**
 * 对话 SSE 端点。
 * 前端使用fetch POST和ReadableStream连接，逐事件接收status、token、ask与done。
 */
@RestController
@RequestMapping("/api/v1/chat")
public class ChatController {

    private static final int MAX_MESSAGE_LENGTH = 4_000;

    private final AgentOrchestrator orchestrator;
    private final SingleUserContext singleUserContext;
    private final GuestIdentityService guestIdentityService;
    private final GuestAnalysisQuotaService guestAnalysisQuotaService;

    public ChatController(AgentOrchestrator orchestrator,
                          SingleUserContext singleUserContext,
                          GuestIdentityService guestIdentityService,
                          GuestAnalysisQuotaService guestAnalysisQuotaService) {
        this.orchestrator = orchestrator;
        this.singleUserContext = singleUserContext;
        this.guestIdentityService = guestIdentityService;
        this.guestAnalysisQuotaService = guestAnalysisQuotaService;
    }

    /**
     * 使用POST接收结构化会话和标的，并返回统一SSE事件流。
     */
    @PostMapping(value = "/stream",
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@RequestBody ChatStreamRequest request,
                             HttpServletRequest servletRequest,
                             HttpServletResponse servletResponse) {
        ChatStreamRequest normalized;
        try {
            // 1. 请求字段先在HTTP边界标准化，避免无效值进入Redis键或模型上下文
            normalized = normalize(request);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, error.getMessage(), error);
        }
        // 2. 游客身份必须在进入异步线程前解析，避免RequestContext在线程切换后丢失。
        boolean guest = singleUserContext.isGuest();
        String guestSubjectHash = guest
                ? guestIdentityService.resolveSubjectHash(servletRequest, servletResponse)
                : null;
        // 3. 用户身份只从服务端上下文读取，客户端不得自行声明游客或用户ID。
        return orchestrator.handle(
                singleUserContext.userId(),
                normalized.mode().scopedSessionId(normalized.sessionId()),
                normalized.mode(),
                normalized.message(),
                normalized.instrument(),
                guest,
                guestSubjectHash);
    }

    /**
     * 返回当前浏览器的游客分析剩余次数，供页面初始状态展示。
     */
    @GetMapping("/guest-analysis-quota")
    public Map<String, Object> guestAnalysisQuota(HttpServletRequest servletRequest,
                                                  HttpServletResponse servletResponse) {
        boolean guest = singleUserContext.isGuest();
        String guestSubjectHash = guest
                ? guestIdentityService.resolveSubjectHash(servletRequest, servletResponse)
                : null;
        GuestAnalysisQuota quota = guestAnalysisQuotaService.status(guest, guestSubjectHash);
        return Map.of(
                "guest", guest,
                "applicable", quota.applicable(),
                "quotaType", "guest_analysis",
                "limit", quota.limit(),
                "used", quota.used(),
                "remaining", quota.remaining());
    }

    private ChatStreamRequest normalize(ChatStreamRequest request) {
        if (request == null) {
            throw new IllegalArgumentException("请求体不能为空");
        }
        String sessionId = request.sessionId() == null ? "" : request.sessionId().trim();
        if (!sessionId.matches("[A-Za-z0-9_-]{8,100}")) {
            throw new IllegalArgumentException("sessionId 格式无效");
        }
        String message = request.message() == null ? "" : request.message().trim();
        if (message.isEmpty() || message.length() > MAX_MESSAGE_LENGTH) {
            throw new IllegalArgumentException("message 长度必须在1到4000之间");
        }
        ChatInstrument instrument = ChatInstrument.normalize(request.instrument());
        ChatMode mode = request.mode() == null
                ? instrument == null ? ChatMode.GENERAL : ChatMode.STOCK_AGENT
                : request.mode();
        // 3. 普通问答在 HTTP 边界清除标的，防止客户端把股票上下文混入独立对话。
        if (mode == ChatMode.GENERAL) {
            instrument = null;
        }
        return new ChatStreamRequest(sessionId, mode, message, instrument);
    }
}

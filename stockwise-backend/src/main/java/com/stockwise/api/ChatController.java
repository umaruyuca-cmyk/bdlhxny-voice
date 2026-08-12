package com.stockwise.api;

import com.stockwise.agent.AgentOrchestrator;
import com.stockwise.dto.ChatInstrument;
import com.stockwise.dto.ChatMode;
import com.stockwise.dto.ChatStreamRequest;
import com.stockwise.security.SingleUserContext;
import org.springframework.http.MediaType;
import org.springframework.http.HttpStatus;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.web.server.ResponseStatusException;


/**
 * 对话 SSE 端点。
 * 前端使用fetch POST和ReadableStream连接，逐事件接收status、token、ask与done。
 */
@RestController
@RequestMapping("/api/v1/chat")
@ConditionalOnProperty(
        name = "stockwise.legacy-agent-runtime.enabled",
        havingValue = "true")
public class ChatController {

    private static final int MAX_MESSAGE_LENGTH = 4_000;

    private final AgentOrchestrator orchestrator;
    private final SingleUserContext singleUserContext;

    public ChatController(AgentOrchestrator orchestrator,
                          SingleUserContext singleUserContext) {
        this.orchestrator = orchestrator;
        this.singleUserContext = singleUserContext;
    }

    /**
     * 使用POST接收结构化会话和标的，并返回统一SSE事件流。
     */
    @PostMapping(value = "/stream",
            consumes = MediaType.APPLICATION_JSON_VALUE,
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@RequestBody ChatStreamRequest request) {
        ChatStreamRequest normalized;
        try {
            // 1. 请求字段先在HTTP边界标准化，避免无效值进入Redis键或模型上下文
            normalized = normalize(request);
        } catch (IllegalArgumentException error) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, error.getMessage(), error);
        }
        // 2. 单用户工作站始终使用服务端确定的用户 ID，客户端不得自行声明用户 ID。
        return orchestrator.handle(
                singleUserContext.requireAuthenticatedUserId(),
                resolveBackendSessionId(normalized.mode(), normalized.sessionId()),
                normalized.mode(),
                normalized.message(),
                normalized.instrument());
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

    /**
     * 已从会话目录恢复的后端 ID 直接复用，首次由浏览器生成的原始 ID 才进行模式隔离转换。
     */
    private String resolveBackendSessionId(ChatMode mode, String sessionId) {
        String prefix = mode.value() + "_";
        return sessionId.startsWith(prefix) ? sessionId : mode.scopedSessionId(sessionId);
    }
}

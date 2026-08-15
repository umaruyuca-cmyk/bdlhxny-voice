package com.bdlh.runtime.api;

import com.bdlh.runtime.dto.ChatMode;
import com.bdlh.runtime.entity.ConversationSession;
import com.bdlh.runtime.security.SingleUserContext;
import com.bdlh.runtime.service.ConversationSessionService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/**
 * Agent 会话目录接口，供前端左侧列表和刷新恢复使用。
 * 会话消息只返回当前用户拥有的最新快照，不暴露其他用户数据。
 */
@RestController
@RequestMapping("/api/v1/conversations")
public class ConversationController {

    private final ConversationSessionService sessionService;
    private final SingleUserContext singleUserContext;

    public ConversationController(ConversationSessionService sessionService,
                                   SingleUserContext singleUserContext) {
        this.sessionService = sessionService;
        this.singleUserContext = singleUserContext;
    }

    /**
     * 查询当前用户最近会话，可按 general 或 stock 模式过滤。
     */
    @GetMapping
    public List<ConversationSession> list(
            @RequestParam(required = false) String mode,
            @RequestParam(defaultValue = "20") int limit) {
        ChatMode chatMode = mode == null || mode.isBlank() ? null : ChatMode.from(mode);
        return sessionService.listRecent(singleUserContext.requireAuthenticatedUserId(), chatMode, limit);
    }

    /**
     * 查询单个会话的元数据和完整消息快照。
     */
    @GetMapping("/{sessionId}")
    public ConversationDetailResponse detail(@PathVariable String sessionId) {
        if (sessionId == null || !sessionId.matches("[A-Za-z0-9_-]{8,100}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "sessionId 格式无效");
        }
        ConversationSessionService.ConversationDetail detail = sessionService.loadOwned(
                singleUserContext.requireAuthenticatedUserId(), sessionId);
        if (detail == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在");
        }
        return new ConversationDetailResponse(detail.session(), detail.messages());
    }

    /**
     * 会话详情响应，消息数组保持原始 role/content 结构。
     */
    public record ConversationDetailResponse(
            ConversationSession session,
            List<Object> messages) {
    }
}

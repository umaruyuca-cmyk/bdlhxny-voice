package com.stockwise.agent.routing;

import com.stockwise.llm.ChatIntent;

import java.util.Set;

/**
 * 定义 Route 对真实 Skill Command、WebSearch 和模型等级的不可绕过白名单。
 */
public record RouteExecutionPolicy(
        RequestRoute route,
        ChatIntent compatibleIntent,
        ModelPolicy modelPolicy,
        Set<String> allowedSkillCommands,
        boolean webSearchAllowed,
        boolean webSearchRequired
) {
}

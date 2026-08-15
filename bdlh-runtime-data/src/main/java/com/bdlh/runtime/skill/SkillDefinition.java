package com.bdlh.runtime.skill;

import java.util.List;
import java.util.Map;

/**
 * Skill 定义：一类问题的完整处理方案，含系统指令、可用工具、约束与专属护栏。
 * Agent 按 intent 选定 Skill，把 systemPrompt 注入推理模型，约束其在规则内使用工具完成任务。
 *
 * @param name           Skill 唯一标识，如 "investment-knowledge-qa"
 * @param version        Skill 行为版本，写入 Agent Run 以支持结果复现
 * @param description    用途说明
 * @param systemPrompt   注入推理模型的系统指令（角色 + 规则）
 * @param availableTools 该 Skill 允许调用的工具名，超出范围一律禁用
 * @param constraints    推理参数约束，如 maxTokens / temperature
 * @param guardrailRules 该 Skill 专属护栏规则
 */
public record SkillDefinition(
        String name,
        String version,
        String description,
        String systemPrompt,
        List<String> availableTools,
        Map<String, Object> constraints,
        List<String> guardrailRules
) {
}

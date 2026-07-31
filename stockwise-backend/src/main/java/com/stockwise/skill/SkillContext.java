package com.stockwise.skill;

import com.stockwise.entity.KnowledgeChunkWithScore;

import java.util.List;
import java.util.Map;

/**
 * Skill 执行上下文，由 Agent 在 Step 6 组装。
 * 把用户问题、对话历史、检索结果与项目环境打包，作为推理模型的统一输入。
 *
 * @param userQuestion        本轮用户原始问题
 * @param conversationHistory 近期对话历史
 * @param projectEnvironment  用户持仓/偏好等项目环境
 * @param skillInstruction    来自 SkillDefinition 的系统指令
 * @param availableTools      允许使用的工具列表
 * @param retrievalHit        是否检索到可用知识（Step 5 的过滤结果）
 * @param retrievalResults    检索到的知识列表，未命中时为空
 * @param constraints         推理参数约束
 */
public record SkillContext(
        String userQuestion,
        List<Object> conversationHistory,
        Object projectEnvironment,
        String skillInstruction,
        List<String> availableTools,
        boolean retrievalHit,
        List<KnowledgeChunkWithScore> retrievalResults,
        Map<String, Object> constraints
) {
}

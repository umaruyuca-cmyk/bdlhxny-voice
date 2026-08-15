package com.bdlh.runtime.skill;

import java.util.List;

/**
 * Skill 执行的结构化结果，Agent 据 status 决定下一步（直接输出 / 追问 / 告知无法确定）。
 *
 * @param answer      回答或分析文本
 * @param status      执行状态，驱动 Step 9 分支
 * @param confidence  置信度 0-100
 * @param missingInfo 缺失信息项，status=NEED_MORE_INFO 时填充
 * @param candidates  可入库的候选知识，问题解决后提取
 */
public record SkillResult(
        String answer,
        SkillStatus status,
        int confidence,
        List<String> missingInfo,
        List<KnowledgeCandidate> candidates
) {
}

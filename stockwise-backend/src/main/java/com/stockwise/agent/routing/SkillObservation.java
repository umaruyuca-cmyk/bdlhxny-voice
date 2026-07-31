package com.stockwise.agent.routing;

/**
 * 汇总经过代码校验的 Skill 执行状态，供付费模型门禁作确定性判断。
 */
public record SkillObservation(
        boolean success,
        boolean contractValidated,
        boolean commandMatchesRoute,
        boolean subjectMatches,
        boolean freshnessValidated
) {
}

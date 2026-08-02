package com.stockwise.dto;

import java.util.List;
import java.util.UUID;

/**
 * 返回一次运行中可供界面展示的结构化 Skill Observation，避免前端解析完整审计日志。
 */
public record AgentSkillResults(
        UUID runId,
        List<Item> items
) {

    /** 单条 Skill 结果保留命令名、耗时和原始版本化契约。 */
    public record Item(String command, Long durationMs, Object observation) {
    }
}

package com.bdlh.runtime.skill;

import com.bdlh.runtime.llm.ChatIntent;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * 验证单标的 Skill 使用面向研究结论的输出协议，而非仅要求模型压缩指标摘要。
 */
class SkillRegistryTest {

    @Test
    void stockAnalysisUsesEvidenceDrivenResearchReportProtocol() {
        SkillDefinition skill = new SkillRegistry().get(ChatIntent.STOCK_ANALYSIS);

        assertThat(skill.version()).isEqualTo("1.3.0");
        assertThat(skill.systemPrompt())
                .contains("标准研究报告")
                .contains("事实与推理要分开表达")
                .contains("下一步观察条件")
                .contains("不得自行补造");
    }
}

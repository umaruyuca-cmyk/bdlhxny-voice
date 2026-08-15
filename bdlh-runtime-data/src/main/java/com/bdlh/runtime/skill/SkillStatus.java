package com.bdlh.runtime.skill;

/**
 * Skill 执行状态，驱动 Agent 的 Step 9 分支决策。
 */
public enum SkillStatus {

    RESOLVED,      // 问题已解决，可直接输出方案
    NEED_MORE_INFO,// 需要补充信息，触发追问或联网搜索
    UNSURE         // 信息不足且无法判断，明确告知用户并请求必要信息
}

package com.stockwise.memory;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.stockwise.llm.ChatIntent;
import com.stockwise.agent.routing.ModelPolicy;
import com.stockwise.agent.routing.RequestRoute;
import com.stockwise.agent.routing.RouteSubjectType;
import com.stockwise.agent.routing.SectorType;
import com.stockwise.dto.ChatMode;
import com.stockwise.skill.KnowledgeCandidate;
import lombok.Data;

import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * 会话流程状态，用于在三个暂停点（追问、问是否解决、确认入库）之间持久化与恢复。
 * SSE 连接在暂停点会关闭，下次用户消息进来时由 AgentOrchestrator 读取本状态续跑，而非从头开始。
 */
@Data
@JsonIgnoreProperties(ignoreUnknown = true)
public class SessionState {

    /** Redis 乐观并发版本，新状态为0，每次 CAS 保存后递增。 */
    private long version;

    /** 会话唯一标识。 */
    private String sessionId;

    /** 所属用户。 */
    private Long userId;

    /** 当前所处步骤或暂停点，如 classifying / awaiting_resolution / awaiting_confirm。 */
    private String currentStep;

    /** 当前会话所属的业务模式，用于恢复流程时继续执行同一套路由边界。 */
    private ChatMode chatMode;

    /** 本轮分类出的意图，恢复时复用，避免重复分类。 */
    private ChatIntent intent;

    /** 本轮最终执行路由，恢复时不得退回粗粒度 Intent 直接选 Skill。 */
    private RequestRoute route;

    /** 本轮允许使用的最高模型等级。 */
    private ModelPolicy modelPolicy;

    /** 本轮已确认的6位标的代码。 */
    private String symbol;

    /** 本轮已确认的统一分析对象类型。 */
    private RouteSubjectType subjectType;

    /** 本轮板块对象的行业或概念类型。 */
    private SectorType sectorType;

    /** 本轮已确认的板块名称，避免只用股票代码保存上下文。 */
    private List<String> sectors = new ArrayList<>();

    /** 最近一次模型门禁原因码。 */
    private String gateReason;

    /** 最近一次 Agent Run 标识，用于关联用户结构化反馈。 */
    private UUID lastRunId;

    /** 本轮是否命中知识库。 */
    private boolean retrievalHit;

    /** 最近一次推理的完整回答，供解决后抽取候选知识。 */
    private String lastAnswer;

    /** 本轮使用的 Skill 名，供前端展示与日志。 */
    private String lastSkillName;

    /** 触发本轮回答的原始问题，候选知识入库时作为 problem 记入 metadata。 */
    private String lastQuestion;

    /** 待用户确认入库的候选知识（暂停点 C）。 */
    private List<KnowledgeCandidate> pendingCandidates;

    /** 对话历史，累计用户与助手消息。 */
    private List<ConversationMessage> history = new ArrayList<>();

    /** 用户最近已归档会话的摘要，新会话组装上下文时使用。 */
    private List<String> recentConversationSummaries = new ArrayList<>();
}

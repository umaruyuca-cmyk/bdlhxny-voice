package com.stockwise.agent;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.stockwise.dto.GuardrailResult;
import com.stockwise.dto.IngestResult;
import com.stockwise.dto.AgentSkillResults;
import com.stockwise.dto.AgentRunReplay;
import com.stockwise.dto.ChatMode;
import com.stockwise.dto.ChatInstrument;
import com.stockwise.agent.routing.BusinessRoute;
import com.stockwise.agent.routing.RequestRouter;
import com.stockwise.agent.routing.RouteDecision;
import com.stockwise.agent.routing.RouteExecutionPolicy;
import com.stockwise.agent.routing.RouteExecutionPolicyRegistry;
import com.stockwise.llm.ChatIntent;
import com.stockwise.memory.FeedbackType;
import com.stockwise.memory.MemoryRouter;
import com.stockwise.memory.ConversationMessage;
import com.stockwise.memory.SessionState;
import com.stockwise.memory.SessionStateConflictException;
import com.stockwise.service.AgentRunService;
import com.stockwise.service.ConversationSessionService;
import com.stockwise.service.ExplicitAnalysisExecutor;
import com.stockwise.service.GuardrailService;
import com.stockwise.service.GuardedOutputService;
import com.stockwise.service.OutputGuardrailException;
import com.stockwise.service.KnowledgeExtractor;
import com.stockwise.skill.KnowledgeCandidate;
import com.stockwise.skill.SkillDefinition;
import com.stockwise.skill.SkillRegistry;
import com.stockwise.entity.AgentStep;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.LinkedHashMap;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;

/**
 * Agent 主流程编排器（agentic / function-calling 架构）。
 * 分类后选 Skill 注入 systemPrompt，工具调用交给 DeepSeek 自主决策——检索知识、调 stock-analysis-skill 均由模型按需触发，编排器不再硬编码调用顺序。
 * 暂停点（问是否解决、确认入库）、护栏、记忆、知识闭环全部保留。
 * 修补后由 RouteExecutionPolicy 显式选择确定性能力，上一行描述仅表示改造前行为，不再作为当前执行依据。
 * 当前工作站版本将反馈与知识沉淀移出每轮主流程，回答完成后直接允许继续提问。
 */
@Slf4j
@Component
@ConditionalOnProperty(
        name = "stockwise.legacy-agent-runtime.enabled",
        havingValue = "true")
public class AgentOrchestrator {

    private static final long SSE_TIMEOUT = 300_000L;

    private final RequestRouter requestRouter;
    private final RouteExecutionPolicyRegistry routePolicyRegistry;
    private final SkillRegistry skillRegistry;
    private final ExplicitAnalysisExecutor explicitAnalysisExecutor;
    private final MemoryRouter memoryRouter;
    private final KnowledgeExtractor knowledgeExtractor;
    private final GuardrailService guardrailService;
    private final GuardedOutputService guardedOutputService;
    private final AgentContextBuilder agentContextBuilder;
    private final UserReplyClassifier userReplyClassifier;
    private final AgentRunService agentRunService;
    private final ConversationSessionService conversationSessionService;
    private final ObjectMapper mapper;

    @Value("${stockwise.ai.chat-provider:deepseek}")
    private String generalChatProvider;

    @Value("${spring.ai.openai.chat.options.model:deepseek}")
    private String deepSeekModel;

    @Value("${spring.ai.ollama.chat.model:ollama}")
    private String ollamaModel;

    private final ExecutorService executor;

    public AgentOrchestrator(RequestRouter requestRouter,
                             RouteExecutionPolicyRegistry routePolicyRegistry,
                             SkillRegistry skillRegistry,
                             ExplicitAnalysisExecutor explicitAnalysisExecutor,
                             MemoryRouter memoryRouter,
                             KnowledgeExtractor knowledgeExtractor,
                             GuardrailService guardrailService,
                             GuardedOutputService guardedOutputService,
                             AgentContextBuilder agentContextBuilder,
                             UserReplyClassifier userReplyClassifier,
                             AgentRunService agentRunService,
                             ConversationSessionService conversationSessionService,
                             ObjectMapper mapper,
                             @Qualifier("agentFlowExecutor") ExecutorService executor) {
        this.requestRouter = requestRouter;
        this.routePolicyRegistry = routePolicyRegistry;
        this.skillRegistry = skillRegistry;
        this.explicitAnalysisExecutor = explicitAnalysisExecutor;
        this.memoryRouter = memoryRouter;
        this.knowledgeExtractor = knowledgeExtractor;
        this.guardrailService = guardrailService;
        this.guardedOutputService = guardedOutputService;
        this.agentContextBuilder = agentContextBuilder;
        this.userReplyClassifier = userReplyClassifier;
        this.agentRunService = agentRunService;
        this.conversationSessionService = conversationSessionService;
        this.mapper = mapper;
        this.executor = executor;
    }

    /**
     * 对话入口：创建 SSE 并异步执行流程，立即返回 emitter 供 Controller 写出。
     */
    public SseEmitter handle(Long userId, String sessionId, ChatMode mode,
                             String message, ChatInstrument instrument) {
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT);
        // 1. 注册超时与错误回调，避免连接泄漏
        emitter.onTimeout(emitter::complete);
        emitter.onError(t -> emitter.complete());
        // 2. 后台线程跑编排，及时释放 Tomcat 请求线程
        try {
            executor.execute(() -> runFlow(
                    userId,
                    sessionId,
                    mode,
                    message,
                    instrument,
                    emitter));
        } catch (RejectedExecutionException error) {
            // 3. 有界队列满时明确结束请求，不在Tomcat线程中降级执行重任务
            sendEvent(emitter, "done", Map.of(
                    "status", "SYSTEM_BUSY",
                    "message", "当前请求较多，请稍后重试"));
            emitter.complete();
        }
        return emitter;
    }

    /**
     * 保留旧调用点的兼容入口，新请求应显式传入业务模式。
     */
    public SseEmitter handle(Long userId, String sessionId, String message, ChatInstrument instrument) {
        ChatMode mode = instrument == null ? ChatMode.GENERAL : ChatMode.STOCK_AGENT;
        return handle(userId, sessionId, mode, message, instrument);
    }

    /**
     * 主流程分发：命中暂停点则恢复续跑，否则走首次流程。
     */
    private void runFlow(Long userId, String sessionId, ChatMode mode, String message,
                         ChatInstrument instrument,
                         SseEmitter emitter) {
        try {
            // 1. Stock Agent 无标的时仍允许板块和市场问题，单标的缺失由 Route 统一追问。
            SessionState state = memoryRouter.loadWorking(sessionId);
            if (state != null) {
                String step = state.getCurrentStep();
                // 2. 同一会话已有 ReAct 在执行时拒绝并发覆盖
                if ("react_running".equals(step) || "archiving".equals(step)) {
                    sendEvent(emitter, "done", Map.of(
                            "status", "SESSION_BUSY",
                            "message", "当前会话仍在处理中，请稍后重试"));
                    emitter.complete();
                    return;
                }
                // 3. 旧会话的反馈暂停点迁移为可继续输入状态，不再强制追问解决和入库
                if ("awaiting_resolution".equals(step) || "awaiting_confirm".equals(step)) {
                    state.setCurrentStep("idle");
                    state.setPendingCandidates(null);
                    memoryRouter.saveWorking(state);
                }
            }
            // 4. 进入本轮独立路由
            firstRun(
                    userId,
                    sessionId,
                    mode,
                    message,
                    instrument,
                    emitter);
        } catch (SessionStateConflictException e) {
            log.warn("会话并发冲突: {}", e.getMessage());
            sendEvent(emitter, "done", Map.of(
                    "status", "SESSION_CONFLICT",
                    "message", "会话已被另一请求更新，请重新发送"));
            emitter.complete();
        } catch (Exception e) {
            log.error("编排流程异常", e);
            sendEvent(emitter, "error", Map.of("message", safe(e)));
            emitter.complete();
        }
    }

    /**
     * 首次流程：输入护栏 → 分类选 Skill → DeepSeek 自主调工具推理。
     * 不再固定检索/调工具，知识与行情数据由模型按需通过 StockTools 获取。
     * 修补后保留原暂停点，但实际执行改为 Route 先行并由 Java 显式调用允许的能力。
     */
    private void firstRun(Long userId, String sessionId, ChatMode mode, String message,
                          ChatInstrument instrument,
                          SseEmitter emitter) {
        // Step 0：输入护栏，拦截空消息与 Prompt 注入
        GuardrailResult inputCheck = guardrailService.checkInput(message);
        if (!inputCheck.passed()) {
            sendEvent(emitter, "done", Map.of("status", "REFUSED", "reason", inputCheck.reason()));
            emitter.complete();
            return;
        }
        // Step 1：初始化或续用会话状态，记录用户消息
        SessionState state = memoryRouter.loadWorking(sessionId);
        boolean newSession = state == null;
        if (newSession) {
            state = new SessionState();
            state.setSessionId(sessionId);
            state.setUserId(userId);
        }
        state.setChatMode(mode);
        appendHistory(state, "user", message);
        state.setLastQuestion(message);

        // Step 2：规则优先并使用本地 Intent 兜底，输出不可变 RouteDecision
        sendStatus(emitter, "classifying", null, null);
        RouteDecision decision = mode == ChatMode.GENERAL
                ? requestRouter.routeGeneral(message)
                : requestRouter.routeStock(message, instrument == null ? null : instrument.symbol());
        applyDecision(state, decision);
        if (newSession) {
            // 1. 路由确定标的后再做用户隔离的语义召回，避免只按时间盲目注入历史。
            state.setRecentConversationSummaries(
                    loadRelevantSummaries(userId, message, decision.symbol()));
        }

        // Step 6：兼容 SkillDefinition 只提供角色规则，真实 Command 由 Route 白名单控制
        SkillDefinition skill = skillRegistry.get(decision);
        state.setLastSkillName(skill.name());
        state.setCurrentStep("react_running");
        memoryRouter.saveWorking(state);
        sendBusinessStatus(emitter, decision, skill);

        // Step 7：显式执行 Route，只有门禁放行的分析类请求才能调用 DeepSeek
        streamAndFinalize(
                emitter, state, skill, message, decision);
    }

    /**
     * 暂停点 B 恢复：按用户反馈判断是否解决，已解决则抽取候选知识进入暂停点 C，未解决则带补充重跑推理。
     */
    private void resumeFromResolution(String sessionId, String message,
                                      SessionState state,
                                      SseEmitter emitter) {
        // 1. 简单判定用户是否表示已解决
        FeedbackType feedbackType = userReplyClassifier.classifyResolution(message);
        boolean resolved = feedbackType == FeedbackType.RESOLVED;
        if (resolved) {
            // 2. 已解决：抽取候选知识，进入"等待确认入库"暂停点
            List<KnowledgeCandidate> candidates = knowledgeExtractor.extract(state.getLastQuestion(), state.getLastAnswer());
            state.setPendingCandidates(candidates);
            state.setCurrentStep("awaiting_confirm");
            memoryRouter.saveWorking(state);
            recordFeedbackSafely(state, sessionId, feedbackType, message,
                    Map.of("step", "awaiting_resolution"));
            // 3. 推送候选给前端，等用户确认/修改/拒绝
            sendEvent(emitter, "suggest", Map.of("items", candidates));
            sendEvent(emitter, "ask", Map.of("prompt", "以上知识将加入知识库，回复\"确认\"入库，或输入修改/拒绝"));
            sendEvent(emitter, "done", Map.of("status", "RESOLVED", "resolved", true, "candidates", candidates.size()));
            emitter.complete();
            return;
        }
        // 4. 未解决：把补充当新输入，重新路由后按显式策略执行
        appendHistory(state, "user", message);
        String combinedQuestion = state.getLastQuestion() + "\n用户补充：" + message;
        RouteDecision decision = state.getChatMode() == ChatMode.GENERAL
                ? requestRouter.routeGeneral(combinedQuestion)
                : requestRouter.routeStock(combinedQuestion, state.getSymbol());
        applyDecision(state, decision);
        SkillDefinition skill = skillRegistry.get(decision);
        state.setCurrentStep("react_running");
        memoryRouter.saveWorking(state);
        recordFeedbackSafely(state, sessionId, feedbackType, message,
                Map.of("step", "awaiting_resolution"));
        sendBusinessStatus(emitter, decision, skill);
        streamAndFinalize(
                emitter, state, skill, combinedQuestion, decision);
    }

    /**
     * 暂停点 C 恢复：用户确认后对每条候选知识去重入库，拒绝或无候选则直接收档。
     */
    private void confirmAndIngest(String sessionId, String message, SessionState state, SseEmitter emitter) {
        // 1. 判定用户是否确认入库
        FeedbackType feedbackType = userReplyClassifier.classifyKnowledgeConfirmation(message);
        boolean confirmed = feedbackType == FeedbackType.KNOWLEDGE_CONFIRMED;
        List<KnowledgeCandidate> candidates = state.getPendingCandidates();
        // 2. 先抢占归档状态，再执行反馈、知识入库和归档等有副作用操作
        state.setCurrentStep("archiving");
        memoryRouter.saveWorking(state);
        try {
            recordFeedbackSafely(
                    state,
                    sessionId,
                    feedbackType,
                    message,
                    Map.of("candidateCount", candidates == null ? 0 : candidates.size()));
            if (!confirmed || candidates == null || candidates.isEmpty()) {
                // 3. 拒绝或无候选：归档后收档
                archiveThenClear(state, sessionId);
                sendEvent(emitter, "done", Map.of("status", "CLOSED", "ingested", 0));
                emitter.complete();
                return;
            }
            // 4. 逐条入库，统计结果
            int ingested = 0;
            int duplicate = 0;
            for (KnowledgeCandidate c : candidates) {
                // 入库护栏：长度门槛 + 禁止措辞
                GuardrailResult kCheck = guardrailService.checkKnowledge(c);
                if (!kCheck.passed()) {
                    log.warn("入库护栏拒绝: {}", kCheck.reason());
                    continue;
                }
                IngestResult r = memoryRouter.ingestConfirmedKnowledge(
                        c, state.getLastQuestion(), state.getUserId());
                if ("ingested".equals(r.status())) {
                    ingested++;
                } else if ("duplicate".equals(r.status())) {
                    duplicate++;
                }
            }
            archiveThenClear(state, sessionId);
            sendEvent(emitter, "done", Map.of(
                    "status", "INGESTED", "ingested", ingested, "duplicate", duplicate, "total", candidates.size()));
            emitter.complete();
        } catch (RuntimeException error) {
            // 5. 副作用失败时恢复确认暂停点，允许用户安全重试
            state.setCurrentStep("awaiting_confirm");
            memoryRouter.saveWorking(state);
            throw error;
        }
    }

    /**
     * 流式推理并收尾：注册 StockTools 让 DeepSeek 自主调用，逐 token 推前端，完成后落库、护栏、进入暂停点。
     * 修补后不再注册自主工具，输出流来自 ExplicitAnalysisExecutor 选择的模板、本地模型或门禁后的付费模型。
     */
    private void streamAndFinalize(SseEmitter emitter, SessionState state,
                                   SkillDefinition skill, String userMessage,
                                   RouteDecision decision) {
        StringBuilder answer = new StringBuilder();
        String prompt = agentContextBuilder.build(state, userMessage);
        AgentRunContext runContext = agentRunService.start(
                state.getUserId(), state.getSessionId(), userMessage, state.getIntent(), skill);
        state.setLastRunId(runContext.runId());
        memoryRouter.saveWorking(state);
        // 1. 先返回稳定 Run ID，前端可在推理期间关联日志和后续回放
        sendEvent(emitter, "agent_run", Map.of(
                "runId", runContext.runId().toString(),
                "sessionId", state.getSessionId(),
                "route", decision.businessRoute().name(),
                "internalRoute", decision.route().name(),
                "mode", state.getChatMode() == null ? "legacy" : state.getChatMode().value()));
        try {
            RouteExecutionPolicy executionPolicy = routePolicyRegistry.get(decision.route());
            agentRunService.recordRouteDecision(runContext, decision,
                    executionPolicy.allowedSkillCommands(), executionPolicy.webSearchRequired());
            sendResearchTrace(emitter, runContext, decision, "running", "ROUTE_DECISION");
            if (decision.businessRoute() == BusinessRoute.TOOL_AGENT) {
                sendStatus(emitter, "searching_web", null, skill.name());
            }
            ExplicitAnalysisExecutor.ExecutionOutput execution = explicitAnalysisExecutor.execute(
                    decision, skill, prompt, userMessage, runContext);
            if (decision.businessRoute() == BusinessRoute.TOOL_AGENT) {
                sendStatus(emitter, "reading_sources", null, skill.name());
            }
            agentRunService.recordReactTermination(
                    runContext,
                    execution.reactTerminationReason().name(),
                    execution.reactRounds(),
                    execution.reactToolCalls(),
                    execution.reactDetail());
            boolean paid = "PAID".equals(execution.modelTier());
            agentRunService.recordModelGate(runContext, paid, execution.gateReason());
            agentRunService.recordModelCall(runContext, execution.modelTier(), decision.route().name());
            sendResearchTrace(emitter, runContext, decision, "running", "MODEL_CALL");
            state.setGateReason(execution.gateReason());
            guardedOutputService.guard(execution.content())
                    .subscribe(token -> {
                        // 3. 只有通过发送前护栏的完整句子片段才能推送前端
                        sendEvent(emitter, "token", Map.of("content", token));
                        answer.append(token);
                    }, error -> {
                        log.error("推理流异常，runId={}", runContext.runId(), error);
                        agentRunService.fail(runContext, error);
                        releaseRunningState(state);
                        if (error instanceof OutputGuardrailException) {
                            sendEvent(emitter, "error", Map.of(
                                    "code", "OUTPUT_GUARD_BLOCKED",
                                    "message", "回答未通过输出安全检查，已停止发送",
                                    "runId", runContext.runId().toString()));
                        } else {
                            sendEvent(emitter, "error", Map.of(
                                    "code", "MODEL_STREAM_FAILED",
                                    "message", safe(error),
                                    "runId", runContext.runId().toString()));
                        }
                        emitter.complete();
                    }, () -> {
                        try {
                            // 4. 落库回答与历史
                            String full = answer.toString();
                            state.setLastAnswer(full);
                            appendHistory(state, "assistant", full);
                            // 5. 对已发送前校验的完整答案再次检查，防止跨片段规则回归
                            GuardrailResult outputCheck = guardrailService.checkOutput(full);
                            if (!outputCheck.passed()) {
                                throw new OutputGuardrailException(outputCheck.reason());
                            }
                            saveConversationSnapshotSafely(state);
                            // 6. 完成本轮后回到可继续输入状态，反馈和知识沉淀不再阻塞主对话
                            state.setCurrentStep("idle");
                            memoryRouter.saveWorking(state);
                            agentRunService.complete(runContext, full);
                            List<Map<String, String>> clarificationOptions =
                                    clarificationOptions(decision);
                            if (!clarificationOptions.isEmpty()) {
                                sendEvent(emitter, "clarification", Map.of(
                                        "reason", decision.reasonCode(),
                                        "prompt", "选择一个分析方向，我会联网检索后给出精简结论。",
                                        "options", clarificationOptions));
                            }
                            Map<String, Object> done = new LinkedHashMap<>();
                            done.put("skill", skill.name());
                            done.put("route", decision.businessRoute().name());
                            done.put("internalRoute", decision.route().name());
                            done.put("mode", state.getChatMode() == null ? "legacy" : state.getChatMode().value());
                            done.put("modelTier", execution.modelTier());
                            done.putAll(modelMetadata(execution.modelTier()));
                            done.put("gateReason", execution.gateReason());
                            done.put("reactTerminationReason", execution.reactTerminationReason().name());
                            done.put("reactRounds", execution.reactRounds());
                            done.put("reactToolCalls", execution.reactToolCalls());
                            Map<String, Object> skillResult = skillResultForDisplay(
                                    runContext.runId(), runContext.userId(), execution.reactToolCalls(),
                                    decision.businessRoute());
                            done.put("skillResultAvailable", skillResult != null);
                            if (skillResult != null) {
                                // 7. 将本轮已完成的结构化结果随 SSE 返回，前端无需再次读取运行审计接口。
                                done.put("skillResult", skillResult);
                            }
                            done.put("status", decision.needsClarification()
                                    ? "NEED_CLARIFICATION"
                                    : "COMPLETED");
                            done.put("runId", runContext.runId().toString());
                            done.put("sessionId", state.getSessionId());
                            Map<String, Object> researchTrace = researchTrace(
                                    runContext, decision, "completed", "FINAL_ANSWER");
                            done.put("researchTrace", researchTrace);
                            sendEvent(emitter, "research_trace", researchTrace);
                            sendEvent(emitter, "done", done);
                            emitter.complete();
                        } catch (Exception error) {
                            log.error("推理收尾异常，runId={}", runContext.runId(), error);
                            agentRunService.fail(runContext, error);
                            releaseRunningState(state);
                            sendEvent(emitter, "error", Map.of(
                                    "message", safe(error),
                                    "runId", runContext.runId().toString()));
                            emitter.complete();
                        }
                    });
        } catch (RuntimeException error) {
            agentRunService.fail(runContext, error);
            releaseRunningState(state);
            throw error;
        }
    }

    /**
     * 发送 status 事件，携带当前步骤与 Skill 名。
     */
    private void sendStatus(SseEmitter emitter, String step, Boolean hit, String skill) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("step", step);
        if (hit != null) {
            data.put("hit", hit);
        }
        if (skill != null) {
            data.put("skill", skill);
        }
        sendEvent(emitter, "status", data);
    }

    /**
     * 将内部细分路由转换为前端可理解的业务执行阶段。
     */
    private void sendBusinessStatus(SseEmitter emitter, RouteDecision decision, SkillDefinition skill) {
        String step = switch (decision.businessRoute()) {
            case DIRECT_CHAT -> "direct_chat";
            case TOOL_AGENT -> "react_planning";
            case STOCK_ANALYSIS -> "stock_validating";
        };
        sendStatus(emitter, step, null, skill.name());
    }

    /**
     * 为适合渐进选择的模糊问题提供结构化选项，避免模型先生成大段通用说明。
     */
    private List<Map<String, String>> clarificationOptions(RouteDecision decision) {
        if (!"GENERAL_RESEARCH_SCOPE_REQUIRED".equals(decision.reasonCode())) {
            return List.of();
        }
        return List.of(
                Map.of(
                        "label", "昨日复盘",
                        "message", "搜索并复盘最近一个已完成交易日的该板块表现，"
                                + "重点看涨跌、成交和领涨细分方向。"),
                Map.of(
                        "label", "近期趋势",
                        "message", "搜索并分析该板块近20个交易日的趋势、强弱和关键变化。"),
                Map.of(
                        "label", "资金强弱",
                        "message", "搜索并分析该板块近期资金流向、成交变化和内部强弱分化。"),
                Map.of(
                        "label", "消息影响",
                        "message", "搜索该板块近期重要新闻、政策和事件，并分析其影响。"));
    }

    /**
     * 提取本轮可视化所需的首个 StockSkill 契约，避免前端额外进行审计回读。
     */
    private Map<String, Object> skillResultForDisplay(UUID runId,
                                                       Long userId,
                                                       int reactToolCalls,
                                                       BusinessRoute businessRoute) {
        if (userId == null || reactToolCalls <= 0 || businessRoute != BusinessRoute.STOCK_ANALYSIS) {
            return null;
        }
        return agentRunService.skillResults(runId, userId).items().stream()
                .map(AgentSkillResults.Item::observation)
                .filter(Map.class::isInstance)
                .map(Map.class::cast)
                .filter(item -> item.containsKey("schemaVersion")
                        && item.containsKey("command")
                        && item.containsKey("data"))
                .findFirst()
                .orElse(null);
    }

    /**
     * 将审计步骤投影为面向用户的研究路径，供 SSE 实时展示而不暴露原始审计载荷。
     */
    private void sendResearchTrace(SseEmitter emitter,
                                   AgentRunContext context,
                                   RouteDecision decision,
                                   String status,
                                   String currentStage) {
        sendEvent(emitter, "research_trace", researchTrace(context, decision, status, currentStage));
    }

    /**
     * 复用已持久化的运行步骤生成统一路径，确保实时展示与回放结果一致。
     */
    private Map<String, Object> researchTrace(AgentRunContext context,
                                              RouteDecision decision,
                                              String status,
                                              String currentStage) {
        AgentRunReplay replay = agentRunService.replay(context.runId(), context.userId());
        List<Map<String, Object>> steps = replay.steps().stream()
                .filter(step -> isTraceStep(step.getStepType()))
                .map(this::traceStep)
                .toList();
        Map<String, Object> trace = new LinkedHashMap<>();
        trace.put("runId", context.runId().toString());
        trace.put("route", decision.businessRoute().name());
        trace.put("status", status);
        trace.put("currentStage", currentStage);
        trace.put("steps", steps);
        return trace;
    }

    private boolean isTraceStep(String type) {
        return List.of("ROUTE_DECISION", "REACT_DECISION", "TOOL_CALL", "TOOL_OBSERVATION",
                        "REACT_TERMINATION", "MODEL_GATE", "MODEL_CALL", "FINAL_ANSWER",
                        "POLICY_REJECTION", "ERROR")
                .contains(type);
    }

    private Map<String, Object> traceStep(AgentStep step) {
        Map<String, Object> payload = step.getPayload() == null ? Map.of() : step.getPayload();
        String type = step.getStepType();
        Map<String, Object> view = new LinkedHashMap<>();
        view.put("type", type);
        view.put("title", traceTitle(type));
        view.put("status", traceStatus(type, payload));
        view.put("detail", traceDetail(step, payload));
        view.put("technical", traceTechnical(step, payload));
        return view;
    }

    private String traceTitle(String type) {
        return Map.of(
                "ROUTE_DECISION", "路由", "REACT_DECISION", "规划", "TOOL_CALL", "工具",
                "TOOL_OBSERVATION", "结果", "REACT_TERMINATION", "收束", "MODEL_GATE", "模型门禁",
                "MODEL_CALL", "生成", "FINAL_ANSWER", "完成", "POLICY_REJECTION", "策略拦截",
                "ERROR", "执行错误").getOrDefault(type, type);
    }

    private String traceStatus(String type, Map<String, Object> payload) {
        if ("POLICY_REJECTION".equals(type) || "ERROR".equals(type)
                || ("MODEL_GATE".equals(type) && Boolean.FALSE.equals(payload.get("allowed")))) {
            return "blocked";
        }
        return "done";
    }

    private String traceDetail(AgentStep step, Map<String, Object> payload) {
        return switch (step.getStepType()) {
            case "ROUTE_DECISION" -> "请求已映射到「" + routeDisplay(value(payload, "route", step.getName())) + "」执行路径";
            case "REACT_DECISION" -> "ReAct 第 " + value(payload, "round", "1")
                    + " 轮：" + value(payload, "reasoningSummary", "选择下一步工具 Action");
            case "TOOL_CALL" -> "正在调用 " + toolDisplay(step.getName()) + " 获取研究数据";
            case "TOOL_OBSERVATION" -> "工具已返回结构化结果" + durationSuffix(payload);
            case "REACT_TERMINATION" -> "ReAct 已获得足够信息，结束工具调用";
            case "MODEL_GATE" -> Boolean.FALSE.equals(payload.get("allowed"))
                    ? "数据或规则未通过，停止生成方向性结论"
                    : "数据质量与规则校验已通过，允许生成结论";
            case "MODEL_CALL" -> "正在调用回答模型生成解释性结论";
            case "FINAL_ANSWER" -> "已生成最终回答与分析看板";
            default -> step.getSummary();
        };
    }

    private String traceTechnical(AgentStep step, Map<String, Object> payload) {
        return switch (step.getStepType()) {
            case "ROUTE_DECISION" -> "Route · " + value(payload, "route", step.getName());
            case "REACT_DECISION" -> "Action · " + value(payload, "action", step.getName());
            case "TOOL_CALL" -> "Tool · " + step.getName();
            case "TOOL_OBSERVATION" -> "Observation · " + step.getName();
            case "REACT_TERMINATION" -> "Termination · " + value(payload, "reason", step.getName());
            case "MODEL_GATE" -> "Gate · " + value(payload, "reasonCode", "passed");
            case "MODEL_CALL" -> "Model · " + value(payload, "modelTier", step.getName());
            case "FINAL_ANSWER" -> "FINAL_ANSWER";
            default -> step.getName();
        };
    }

    private String durationSuffix(Map<String, Object> payload) {
        Object duration = payload.get("durationMs");
        return duration == null ? "" : " · 耗时 " + duration + "ms";
    }

    private String value(Map<String, Object> payload, String key, String fallback) {
        Object value = payload.get(key);
        return value == null || value.toString().isBlank() ? fallback : value.toString();
    }

    private String routeDisplay(String route) {
        return Map.of("STOCK_DECISION", "标的决策", "MARKET_FACT", "行情与指标",
                "EXTERNAL_RESEARCH", "联网研究", "KNOWLEDGE_QA", "投资知识",
                "GENERAL_CHAT", "普通问答", "NEED_CLARIFICATION", "需要补充")
                .getOrDefault(route, route);
    }

    private String toolDisplay(String tool) {
        return Map.of("stock", "StockSkill · 标的分析", "sector", "StockSkill · 板块分析",
                "quant", "StockSkill · 量化分析", "portfolio", "StockSkill · 组合分析",
                "webSearch", "联网检索", "searchInvestmentKnowledge", "知识库检索")
                .getOrDefault(tool, tool);
    }

    /**
     * 将策略层级转换为前端可理解的实际回答来源，避免把 LOCAL 误解为本地模型。
     */
    private Map<String, Object> modelMetadata(String modelTier) {
        if ("TEMPLATE".equals(modelTier)) {
            return Map.of("modelProvider", "rule", "modelName", "规则与 Skill 数据");
        }
        if ("PAID".equals(modelTier)) {
            return Map.of("modelProvider", "deepseek", "modelName", deepSeekModel);
        }
        boolean ollama = "ollama".equalsIgnoreCase(generalChatProvider);
        return Map.of(
                "modelProvider", ollama ? "ollama" : "deepseek",
                "modelName", ollama ? ollamaModel : deepSeekModel);
    }

    /**
     * 统一发送 SSE 事件，自动补 type 字段；发送异常忽略（emitter 可能已关闭）。
     */
    private void sendEvent(SseEmitter emitter, String type, Map<String, Object> payload) {
        try {
            Map<String, Object> data = new LinkedHashMap<>(payload);
            data.put("type", type);
            emitter.send(SseEmitter.event().data(mapper.writeValueAsString(data)));
        } catch (Exception e) {
            // 忽略：客户端连接已断
        }
    }

    private void appendHistory(SessionState state, String role, String content) {
        if ("assistant".equals(role)) {
            state.getHistory().add(ConversationMessage.assistant(content));
            return;
        }
        state.getHistory().add(ConversationMessage.user(content));
    }

    /**
     * 将当前轮完整消息写入会话目录和可恢复快照，持久化失败只记录告警，不回滚已经完成的回答。
     */
    private void saveConversationSnapshotSafely(SessionState state) {
        try {
            String title = state.getHistory() == null
                    ? "新的研究"
                    : state.getHistory().stream()
                    .filter(message -> "user".equals(message.role()))
                    .map(ConversationMessage::content)
                    .findFirst()
                    .orElse("新的研究");
            conversationSessionService.saveTurn(
                    state.getUserId(),
                    state.getSessionId(),
                    state.getChatMode(),
                    title,
                    state.getHistory());
        } catch (RuntimeException error) {
            log.warn("会话快照保存失败，sessionId={}: {}", state.getSessionId(), error.getMessage());
        }
    }

    /**
     * 将最终路由写入短期状态，恢复流程不得只依赖旧 Intent。
     */
    private void applyDecision(SessionState state, RouteDecision decision) {
        state.setIntent(decision.compatibleIntent());
        state.setRoute(decision.route());
        state.setModelPolicy(decision.modelPolicy());
        state.setSymbol(decision.symbol());
        state.setSubjectType(decision.subjectType());
        state.setSectorType(decision.sectorType());
        state.setSectors(decision.sectors());
        state.setGateReason(decision.reasonCode());
    }

    /**
     * 归档会话到 PG 中期记忆，再清除 Redis 短期状态。
     */
    private void archiveThenClear(SessionState state, String sessionId) {
        // 1. 调用方已通过 CAS 抢占归档权，写入情景记忆后清除对应版本的工作记忆
        memoryRouter.archiveEpisode(
                state.getUserId(),
                sessionId,
                state.getSymbol(),
                state.getHistory(),
                buildArchiveSummary(state));
        memoryRouter.clearWorking(state);
    }

    /**
     * 反馈落库失败只记录告警，不能阻断已经完成 CAS 状态迁移的主对话流程。
     */
    private void recordFeedbackSafely(SessionState state,
                                      String sessionId,
                                      FeedbackType feedbackType,
                                      String message,
                                      Map<String, Object> metadata) {
        try {
            memoryRouter.recordFeedback(
                    state.getUserId(),
                    sessionId,
                    state.getLastRunId(),
                    feedbackType,
                    message,
                    metadata);
        } catch (RuntimeException error) {
            log.warn("结构化反馈保存失败，sessionId={}, type={}: {}",
                    sessionId, feedbackType, error.getMessage());
        }
    }

    /**
     * 推理异常时释放 react_running 状态，使下一条用户消息能够重新进入路由。
     */
    private void releaseRunningState(SessionState state) {
        try {
            state.setCurrentStep("error");
            memoryRouter.saveWorking(state);
        } catch (Exception e) {
            log.warn("释放会话运行状态失败: {}", e.getMessage());
        }
    }

    /**
     * 加载与当前问题和标的相关的长期情景摘要，底层负责向量故障时的最近摘要降级。
     */
    private List<String> loadRelevantSummaries(Long userId, String question, String symbol) {
        try {
            return memoryRouter.loadRelevantEpisodes(userId, question, symbol);
        } catch (Exception e) {
            log.warn("加载长期情景记忆失败，本轮按无历史上下文继续: {}", e.getMessage());
            return List.of();
        }
    }

    /**
     * 生成可检索的确定性会话摘要，避免仅把最后问题误当成完整摘要。
     */
    private String buildArchiveSummary(SessionState state) {
        String question = truncate(state.getLastQuestion(), 300);
        String answer = truncate(state.getLastAnswer(), 700);
        String subject = state.getSymbol() != null && !state.getSymbol().isBlank()
                ? state.getSymbol()
                : state.getSectors() == null || state.getSectors().isEmpty()
                ? state.getSubjectType() == null ? "未指定" : state.getSubjectType().name()
                : String.join("、", state.getSectors());
        return "分析对象：" + subject + "\n问题：" + question + "\n历史结论：" + answer;
    }

    private String truncate(String text, int maxLength) {
        if (text == null) {
            return "";
        }
        String normalized = text.trim();
        if (normalized.length() <= maxLength) {
            return normalized;
        }
        return normalized.substring(0, maxLength) + "…";
    }

    private String safe(Throwable e) {
        String m = e.getMessage();
        return m == null ? e.getClass().getSimpleName() : m;
    }
}

package com.bdlh.runtime.agent.react;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.agent.AgentRunContext;
import com.bdlh.runtime.agent.routing.RequestRoute;
import com.bdlh.runtime.agent.routing.RouteDecision;
import com.bdlh.runtime.service.ExplicitAnalysisExecutor;
import com.bdlh.runtime.skill.SkillDefinition;
import com.bdlh.runtime.tool.StockTools;
import com.bdlh.runtime.websearch.gateway.WebSearchGateway;
import com.bdlh.runtime.websearch.model.SearchTask;
import com.bdlh.runtime.websearch.planner.LocalSearchPlanner;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatModel;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * 普通问答的受控 LangChain4j ReAct 执行器。
 * 模型只负责选择下一步或结束，真实工具调用、轮数上限与最终流式回答仍由后端控制。
 */
@Component
public class LangChain4jGeneralReactAgent {

    private static final int MAX_ROUNDS = 2;
    private static final int MAX_OBSERVATION_CHARS = 12_000;

    private static final String PLANNER_PROMPT = """
            你是智能问答 Agent 的 ReAct 规划器。你不直接回答用户问题，只返回一个 JSON 对象。
            可选 action：FINAL、WEB_SEARCH、KNOWLEDGE_BASE。
            - FINAL：现有上下文足以回答，或工具不能提升答案质量。
            - WEB_SEARCH：用户明确要求最新、今天、新闻、公告、链接、核验或需要外部事实。
            - KNOWLEDGE_BASE：问题是投资术语、策略、方法或内部知识，且内部资料可能有帮助。
            安全规则：不把天气、实时行情等问题伪装成已获得实时数据；没有专用实时工具时，搜索结果只能作为网页资料。
            返回格式严格为：{"action":"FINAL|WEB_SEARCH|KNOWLEDGE_BASE","reason":"不超过30字的可展示原因"}。
            不输出 Markdown、解释文字、思维过程或其他字段。
            """;

    private final ChatModel chatModel;
    private final ObjectMapper objectMapper;
    private final WebSearchGateway webSearchGateway;
    private final LocalSearchPlanner searchPlanner;
    private final StockTools stockTools;
    private final BoundedReactLoop reactLoop;

    public LangChain4jGeneralReactAgent(ChatModel chatModel,
                                        ObjectMapper objectMapper,
                                        WebSearchGateway webSearchGateway,
                                        LocalSearchPlanner searchPlanner,
                                        StockTools stockTools,
                                        BoundedReactLoop reactLoop) {
        this.chatModel = chatModel;
        this.objectMapper = objectMapper;
        this.webSearchGateway = webSearchGateway;
        this.searchPlanner = searchPlanner;
        this.stockTools = stockTools;
        this.reactLoop = reactLoop;
    }

    /**
     * 以最多两轮受控 Action 补充普通问答证据，并返回交给流式回答模型的上下文。
     */
    public ExplicitAnalysisExecutor.ExecutionOutput execute(RouteDecision decision,
                                                             SkillDefinition skill,
                                                             String contextualPrompt,
                                                             String question,
                                                             AgentRunContext runContext,
                                                             java.util.function.BiFunction<String, String, Flux<String>> answerStream) {
        List<String> observations = new ArrayList<>();
        int rounds = 0;
        int toolCalls = 0;
        String termination = "模型直接回答";
        for (int round = 1; round <= MAX_ROUNDS; round++) {
            rounds = round;
            Plan plan = plan(question, observations);
            if (!isAllowed(decision.route(), plan.action())) {
                termination = "当前 Route 不允许该工具，直接回答";
                break;
            }
            if (plan.action() == Action.FINAL) {
                termination = plan.reason();
                break;
            }
            if (plan.action() == Action.WEB_SEARCH) {
                List<SearchTask> tasks = searchPlanner.planGeneral(question);
                ReactLoopResult loop = reactLoop.execute(
                        decision, skill, runContext, List.of(new ReactToolAction(
                                "webSearch",
                                java.util.Map.of("query", tasks.get(0).query(), "reactRound", round),
                                plan.reason(),
                                () -> serialize(webSearchGateway.search(tasks)))));
                if (!loop.completed()) {
                    termination = loop.detail();
                    break;
                }
                String observation = observation(loop, "webSearch");
                observations.add("网页检索结果：\n" + clip(observation));
                toolCalls++;
                termination = plan.reason();
                continue;
            }
            if (plan.action() == Action.KNOWLEDGE_BASE) {
                ReactLoopResult loop = reactLoop.execute(
                        decision, skill, runContext, List.of(new ReactToolAction(
                                "searchInvestmentKnowledge",
                                java.util.Map.of("question", question, "reactRound", round),
                                plan.reason(),
                                () -> stockTools.searchInvestmentKnowledge(question))));
                if (!loop.completed()) {
                    termination = loop.detail();
                    break;
                }
                String observation = observation(loop, "searchInvestmentKnowledge");
                observations.add("知识库检索结果：\n" + clip(observation));
                toolCalls++;
                termination = plan.reason();
            }
        }
        String evidence = observations.isEmpty()
                ? "本轮未调用工具，请基于已知通用知识直接回答；不得声称已经检索外部实时资料。"
                : String.join("\n\n", observations);
        String finalPrompt = contextualPrompt + "\n\nReAct 工具观察（仅在有事实支持时引用）：\n" + evidence
                + "\n\n回答要求：先直接回答，再给不超过 4 条最关键依据。"
                + "若网页资料时间不匹配“今天/最新”，要明确说明时效限制，不得虚构实时结论。";
        return new ExplicitAnalysisExecutor.ExecutionOutput(
                answerStream.apply(skill.systemPrompt(), finalPrompt),
                "LOCAL_REACT",
                observations.isEmpty() ? "REACT_NO_TOOL_NEEDED" : "REACT_TOOL_EVIDENCE",
                ReactTerminationReason.FINAL_ANSWER,
                rounds,
                toolCalls,
                termination);
    }

    private Plan plan(String question, List<String> observations) {
        String prompt = "用户问题：\n" + question + "\n\n已获得的观察：\n"
                + (observations.isEmpty() ? "无" : String.join("\n\n", observations));
        try {
            String response = chatModel.chat(List.of(
                    SystemMessage.from(PLANNER_PROMPT), UserMessage.from(prompt)))
                    .aiMessage()
                    .text();
            JsonNode node = objectMapper.readTree(response == null ? "{}" : response);
            Action action = Action.from(node.path("action").asText());
            String reason = node.path("reason").asText("规划完成");
            return new Plan(action, reason.isBlank() ? "规划完成" : reason);
        } catch (Exception ignored) {
            // 1. 规划模型或 JSON 不可用时保守降级为直接回答，避免普通问答不可用。
            return new Plan(Action.FINAL, "规划器不可用，直接回答");
        }
    }

    private boolean isAllowed(RequestRoute route, Action action) {
        if (action == Action.FINAL) {
            return true;
        }
        if (action == Action.WEB_SEARCH) {
            return route == RequestRoute.GENERAL_CHAT || route == RequestRoute.EXTERNAL_RESEARCH;
        }
        return route == RequestRoute.GENERAL_CHAT || route == RequestRoute.KNOWLEDGE_QA;
    }

    private String serialize(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception error) {
            throw new IllegalStateException("ReAct 工具观察序列化失败", error);
        }
    }

    private String observation(ReactLoopResult loop, String action) {
        return loop.observations().stream()
                .filter(item -> action.equals(item.toolName()))
                .map(ReactObservation::output)
                .findFirst()
                .orElse("");
    }

    private String clip(String value) {
        if (value == null || value.length() <= MAX_OBSERVATION_CHARS) {
            return value == null ? "" : value;
        }
        return value.substring(0, MAX_OBSERVATION_CHARS) + "…";
    }

    private enum Action {
        FINAL, WEB_SEARCH, KNOWLEDGE_BASE;

        private static Action from(String value) {
            try {
                return Action.valueOf(value == null ? "FINAL" : value.trim().toUpperCase(Locale.ROOT));
            } catch (IllegalArgumentException ignored) {
                return FINAL;
            }
        }
    }

    private record Plan(Action action, String reason) {
    }
}

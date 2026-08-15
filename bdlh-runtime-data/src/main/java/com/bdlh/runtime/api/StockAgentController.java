package com.bdlh.runtime.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.bdlh.runtime.agent.routing.EvidenceBundle;
import com.bdlh.runtime.agent.routing.ModelPolicy;
import com.bdlh.runtime.agent.routing.PaidModelGate;
import com.bdlh.runtime.agent.routing.PaidModelPermit;
import com.bdlh.runtime.agent.routing.RequestRoute;
import com.bdlh.runtime.agent.routing.RouteDecision;
import com.bdlh.runtime.agent.routing.SkillObservation;
import com.bdlh.runtime.dto.AnalysisReport;
import com.bdlh.runtime.dto.AnalyzeRequest;
import com.bdlh.runtime.dto.ChatRequest;
import com.bdlh.runtime.llm.ChatIntent;
import com.bdlh.runtime.llm.PaidAnalysisClient;
import com.bdlh.runtime.tool.ReportAssembler;
import com.bdlh.runtime.tool.StockAnalysisGateway;
import com.bdlh.runtime.tool.StockSkillContractValidator;
import com.bdlh.runtime.service.GuardedOutputService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;
import java.util.concurrent.ExecutorService;

/**
 * 对接 stock-agent.html 前端的接口。
 * /analyze 返回完整报告 JSON；/chat 用 SSE 推 token（流式分析文字）+ report（结构化数据）+ done。
 * 报告数据由 stock-analysis-skill 算（确定性），分析文字由 DeepSeek 生成（解释性）。
 */
@Slf4j
@Deprecated
@RestController
@RequestMapping("/api/stock-agent")
@ConditionalOnProperty(
        name = "bdlh_runtime.legacy-stock-agent.enabled",
        havingValue = "true")
public class StockAgentController {

    private static final long SSE_TIMEOUT = 120_000L;

    private final StockAnalysisGateway stockAnalysisGateway;
    private final ReportAssembler reportAssembler;
    private final PaidAnalysisClient paidAnalysisClient;
    private final StockSkillContractValidator contractValidator;
    private final PaidModelGate paidModelGate;
    private final ObjectMapper mapper;
    private final GuardedOutputService guardedOutputService;
    private final ExecutorService executor;

    public StockAgentController(StockAnalysisGateway stockAnalysisGateway, ReportAssembler reportAssembler,
                                PaidAnalysisClient paidAnalysisClient,
                                StockSkillContractValidator contractValidator,
                                PaidModelGate paidModelGate,
                                ObjectMapper mapper,
                                GuardedOutputService guardedOutputService,
                                @Qualifier("agentFlowExecutor") ExecutorService executor) {
        this.stockAnalysisGateway = stockAnalysisGateway;
        this.reportAssembler = reportAssembler;
        this.paidAnalysisClient = paidAnalysisClient;
        this.contractValidator = contractValidator;
        this.paidModelGate = paidModelGate;
        this.mapper = mapper;
        this.guardedOutputService = guardedOutputService;
        this.executor = executor;
    }

    /**
     * 重新分析：调 skill 取最新数据，组装报告返回。
     */
    @PostMapping(value = "/analyze", produces = MediaType.APPLICATION_JSON_VALUE)
    public AnalysisReport analyze(@RequestBody AnalyzeRequest req) {
        // 1. 调 stock-analysis-skill 取结构化数据
        String json = stockAnalysisGateway.stock(req.symbol(), "auto");
        // 2. 映射成前端报告
        return reportAssembler.assemble(json);
    }

    /**
     * 对话流：取数据→DeepSeek 流式生成分析文字→发 token+report+done。
     */
    @PostMapping(value = "/chat", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter chat(@RequestBody ChatRequest req) {
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT);
        emitter.onTimeout(emitter::complete);
        emitter.onError(t -> emitter.complete());
        executor.execute(() -> {
            try {
                // 1. 调 skill + 组装报告（确定性数据）
                String rawJson = stockAnalysisGateway.stock(req.symbol(), "auto");
                String json = contractValidator.validateAndAnnotate(rawJson, "stock");
                AnalysisReport report = reportAssembler.assemble(json);
                // 2. 旧版股票分析入口也必须通过统一付费门禁，避免绕过主编排器
                boolean subjectMatches = req.symbol() != null && req.symbol().equals(report.symbol());
                boolean freshnessValidated = contractValidator.policy(
                        contractValidator.validate(json, "stock")).directionalSignalAllowed();
                PaidModelPermit permit = paidModelGate.evaluate(
                        directStockDecision(req.symbol()),
                        new SkillObservation(true, true, true, subjectMatches, freshnessValidated),
                        EvidenceBundle.notRequired());
                if (!permit.allowed()) {
                    sendEvent(emitter, "error", Map.of(
                            "message", "数据未通过深度分析门禁：" + permit.reasonCode()));
                    emitter.complete();
                    return;
                }
                // 3. DeepSeek 基于报告数据流式生成分析文字
                guardedOutputService.guard(
                                paidAnalysisClient.streamChat(
                                        permit, systemPrompt(), buildPayload(report, req.message())))
                        .doOnNext(token -> sendEvent(emitter, "token", Map.of("text", token)))
                        .doOnError(e -> {
                            log.error("chat 流异常", e);
                            sendEvent(emitter, "error", Map.of("message", e.getMessage() == null ? "推理失败" : e.getMessage()));
                        })
                        .doOnComplete(() -> {
                            // 4. 文字结束后推结构化报告与结束事件
                            sendEvent(emitter, "report", report);
                            sendEvent(emitter, "done", Map.of());
                            emitter.complete();
                        })
                        .subscribe();
            } catch (Exception e) {
                log.error("chat 失败", e);
                sendEvent(emitter, "error", Map.of("message", "分析失败：" + e.getMessage()));
                emitter.complete();
            }
        });
        return emitter;
    }

    /**
     * 推理系统指令：约束模型基于数据生成、禁止承诺收益。
     */
    private String systemPrompt() {
        return "你是股票分析助手。基于提供的结构化数据（评分/指标/价位）生成中文分析，开头给明确结论，再展开原因。禁止保证收益类措辞，末尾附风险声明。";
    }

    /**
     * 把报告关键数据 + 用户问题组装成 DeepSeek 的输入。
     */
    private String buildPayload(AnalysisReport r, String message) {
        return "用户问题：" + message + "\n\n结构化数据（已由代码计算，请据此解释，勿编造）：\n"
                + "标的：" + r.symbol() + " " + r.name() + "\n"
                + "评分：" + r.decision().techScore() + "/100  信号：" + r.decision().action() + "  追高：" + r.decision().chaseRisk() + "\n"
                + "现价：" + r.levels().current() + "  风险位：" + r.levels().risk() + "  修复位：" + r.levels().repair() + "\n"
                + "趋势：" + fmt(r.indicators().trend()) + "  RSI6：" + fmt(r.indicators().rsi6())
                + "  量比：" + fmt(r.indicators().volumeRatio()) + "  MA20乖离：" + fmt(r.indicators().ma20Bias());
    }

    private String fmt(AnalysisReport.Indicator i) {
        return i == null ? "N/A" : String.valueOf(i.value());
    }

    /**
     * 为旧版显式股票分析接口构造受限决策，使其复用统一付费门禁。
     */
    private RouteDecision directStockDecision(String symbol) {
        return new RouteDecision(
                RequestRoute.STOCK_DECISION,
                ChatIntent.STOCK_ANALYSIS,
                ModelPolicy.PAID_AFTER_VALIDATED_SKILL,
                symbol,
                "LEGACY_EXPLICIT_STOCK_ANALYSIS",
                1.0,
                true,
                false,
                false,
                null);
    }

    /**
     * 发送 SSE 命名事件；data 序列化为 JSON，前端按事件名解析。
     */
    private void sendEvent(SseEmitter emitter, String name, Object data) {
        try {
            emitter.send(SseEmitter.event().name(name).data(mapper.writeValueAsString(data)));
        } catch (Exception e) {
            // 客户端可能已断开，忽略
        }
    }
}

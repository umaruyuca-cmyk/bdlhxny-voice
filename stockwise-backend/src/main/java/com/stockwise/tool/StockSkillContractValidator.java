package com.stockwise.tool;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.stereotype.Component;

/**
 * 校验 stock-analysis-skill 的版本化 JSON 契约，并生成消费端必须执行的金融硬规则。
 * 数据时效与追高限制在代码层计算，避免模型或前端绕过 Skill 的客观纪律。
 */
@Component
public class StockSkillContractValidator {

    private static final String SUPPORTED_SCHEMA_VERSION = "1.1";

    private final ObjectMapper mapper;

    public StockSkillContractValidator(ObjectMapper mapper) {
        this.mapper = mapper;
    }

    /**
     * 校验 JSON、Schema 版本与命令类型，返回可供调用方读取的根节点。
     */
    public JsonNode validate(String json, String expectedCommand) {
        try {
            JsonNode root = mapper.readTree(json);
            if (!root.isObject()) {
                throw new IllegalArgumentException("Skill 输出不是 JSON 对象");
            }
            String version = root.path("schemaVersion").asText();
            if (!SUPPORTED_SCHEMA_VERSION.equals(version)) {
                throw new IllegalArgumentException("不支持的 Skill schemaVersion: " + version);
            }
            String command = root.path("command").asText();
            if (expectedCommand != null && !expectedCommand.equals(command)) {
                throw new IllegalArgumentException(
                        "Skill command 不匹配，期望 " + expectedCommand + "，实际 " + command);
            }
            if (!"Asia/Shanghai".equals(root.path("timezone").asText())) {
                throw new IllegalArgumentException("Skill timezone 必须是 Asia/Shanghai");
            }
            if (root.path("asOf").asText("").isBlank()) {
                throw new IllegalArgumentException("Skill 缺少已核验 asOf");
            }
            if (!root.path("dataQuality").isObject()) {
                throw new IllegalArgumentException("Skill 缺少结构化 dataQuality");
            }
            if (!root.path("data").isObject()) {
                throw new IllegalArgumentException("Skill 缺少结构化 data");
            }
            JsonNode methodology = root.path("methodology");
            if (!methodology.isObject()
                    || !"stockwise-objective-analysis".equals(methodology.path("id").asText())
                    || methodology.path("version").asText("").isBlank()
                    || !methodology.path("rules").isArray()) {
                throw new IllegalArgumentException("Skill 缺少可追溯 methodology");
            }
            if (!root.path("decisionBasis").isObject()) {
                throw new IllegalArgumentException("Skill 缺少结构化 decisionBasis");
            }
            return root;
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalArgumentException("解析 Skill JSON 失败: " + e.getMessage(), e);
        }
    }

    /**
     * 校验工具 Observation，并为单标的结果附加消费端策略字段后返回 JSON。
     */
    public String validateAndAnnotate(String json, String expectedCommand) {
        JsonNode validated = validate(json, expectedCommand);
        if (!"stock".equals(expectedCommand)) {
            return json;
        }
        try {
            ObjectNode root = (ObjectNode) validated;
            StockConsumerPolicy policy = policy(root);
            ObjectNode consumerPolicy = root.putObject("consumerPolicy");
            consumerPolicy.put("observationValidated", true);
            consumerPolicy.put("directionalSignalAllowed", policy.directionalSignalAllowed());
            consumerPolicy.put("buyOrAddAllowed", policy.buyOrAddAllowed());
            consumerPolicy.put("hardChaseBlocked", policy.hardChaseBlocked());
            consumerPolicy.put("marketAsOf", policy.marketAsOf());
            if (policy.forcedAction() != null) {
                consumerPolicy.put("forcedAction", policy.forcedAction());
            }
            ArrayNode reasons = consumerPolicy.putArray("reasons");
            policy.reasons().forEach(reasons::add);
            return mapper.writeValueAsString(root);
        } catch (Exception e) {
            throw new IllegalArgumentException("标注 Skill 消费策略失败: " + e.getMessage(), e);
        }
    }

    /**
     * 从已校验的单标的结果计算方向许可、追高禁买和强制动作。
     */
    public StockConsumerPolicy policy(JsonNode root) {
        JsonNode data = root.path("data");
        JsonNode quality = root.path("dataQuality");
        boolean directionalSignalAllowed = quality.path("allowsDirectionalSignal").asBoolean(false);
        boolean hardChase = "hard".equalsIgnoreCase(data.path("chase").path("level").asText());
        String asOf = root.path("asOf").asText(quality.path("asOf").asText(""));

        java.util.List<String> reasons = new java.util.ArrayList<>();
        if (!directionalSignalAllowed) {
            String label = quality.path("label").asText("数据质量未通过");
            reasons.add("数据时效不允许方向性信号：" + label);
        }
        if (hardChase) {
            reasons.add("追高硬警告生效，禁止买入或加仓");
        }
        return new StockConsumerPolicy(
                directionalSignalAllowed,
                directionalSignalAllowed && !hardChase,
                hardChase,
                directionalSignalAllowed ? null : "wait",
                asOf,
                java.util.List.copyOf(reasons)
        );
    }

    /**
     * 单标的 JSON 的消费端硬规则结果。
     */
    public record StockConsumerPolicy(
            boolean directionalSignalAllowed,
            boolean buyOrAddAllowed,
            boolean hardChaseBlocked,
            String forcedAction,
            String marketAsOf,
            java.util.List<String> reasons
    ) {
    }
}

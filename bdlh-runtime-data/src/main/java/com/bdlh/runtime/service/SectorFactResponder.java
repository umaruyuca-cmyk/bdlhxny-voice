package com.bdlh.runtime.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.bdlh.runtime.agent.routing.RouteDecision;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * 使用已校验 sector JSON 生成可复算板块事实回答，避免事实查询触发生成式模型。
 */
@Component
public class SectorFactResponder {

    private static final int DEFAULT_LIMIT = 10;

    /**
     * 返回板块热度、组成贡献、数据质量和方法论版本。
     */
    public String respond(RouteDecision decision, JsonNode root) {
        JsonNode sectors = root.path("data").path("sectors");
        if (!sectors.isArray() || sectors.isEmpty()) {
            return "板块 Skill 没有返回可用排名数据。";
        }
        List<JsonNode> selected = select(decision, sectors);
        if (selected.isEmpty()) {
            return "已取得板块榜单，但用户指定的板块没有出现在当前返回范围内，请确认板块名称或类型。";
        }
        StringBuilder answer = new StringBuilder();
        answer.append("板块行情热度（仅为相对排序，不代表后续上涨概率）\n");
        answer.append("数据截至：").append(root.path("asOf").asText("未核验"));
        answer.append("；方法论版本：")
                .append(root.path("methodology").path("version").asText("unknown"))
                .append("\n");
        int rank = 1;
        for (JsonNode sector : selected) {
            answer.append(rank++).append(". ")
                    .append(sector.path("name").asText("未知板块"))
                    .append("：热度 ").append(number(sector.path("heatScore")))
                    .append("，日涨跌 ").append(number(sector.path("changePct"))).append("%")
                    .append("，5日 ").append(number(sector.path("change5d"))).append("%")
                    .append("，20日 ").append(number(sector.path("change20d"))).append("%")
                    .append("，主力净流入 ").append(number(sector.path("mainNetInflow"))).append("亿元")
                    .append("，换手率 ").append(number(sector.path("turnoverRate"))).append("%")
                    .append("；质量 ").append(sector.path("heatScoreQuality").asText("unknown"))
                    .append("\n   贡献：").append(contributions(sector.path("heatScoreBreakdown")))
                    .append('\n');
        }
        JsonNode warnings = root.path("dataQuality").path("warnings");
        if (warnings.isArray() && !warnings.isEmpty()) {
            answer.append("数据限制：");
            List<String> values = new ArrayList<>();
            warnings.forEach(item -> values.add(item.asText()));
            answer.append(String.join("；", values)).append('\n');
        }
        answer.append("说明：行情热度不包含互联网讨论度；外围关注必须使用独立搜索证据代理。")
                .append("本结果为 AI 系统辅助计算，不构成投资建议。");
        return answer.toString();
    }

    private List<JsonNode> select(RouteDecision decision, JsonNode sectors) {
        List<JsonNode> values = new ArrayList<>();
        sectors.forEach(values::add);
        if (decision.sectors().isEmpty()) {
            return values.stream().limit(DEFAULT_LIMIT).toList();
        }
        return values.stream()
                .filter(item -> decision.sectors().stream()
                        .anyMatch(name -> name.equals(item.path("name").asText())))
                .toList();
    }

    private String contributions(JsonNode breakdown) {
        JsonNode components = breakdown.path("components");
        return "日涨跌 " + contribution(components.path("daily"))
                + "，5日 " + contribution(components.path("fiveDay"))
                + "，20日 " + contribution(components.path("twentyDay"))
                + "，资金 " + contribution(components.path("fundFlow"))
                + "，换手 " + contribution(components.path("turnover"));
    }

    private String contribution(JsonNode component) {
        if (component.isMissingNode() || component.isNull()) {
            return "缺失";
        }
        return number(component.path("contribution")) + "分";
    }

    private String number(JsonNode value) {
        if (value == null || value.isNull() || value.isMissingNode() || !value.isNumber()) {
            return "N/A";
        }
        return String.format(Locale.ROOT, "%.2f", value.asDouble());
    }
}

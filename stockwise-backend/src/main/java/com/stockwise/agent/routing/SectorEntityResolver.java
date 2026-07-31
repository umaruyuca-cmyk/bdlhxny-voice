package com.stockwise.agent.routing;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 使用受控别名和原文匹配规范化板块实体，避免模型凭空补充行业或概念名称。
 */
@Component
public class SectorEntityResolver {

    private static final Pattern QUALIFIED_SECTOR = Pattern.compile(
            "([\\p{IsHan}A-Za-z0-9]{2,12}?)(板块|行业|概念)");
    private static final Map<String, ResolvedSector> ALIASES = aliases();

    /**
     * 从原始问题和模型候选中提取可验证的板块实体。
     */
    public List<ResolvedSector> resolve(String question, List<String> mentions, SectorType suggestedType) {
        String normalizedQuestion = question == null ? "" : question.trim();
        LinkedHashMap<String, ResolvedSector> resolved = new LinkedHashMap<>();

        // 1. 只接受能在原文中找到或命中受控别名的模型候选。
        if (mentions != null) {
            for (String mention : mentions) {
                ResolvedSector value = resolveMention(normalizedQuestion, mention, suggestedType);
                if (value != null) {
                    resolved.putIfAbsent(value.name(), value);
                }
            }
        }

        // 2. 从“XX板块/行业/概念”句式中提取原文实体。
        Matcher matcher = QUALIFIED_SECTOR.matcher(normalizedQuestion);
        while (matcher.find()) {
            String rawName = trimScaffold(matcher.group(1));
            SectorType type = switch (matcher.group(2)) {
                case "行业" -> SectorType.INDUSTRY;
                case "概念" -> SectorType.CONCEPT;
                default -> suggestedType;
            };
            ResolvedSector value = resolveMention(normalizedQuestion, rawName, type);
            if (value != null) {
                resolved.putIfAbsent(value.name(), value);
            }
        }

        // 3. 扫描受控别名，覆盖“新能源车是不是到顶”这类省略板块后缀的表达。
        for (Map.Entry<String, ResolvedSector> entry : ALIASES.entrySet()) {
            if (normalizedQuestion.toLowerCase(Locale.ROOT).contains(entry.getKey())) {
                ResolvedSector value = entry.getValue();
                resolved.putIfAbsent(value.name(), value);
            }
        }
        return List.copyOf(resolved.values());
    }

    private ResolvedSector resolveMention(String question, String mention, SectorType suggestedType) {
        if (mention == null || mention.isBlank()) {
            return null;
        }
        String normalized = mention.trim();
        ResolvedSector alias = ALIASES.get(normalized.toLowerCase(Locale.ROOT));
        if (alias != null) {
            return alias;
        }
        if (!question.contains(normalized)) {
            return null;
        }
        SectorType type = suggestedType == null ? SectorType.UNKNOWN : suggestedType;
        return type == SectorType.UNKNOWN ? null : new ResolvedSector(normalized, type);
    }

    private String trimScaffold(String rawName) {
        String normalized = rawName == null ? "" : rawName;
        String[] prefixes = {
                "最近的", "现在的", "当前的", "今天", "目前", "哪些", "什么",
                "看看", "分析", "比较"
        };
        for (String prefix : prefixes) {
            if (normalized.startsWith(prefix)) {
                normalized = normalized.substring(prefix.length());
            }
        }
        return normalized;
    }

    private static Map<String, ResolvedSector> aliases() {
        List<ResolvedSector> industries = List.of(
                industry("银行"), industry("证券"), industry("保险"), industry("房地产"),
                industry("汽车"), industry("食品饮料"), industry("医药"), industry("电力"),
                industry("煤炭"), industry("有色金属"), industry("计算机"), industry("电子"),
                industry("通信"), industry("传媒"), industry("国防军工"), industry("家电"));
        List<ResolvedSector> concepts = List.of(
                concept("科技"), concept("新能源车"), concept("新能源汽车"),
                concept("人工智能"), concept("AI"), concept("半导体"), concept("芯片"),
                concept("机器人"), concept("CPO"), concept("算力"), concept("低空经济"),
                concept("固态电池"), concept("消费"), concept("消费电子"), concept("数据中心"));
        LinkedHashMap<String, ResolvedSector> result = new LinkedHashMap<>();
        List<ResolvedSector> all = new ArrayList<>();
        all.addAll(industries);
        all.addAll(concepts);
        for (ResolvedSector value : all) {
            result.put(value.name().toLowerCase(Locale.ROOT), value);
        }
        result.put("银行股", industry("银行"));
        result.put("券商", industry("证券"));
        result.put("新能源", concept("新能源车"));
        result.put("ai", concept("人工智能"));
        return Map.copyOf(result);
    }

    private static ResolvedSector industry(String name) {
        return new ResolvedSector(name, SectorType.INDUSTRY);
    }

    private static ResolvedSector concept(String name) {
        return new ResolvedSector(name, SectorType.CONCEPT);
    }

    /**
     * 保存规范化板块名称及 stock-wrapper 支持的类型。
     */
    public record ResolvedSector(String name, SectorType type) {
    }
}

package com.stockwise.agent.routing;

import org.springframework.stereotype.Component;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 从用户问题和前端上下文提取可信代码实体，避免模型生成或猜测证券代码。
 */
@Component
public class DeterministicEntityExtractor {

    private static final Pattern SYMBOL_PATTERN = Pattern.compile("(?<!\\d)(\\d{6})(?!\\d)");

    /**
     * 构建只包含已校验代码和能力标志的最小路由上下文。
     */
    public RoutingContext extract(String question, String contextSymbol, boolean portfolioAvailable) {
        String normalizedQuestion = question == null
                ? ""
                : question.replace('\u0000', ' ').trim();
        LinkedHashSet<String> symbols = new LinkedHashSet<>();
        Matcher matcher = SYMBOL_PATTERN.matcher(normalizedQuestion);
        while (matcher.find()) {
            symbols.add(matcher.group(1));
        }
        return new RoutingContext(
                normalizedQuestion,
                List.copyOf(symbols),
                validSymbol(contextSymbol),
                portfolioAvailable);
    }

    private String validSymbol(String symbol) {
        if (symbol == null) {
            return null;
        }
        String normalized = symbol.trim();
        return SYMBOL_PATTERN.matcher(normalized).matches() ? normalized : null;
    }
}

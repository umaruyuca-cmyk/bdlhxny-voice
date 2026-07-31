package com.stockwise.dto;

import java.util.Locale;
import java.util.Set;

/**
 * 表示前端显式选择的当前分析标的，使标的上下文不再混入用户原始问题。
 *
 * @param symbol    6位股票、ETF或基金代码
 * @param assetType 标准化资产类型
 */
public record ChatInstrument(String symbol, String assetType) {

    private static final Set<String> ALLOWED_ASSET_TYPES = Set.of(
            "auto", "stock", "etf", "fund", "open_fund", "qdii");

    /**
     * 校验并标准化可选标的；没有选择时返回null。
     */
    public static ChatInstrument normalize(ChatInstrument instrument) {
        if (instrument == null) {
            return null;
        }
        String normalizedSymbol = instrument.symbol() == null ? "" : instrument.symbol().trim();
        if (!normalizedSymbol.matches("\\d{6}")) {
            throw new IllegalArgumentException("instrument.symbol 必须是6位数字代码");
        }
        String normalizedType = instrument.assetType() == null
                ? "auto"
                : instrument.assetType().trim().toLowerCase(Locale.ROOT);
        if (!ALLOWED_ASSET_TYPES.contains(normalizedType)) {
            throw new IllegalArgumentException("instrument.assetType 不在允许范围内");
        }
        return new ChatInstrument(normalizedSymbol, normalizedType);
    }
}

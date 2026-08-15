package com.bdlh.runtime.agent.routing;

/**
 * 约束板块查询只能使用 stock-wrapper 支持的行业或概念类型。
 */
public enum SectorType {
    INDUSTRY("industry"),
    CONCEPT("concept"),
    UNKNOWN("");

    private final String commandValue;

    SectorType(String commandValue) {
        this.commandValue = commandValue;
    }

    /**
     * 返回传递给 sector command 的受限类型值。
     */
    public String commandValue() {
        return commandValue;
    }

    /**
     * 把模型或配置中的文本映射为受限板块类型。
     */
    public static SectorType from(String value) {
        if (value == null || value.isBlank()) {
            return UNKNOWN;
        }
        return switch (value.trim().toLowerCase()) {
            case "industry", "行业" -> INDUSTRY;
            case "concept", "概念" -> CONCEPT;
            default -> UNKNOWN;
        };
    }
}

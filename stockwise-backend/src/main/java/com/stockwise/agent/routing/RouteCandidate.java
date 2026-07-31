package com.stockwise.agent.routing;

import java.util.List;

/**
 * 保存规则或语义分类器生成的受限候选结果，必须经过 Java 校验后才能执行。
 */
public record RouteCandidate(
        RequestRoute route,
        RouteSubjectType subjectType,
        List<String> sectorMentions,
        SectorType sectorType,
        boolean useContextSymbol,
        double reportedConfidence,
        String ambiguityReason,
        RouteSource source
) {

    public RouteCandidate {
        sectorMentions = sectorMentions == null ? List.of() : List.copyOf(sectorMentions);
        sectorType = sectorType == null ? SectorType.UNKNOWN : sectorType;
        subjectType = subjectType == null ? RouteSubjectType.NONE : subjectType;
        source = source == null ? RouteSource.CLARIFICATION : source;
    }
}

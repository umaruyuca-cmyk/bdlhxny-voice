package com.stockwise.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.time.OffsetDateTime;

/**
 * Java Data API 的统一只读元数据，供 Python Adapter 判断授权范围和数据时效。
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record DataAccessMetadata(
        Long userId,
        String authorizationScope,
        String queryStatus,
        OffsetDateTime dataTime,
        OffsetDateTime queriedAt) {

    public static DataAccessMetadata of(Long userId, String queryStatus,
                                        OffsetDateTime dataTime, OffsetDateTime queriedAt) {
        return new DataAccessMetadata(userId, "SELF", queryStatus, dataTime, queriedAt);
    }
}

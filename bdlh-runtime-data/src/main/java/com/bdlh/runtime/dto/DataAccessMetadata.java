package com.bdlh.runtime.dto;

import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Objects;

/**
 * Java Data API 的统一只读元数据，供 Python Adapter 判断授权范围和数据时效。
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record DataAccessMetadata(
        String schemaVersion,
        Long userId,
        String authorizationScope,
        String dataMode,
        String sourceType,
        String queryStatus,
        OffsetDateTime dataTime,
        OffsetDateTime queriedAt,
        String confirmationRef,
        List<String> missingFields) {

    public static final String SCHEMA_VERSION = "financial-user-data.v2";

    public DataAccessMetadata {
        missingFields = missingFields == null
                ? List.of()
                : missingFields.stream()
                        .filter(Objects::nonNull)
                        .map(String::trim)
                        .filter(value -> !value.isEmpty())
                        .distinct()
                        .sorted()
                        .toList();
    }

    /** 非 M3 用户快照接口的兼容元数据；查询成功也不得伪装成 LIVE。 */
    public static DataAccessMetadata of(Long userId, String queryStatus,
                                         OffsetDateTime dataTime, OffsetDateTime queriedAt) {
        return new DataAccessMetadata(
                SCHEMA_VERSION,
                userId,
                "SELF",
                "UNAVAILABLE",
                null,
                queryStatus,
                dataTime,
                queriedAt,
                null,
                List.of("metadata.data_mode", "metadata.source_type"));
    }

    public static DataAccessMetadata userData(
            Long userId,
            String dataMode,
            String sourceType,
            String queryStatus,
            OffsetDateTime dataTime,
            OffsetDateTime queriedAt,
            String confirmationRef,
            List<String> missingFields) {
        return new DataAccessMetadata(
                SCHEMA_VERSION,
                userId,
                "SELF",
                dataMode,
                sourceType,
                queryStatus,
                dataTime,
                queriedAt,
                confirmationRef,
                missingFields);
    }
}

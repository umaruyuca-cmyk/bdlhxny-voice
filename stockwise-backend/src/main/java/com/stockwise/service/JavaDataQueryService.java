package com.stockwise.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.stockwise.dto.AccountSnapshotResponse;
import com.stockwise.dto.DataAccessMetadata;
import com.stockwise.dto.PortfolioPositionsResponse;
import com.stockwise.dto.RiskProfileResponse;
import com.stockwise.dto.TransactionHistoryResponse;
import com.stockwise.entity.PortfolioPosition;
import com.stockwise.entity.PortfolioTransaction;
import com.stockwise.entity.UserConfig;
import com.stockwise.mapper.PortfolioPositionMapper;
import com.stockwise.mapper.PortfolioTransactionMapper;
import com.stockwise.mapper.UserConfigMapper;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Objects;
import java.util.Set;

/**
 * Python 分析服务所需的 Java 用户数据查询门面。
 *
 * <p>本服务只执行 SELECT 并返回脱敏 DTO，不暴露 Mapper、数据库主键之外的内部字段，
 * 也不提供任何下单、调仓或账户修改方法。</p>
 */
@Service
public class JavaDataQueryService {

    private static final int DEFAULT_TRANSACTION_LIMIT = 100;
    private static final int MAX_TRANSACTION_LIMIT = 500;

    private final PortfolioPositionMapper positionMapper;
    private final PortfolioTransactionMapper transactionMapper;
    private final UserConfigMapper configMapper;

    public JavaDataQueryService(
            PortfolioPositionMapper positionMapper,
            PortfolioTransactionMapper transactionMapper,
            UserConfigMapper configMapper) {
        this.positionMapper = positionMapper;
        this.transactionMapper = transactionMapper;
        this.configMapper = configMapper;
    }

    public PortfolioPositionsResponse positions(long userId) {
        OffsetDateTime queriedAt = now();
        List<PortfolioPosition> entities = positionMapper.selectList(
                new LambdaQueryWrapper<PortfolioPosition>()
                        .eq(PortfolioPosition::getUserId, userId)
                        .eq(PortfolioPosition::getActive, true)
                        .orderByAsc(PortfolioPosition::getCode));
        List<PortfolioPositionsResponse.Position> positions = entities.stream()
                .map(this::toPosition)
                .toList();
        OffsetDateTime dataTime = entities.stream()
                .map(position -> position.getConfirmedAt() != null
                        ? position.getConfirmedAt()
                        : position.getUpdatedAt())
                .filter(value -> value != null)
                .max(OffsetDateTime::compareTo)
                .orElse(null);
        List<String> missingFields = positionMissingFields(entities);
        String queryStatus = entities.isEmpty()
                ? "NOT_CONFIGURED"
                : missingFields.isEmpty() ? "SUCCESS" : "PARTIAL";
        String dataMode = positionsDataMode(entities, missingFields);
        String sourceType = aggregateSourceType(
                entities.stream().map(PortfolioPosition::getDataSource).toList());
        String confirmationRef = aggregateConfirmationRef(
                entities.stream().map(PortfolioPosition::getSourceRef).toList());
        return new PortfolioPositionsResponse(
                DataAccessMetadata.userData(
                        userId,
                        dataMode,
                        sourceType,
                        queryStatus,
                        dataTime,
                        queriedAt,
                        confirmationRef,
                        missingFields),
                positions);
    }

    public AccountSnapshotResponse account(long userId) {
        OffsetDateTime queriedAt = now();
        UserConfig config = configMapper.selectById(userId);
        if (config == null) {
            return new AccountSnapshotResponse(
                    DataAccessMetadata.userData(
                            userId, "UNAVAILABLE", null, "NOT_CONFIGURED",
                            null, queriedAt, null,
                            List.of("account.cash", "account.currency", "liquidity.liquid_assets",
                                    "liquidity.near_term_cash_needs",
                                    "liquidity.near_term_cash_needs_horizon_days")),
                    null, null, null, null, null, null, null, 0L);
        }
        List<String> missingFields = accountMissingFields(config);
        return new AccountSnapshotResponse(
                profileMetadata(userId, config, queriedAt, missingFields),
                normalizeUpper(config.getCurrency()),
                config.getCash(),
                config.getMonthlyBudget() == null ? null : BigDecimal.valueOf(config.getMonthlyBudget()),
                config.getCashReserveRatio(),
                config.getLiquidAssets(),
                config.getNearTermCashNeeds(),
                config.getNearTermCashNeedsHorizonDays(),
                profileVersion(config));
    }

    public TransactionHistoryResponse transactions(long userId, Integer requestedLimit) {
        int limit = requestedLimit == null
                ? DEFAULT_TRANSACTION_LIMIT
                : Math.max(1, Math.min(requestedLimit, MAX_TRANSACTION_LIMIT));
        OffsetDateTime queriedAt = now();
        List<PortfolioTransaction> entities = transactionMapper.selectList(
                new LambdaQueryWrapper<PortfolioTransaction>()
                        .eq(PortfolioTransaction::getUserId, userId)
                        .orderByDesc(PortfolioTransaction::getTradeDate)
                        .orderByDesc(PortfolioTransaction::getId)
                        .last("LIMIT " + limit));
        List<TransactionHistoryResponse.Transaction> transactions = entities.stream()
                .map(this::toTransaction)
                .toList();
        OffsetDateTime dataTime = entities.stream()
                .map(PortfolioTransaction::getCreatedAt)
                .filter(value -> value != null)
                .max(OffsetDateTime::compareTo)
                .orElse(null);
        return new TransactionHistoryResponse(
                DataAccessMetadata.of(userId, "SUCCESS", dataTime, queriedAt),
                transactions);
    }

    public RiskProfileResponse riskProfile(long userId) {
        OffsetDateTime queriedAt = now();
        UserConfig config = configMapper.selectById(userId);
        if (config == null) {
            return new RiskProfileResponse(
                    DataAccessMetadata.userData(
                            userId, "UNAVAILABLE", null, "NOT_CONFIGURED",
                            null, queriedAt, null,
                            List.of("risk_profile.max_loss_tolerance_pct", "risk_profile.risk_level")),
                    null, null, null, List.of(), List.of(), 0L);
        }
        List<String> missingFields = riskMissingFields(config);
        return new RiskProfileResponse(
                profileMetadata(userId, config, queriedAt, missingFields),
                normalize(config.getRiskTolerance()),
                config.getMaxLossTolerancePct(),
                config.getCashReserveRatio(),
                splitCsv(config.getPreferredSectors()),
                splitCsv(config.getForbiddenSymbols()),
                profileVersion(config));
    }

    private PortfolioPositionsResponse.Position toPosition(PortfolioPosition position) {
        return new PortfolioPositionsResponse.Position(
                position.getCode(),
                position.getName(),
                position.getAssetType(),
                position.getShares(),
                position.getAvgCost(),
                position.getBuyDate(),
                position.getTargetWeight(),
                position.getSector(),
                position.getRiskRole(),
                normalizeUpper(position.getExchange()),
                normalizeUpper(position.getCurrency()),
                position.getDataSource(),
                position.getConfirmedAt(),
                position.getSourceRef());
    }

    private TransactionHistoryResponse.Transaction toTransaction(PortfolioTransaction transaction) {
        return new TransactionHistoryResponse.Transaction(
                transaction.getId(),
                transaction.getSymbol(),
                transaction.getName(),
                transaction.getTransactionType(),
                transaction.getQuantity(),
                transaction.getPrice(),
                transaction.getAmount(),
                transaction.getCurrency(),
                transaction.getTradeDate(),
                transaction.getNote());
    }

    private List<String> splitCsv(String value) {
        if (value == null || value.isBlank()) {
            return List.of();
        }
        return Arrays.stream(value.split(","))
                .map(String::trim)
                .filter(item -> !item.isEmpty())
                .distinct()
                .toList();
    }

    private String normalize(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim().toLowerCase();
    }

    private String normalizeUpper(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim().toUpperCase(Locale.ROOT);
    }

    private DataAccessMetadata profileMetadata(
            long userId,
            UserConfig config,
            OffsetDateTime queriedAt,
            List<String> missingFields) {
        String dataMode = profileDataMode(config);
        String queryStatus = missingFields.isEmpty() && !"UNAVAILABLE".equals(dataMode)
                ? "SUCCESS"
                : "PARTIAL";
        return DataAccessMetadata.userData(
                userId,
                dataMode,
                config.getFinancialDataSource(),
                queryStatus,
                config.getConfirmedAt() != null ? config.getConfirmedAt() : config.getUpdatedAt(),
                queriedAt,
                config.getConfirmationRef(),
                missingFields);
    }

    private String profileDataMode(UserConfig config) {
        if (config.getFinancialDataSource() == null
                || config.getConfirmedAt() == null
                || config.getConfirmationRef() == null
                || config.getConfirmationRef().isBlank()) {
            return "UNAVAILABLE";
        }
        return switch (config.getFinancialDataSource()) {
            case "USER_INPUT" -> "USER_CONFIRMED";
            case "BROKER_SYNC", "ACCOUNT_PROVIDER" -> "LIVE";
            case "TEST_FIXTURE" -> "TEST_FIXTURE";
            default -> "UNAVAILABLE";
        };
    }

    private String positionsDataMode(
            List<PortfolioPosition> positions,
            List<String> missingFields) {
        if (positions.isEmpty() || !missingFields.isEmpty()) {
            return "UNAVAILABLE";
        }
        Set<String> sources = positions.stream()
                .map(PortfolioPosition::getDataSource)
                .filter(Objects::nonNull)
                .collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));
        if (sources.contains("TEST_FIXTURE")) {
            return "TEST_FIXTURE";
        }
        if (sources.contains("USER_INPUT")) {
            return "USER_CONFIRMED";
        }
        if (!sources.isEmpty() && sources.stream().allMatch(
                value -> value.equals("BROKER_SYNC") || value.equals("ACCOUNT_PROVIDER"))) {
            return "LIVE";
        }
        return "UNAVAILABLE";
    }

    private String aggregateSourceType(List<String> values) {
        List<String> distinct = values.stream()
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .distinct()
                .toList();
        if (distinct.size() == 1) {
            return distinct.get(0);
        }
        return distinct.isEmpty() ? null : "MIXED";
    }

    private String aggregateConfirmationRef(List<String> values) {
        List<String> distinct = values.stream()
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(value -> !value.isEmpty())
                .distinct()
                .toList();
        return distinct.size() == 1 ? distinct.get(0) : null;
    }

    private List<String> positionMissingFields(List<PortfolioPosition> positions) {
        List<String> missing = new ArrayList<>();
        for (PortfolioPosition position : positions) {
            String key = position.getCode() == null || position.getCode().isBlank()
                    ? "unknown"
                    : position.getCode().trim();
            addMissing(missing, position.getCode(), "positions[" + key + "].symbol");
            addMissing(missing, position.getShares(), "positions[" + key + "].quantity");
            addMissing(missing, position.getExchange(), "positions[" + key + "].exchange");
            addMissing(missing, position.getCurrency(), "positions[" + key + "].currency");
            addMissing(missing, position.getDataSource(), "positions[" + key + "].data_source");
            addMissing(missing, position.getConfirmedAt(), "positions[" + key + "].confirmed_at");
            addMissing(missing, position.getSourceRef(), "positions[" + key + "].source_ref");
        }
        return missing.stream().distinct().sorted().toList();
    }

    private List<String> accountMissingFields(UserConfig config) {
        List<String> missing = new ArrayList<>();
        addMissing(missing, config.getCurrency(), "account.currency");
        addMissing(missing, config.getCash(), "account.cash");
        addMissing(missing, config.getLiquidAssets(), "liquidity.liquid_assets");
        addMissing(missing, config.getNearTermCashNeeds(), "liquidity.near_term_cash_needs");
        addMissing(missing, config.getNearTermCashNeedsHorizonDays(),
                "liquidity.near_term_cash_needs_horizon_days");
        addProfileProvenanceMissing(missing, config);
        return missing.stream().distinct().sorted().toList();
    }

    private List<String> riskMissingFields(UserConfig config) {
        List<String> missing = new ArrayList<>();
        addMissing(missing, config.getRiskTolerance(), "risk_profile.risk_level");
        addMissing(missing, config.getMaxLossTolerancePct(),
                "risk_profile.max_loss_tolerance_pct");
        addProfileProvenanceMissing(missing, config);
        return missing.stream().distinct().sorted().toList();
    }

    private void addProfileProvenanceMissing(List<String> missing, UserConfig config) {
        addMissing(missing, config.getFinancialDataSource(), "metadata.source_type");
        addMissing(missing, config.getConfirmedAt(), "metadata.confirmed_at");
        addMissing(missing, config.getConfirmationRef(), "metadata.confirmation_ref");
    }

    private void addMissing(List<String> missing, Object value, String field) {
        if (value == null || value instanceof String text && text.isBlank()) {
            missing.add(field);
        }
    }

    private long profileVersion(UserConfig config) {
        return config.getProfileVersion() == null ? 0L : config.getProfileVersion();
    }

    private OffsetDateTime now() {
        return OffsetDateTime.now(ZoneOffset.UTC);
    }
}

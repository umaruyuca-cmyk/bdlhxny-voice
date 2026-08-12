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
import java.util.List;

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
                .map(PortfolioPosition::getUpdatedAt)
                .filter(value -> value != null)
                .max(OffsetDateTime::compareTo)
                .orElse(null);
        return new PortfolioPositionsResponse(
                DataAccessMetadata.of(userId, "SUCCESS", dataTime, queriedAt),
                positions);
    }

    public AccountSnapshotResponse account(long userId) {
        OffsetDateTime queriedAt = now();
        UserConfig config = configMapper.selectById(userId);
        if (config == null) {
            return new AccountSnapshotResponse(
                    DataAccessMetadata.of(userId, "NOT_CONFIGURED", null, queriedAt),
                    "CNY", null, null, null);
        }
        return new AccountSnapshotResponse(
                DataAccessMetadata.of(userId, "SUCCESS", config.getUpdatedAt(), queriedAt),
                "CNY",
                config.getCash(),
                config.getMonthlyBudget() == null ? null : BigDecimal.valueOf(config.getMonthlyBudget()),
                config.getCashReserveRatio());
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
                    DataAccessMetadata.of(userId, "NOT_CONFIGURED", null, queriedAt),
                    null, null, List.of(), List.of());
        }
        String status = config.getRiskTolerance() == null || config.getRiskTolerance().isBlank()
                ? "NOT_CONFIGURED"
                : "SUCCESS";
        return new RiskProfileResponse(
                DataAccessMetadata.of(userId, status, config.getUpdatedAt(), queriedAt),
                normalize(config.getRiskTolerance()),
                config.getCashReserveRatio(),
                splitCsv(config.getPreferredSectors()),
                splitCsv(config.getForbiddenSymbols()));
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
                position.getRiskRole());
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

    private OffsetDateTime now() {
        return OffsetDateTime.now(ZoneOffset.UTC);
    }
}

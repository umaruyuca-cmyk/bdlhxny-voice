package com.bdlh.runtime.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.bdlh.runtime.dto.FinancialProfileConfirmationResponse;
import com.bdlh.runtime.dto.FinancialProfileUpdateRequest;
import com.bdlh.runtime.dto.PortfolioPositionsUpdateRequest;
import com.bdlh.runtime.entity.FinancialProfileConfirmation;
import com.bdlh.runtime.entity.PortfolioPosition;
import com.bdlh.runtime.entity.UserConfig;
import com.bdlh.runtime.mapper.FinancialProfileConfirmationMapper;
import com.bdlh.runtime.mapper.PortfolioPositionMapper;
import com.bdlh.runtime.mapper.UserConfigMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.function.Consumer;

/**
 * 用户本人维护金融事实的命令服务。
 *
 * <p>该服务不属于 Agent Capability。身份由 Controller 的 JWT 上下文绑定，客户端不能提交
 * user_id、data_mode、data_source、confirmation_ref 或 confirmed_at。</p>
 */
@Service
public class FinancialProfileCommandService {

    private static final String USER_INPUT = "USER_INPUT";
    private static final String USER_CONFIRMED = "USER_CONFIRMED";
    private static final String PROFILE_ACTION = "FINANCIAL_PROFILE_REPLACE";
    private static final String POSITIONS_ACTION = "PORTFOLIO_POSITIONS_REPLACE";
    private static final Set<String> ASSET_TYPES = Set.of("stock", "etf", "open_fund", "qdii");
    private static final Set<String> RISK_LEVELS = Set.of(
            "conservative", "moderate", "balanced", "aggressive");

    private final UserConfigMapper configMapper;
    private final PortfolioPositionMapper positionMapper;
    private final FinancialProfileConfirmationMapper confirmationMapper;

    public FinancialProfileCommandService(
            UserConfigMapper configMapper,
            PortfolioPositionMapper positionMapper,
            FinancialProfileConfirmationMapper confirmationMapper) {
        this.configMapper = configMapper;
        this.positionMapper = positionMapper;
        this.confirmationMapper = confirmationMapper;
    }

    @Transactional
    public FinancialProfileConfirmationResponse replaceFinancialProfile(
            long userId,
            String idempotencyKey,
            FinancialProfileUpdateRequest request) {
        requireUser(userId);
        String key = normalizeIdempotencyKey(idempotencyKey);
        ValidatedProfile profile = validateProfile(request);
        String fingerprint = fingerprint(profile.canonical());
        FinancialProfileConfirmation existing = findReplay(userId, key, PROFILE_ACTION, fingerprint);
        if (existing != null) {
            return response(existing);
        }

        OffsetDateTime confirmedAt = now();
        String confirmationRef = UUID.randomUUID().toString();
        long nextVersion = advanceProfileVersion(
                userId,
                profile.expectedVersion(),
                config -> {
                    config.setCurrency(profile.currency());
                    config.setCash(profile.cash());
                    config.setRiskTolerance(profile.riskTolerance());
                    config.setMaxLossTolerancePct(profile.maxLossTolerancePct());
                    config.setLiquidAssets(profile.liquidAssets());
                    config.setNearTermCashNeeds(profile.nearTermCashNeeds());
                    config.setNearTermCashNeedsHorizonDays(profile.nearTermCashNeedsHorizonDays());
                    config.setFinancialDataSource(USER_INPUT);
                    config.setConfirmedAt(confirmedAt);
                    config.setConfirmationRef(confirmationRef);
                },
                confirmedAt);

        FinancialProfileConfirmation confirmation = confirmation(
                confirmationRef,
                userId,
                nextVersion,
                PROFILE_ACTION,
                key,
                fingerprint,
                "account.cash,account.currency,liquidity.liquid_assets,"
                        + "liquidity.near_term_cash_needs,liquidity.near_term_cash_needs_horizon_days,"
                        + "risk_profile.max_loss_tolerance_pct,risk_profile.risk_level",
                confirmedAt);
        confirmationMapper.insert(confirmation);
        return response(confirmation);
    }

    @Transactional
    public FinancialProfileConfirmationResponse replacePositions(
            long userId,
            String idempotencyKey,
            PortfolioPositionsUpdateRequest request) {
        requireUser(userId);
        String key = normalizeIdempotencyKey(idempotencyKey);
        ValidatedPositions validated = validatePositions(request);
        String fingerprint = fingerprint(validated.canonical());
        FinancialProfileConfirmation existing = findReplay(userId, key, POSITIONS_ACTION, fingerprint);
        if (existing != null) {
            return response(existing);
        }

        OffsetDateTime confirmedAt = now();
        String confirmationRef = UUID.randomUUID().toString();
        long nextVersion = advanceProfileVersion(
                userId,
                validated.expectedVersion(),
                ignored -> { },
                confirmedAt);

        List<PortfolioPosition> existingPositions = positionMapper.selectList(
                new LambdaQueryWrapper<PortfolioPosition>()
                        .eq(PortfolioPosition::getUserId, userId));
        Map<String, PortfolioPosition> bySymbol = new HashMap<>();
        for (PortfolioPosition position : existingPositions) {
            bySymbol.put(position.getCode(), position);
        }

        Set<String> requestedSymbols = new HashSet<>();
        for (ValidatedPosition item : validated.positions()) {
            requestedSymbols.add(item.symbol());
            PortfolioPosition entity = bySymbol.get(item.symbol());
            boolean insert = entity == null;
            if (insert) {
                entity = new PortfolioPosition();
                entity.setUserId(userId);
                entity.setCode(item.symbol());
            }
            applyPosition(entity, item, confirmationRef, confirmedAt);
            if (insert) {
                positionMapper.insert(entity);
            } else {
                positionMapper.updateById(entity);
            }
        }

        for (PortfolioPosition position : existingPositions) {
            if (Boolean.TRUE.equals(position.getActive()) && !requestedSymbols.contains(position.getCode())) {
                position.setActive(false);
                position.setUpdatedAt(confirmedAt);
                positionMapper.updateById(position);
            }
        }

        FinancialProfileConfirmation confirmation = confirmation(
                confirmationRef,
                userId,
                nextVersion,
                POSITIONS_ACTION,
                key,
                fingerprint,
                "positions",
                confirmedAt);
        confirmationMapper.insert(confirmation);
        return response(confirmation);
    }

    private long advanceProfileVersion(
            long userId,
            long expectedVersion,
            Consumer<UserConfig> mutation,
            OffsetDateTime updatedAt) {
        UserConfig config = configMapper.selectById(userId);
        long currentVersion = config == null || config.getProfileVersion() == null
                ? 0L
                : config.getProfileVersion();
        if (currentVersion != expectedVersion) {
            throw conflict("金融资料版本冲突，当前版本为 " + currentVersion);
        }
        long nextVersion = currentVersion + 1;
        if (config == null) {
            config = new UserConfig();
            config.setUserId(userId);
            mutation.accept(config);
            config.setProfileVersion(nextVersion);
            config.setUpdatedAt(updatedAt);
            if (configMapper.insert(config) != 1) {
                throw conflict("金融资料版本创建失败");
            }
            return nextVersion;
        }

        mutation.accept(config);
        config.setProfileVersion(nextVersion);
        config.setUpdatedAt(updatedAt);
        int changed = configMapper.update(
                config,
                new LambdaUpdateWrapper<UserConfig>()
                        .eq(UserConfig::getUserId, userId)
                        .eq(UserConfig::getProfileVersion, currentVersion));
        if (changed != 1) {
            throw conflict("金融资料已被其他请求更新");
        }
        return nextVersion;
    }

    private FinancialProfileConfirmation findReplay(
            long userId,
            String idempotencyKey,
            String actionType,
            String fingerprint) {
        FinancialProfileConfirmation existing = confirmationMapper.selectOne(
                new LambdaQueryWrapper<FinancialProfileConfirmation>()
                        .eq(FinancialProfileConfirmation::getUserId, userId)
                        .eq(FinancialProfileConfirmation::getIdempotencyKey, idempotencyKey));
        if (existing == null) {
            return null;
        }
        if (!actionType.equals(existing.getActionType())
                || !fingerprint.equals(existing.getRequestFingerprint())) {
            throw conflict("Idempotency-Key 已用于不同的金融资料请求");
        }
        return existing;
    }

    private ValidatedProfile validateProfile(FinancialProfileUpdateRequest request) {
        if (request == null) {
            throw badRequest("金融资料请求不能为空");
        }
        requireExpectedVersion(request.expectedProfileVersion());
        String currency = requiredUpper(request.currency(), "currency", 3, 8);
        BigDecimal cash = nonNegative(request.cash(), "cash");
        String riskTolerance = requiredLower(request.riskTolerance(), "risk_tolerance", 20);
        if (!RISK_LEVELS.contains(riskTolerance)) {
            throw badRequest("risk_tolerance 不受支持");
        }
        BigDecimal maxLoss = percentage(request.maxLossTolerancePct(), "max_loss_tolerance_pct");
        BigDecimal liquidAssets = nonNegative(request.liquidAssets(), "liquid_assets");
        BigDecimal cashNeeds = nonNegative(request.nearTermCashNeeds(), "near_term_cash_needs");
        Integer horizon = request.nearTermCashNeedsHorizonDays();
        if (horizon == null || horizon <= 0) {
            throw badRequest("near_term_cash_needs_horizon_days 必须大于 0");
        }
        return new ValidatedProfile(
                request.expectedProfileVersion(),
                currency,
                cash,
                riskTolerance,
                maxLoss,
                liquidAssets,
                cashNeeds,
                horizon);
    }

    private ValidatedPositions validatePositions(PortfolioPositionsUpdateRequest request) {
        if (request == null || request.positions() == null) {
            throw badRequest("positions 不能为空");
        }
        requireExpectedVersion(request.expectedProfileVersion());
        List<ValidatedPosition> positions = new ArrayList<>();
        Set<String> symbols = new HashSet<>();
        BigDecimal totalTargetWeight = BigDecimal.ZERO;
        for (PortfolioPositionsUpdateRequest.Position item : request.positions()) {
            if (item == null) {
                throw badRequest("positions 不能包含 null");
            }
            String symbol = requiredUpper(item.symbol(), "positions.symbol", 1, 32);
            if (!symbols.add(symbol)) {
                throw badRequest("positions.symbol 不能重复: " + symbol);
            }
            String name = required(item.name(), "positions.name", 100);
            String assetType = requiredLower(item.assetType(), "positions.asset_type", 20);
            if (!ASSET_TYPES.contains(assetType)) {
                throw badRequest("positions.asset_type 不受支持: " + assetType);
            }
            BigDecimal quantity = positive(item.quantity(), "positions.quantity");
            BigDecimal costPrice = nonNegative(item.costPrice(), "positions.cost_price");
            if (item.buyDate() == null) {
                throw badRequest("positions.buy_date 不能为空");
            }
            BigDecimal targetWeight = ratio(item.targetWeight(), "positions.target_weight");
            totalTargetWeight = totalTargetWeight.add(targetWeight);
            String exchange = requiredUpper(item.exchange(), "positions.exchange", 1, 16);
            String currency = requiredUpper(item.currency(), "positions.currency", 3, 8);
            positions.add(new ValidatedPosition(
                    symbol,
                    name,
                    assetType,
                    quantity,
                    costPrice,
                    item.buyDate(),
                    targetWeight,
                    optional(item.sector(), 50),
                    optional(item.riskRole(), 30),
                    exchange,
                    currency));
        }
        if (totalTargetWeight.compareTo(BigDecimal.ONE) > 0) {
            throw badRequest("positions.target_weight 合计不能大于 1");
        }
        positions.sort(Comparator.comparing(ValidatedPosition::symbol));
        return new ValidatedPositions(request.expectedProfileVersion(), List.copyOf(positions));
    }

    private void applyPosition(
            PortfolioPosition entity,
            ValidatedPosition item,
            String confirmationRef,
            OffsetDateTime confirmedAt) {
        entity.setName(item.name());
        entity.setAssetType(item.assetType());
        entity.setShares(item.quantity());
        entity.setAvgCost(item.costPrice());
        entity.setBuyDate(item.buyDate());
        entity.setTargetWeight(item.targetWeight());
        entity.setSector(item.sector());
        entity.setRiskRole(item.riskRole());
        entity.setExchange(item.exchange());
        entity.setCurrency(item.currency());
        entity.setDataSource(USER_INPUT);
        entity.setConfirmedAt(confirmedAt);
        entity.setSourceRef(confirmationRef);
        entity.setActive(true);
        entity.setUpdatedAt(confirmedAt);
    }

    private FinancialProfileConfirmation confirmation(
            String confirmationRef,
            long userId,
            long profileVersion,
            String actionType,
            String idempotencyKey,
            String requestFingerprint,
            String changedFields,
            OffsetDateTime confirmedAt) {
        FinancialProfileConfirmation result = new FinancialProfileConfirmation();
        result.setConfirmationRef(confirmationRef);
        result.setUserId(userId);
        result.setProfileVersion(profileVersion);
        result.setActionType(actionType);
        result.setIdempotencyKey(idempotencyKey);
        result.setRequestFingerprint(requestFingerprint);
        result.setChangedFields(changedFields);
        result.setConfirmedAt(confirmedAt);
        return result;
    }

    private FinancialProfileConfirmationResponse response(FinancialProfileConfirmation confirmation) {
        return new FinancialProfileConfirmationResponse(
                confirmation.getUserId(),
                confirmation.getProfileVersion(),
                USER_CONFIRMED,
                confirmation.getConfirmationRef(),
                confirmation.getConfirmedAt());
    }

    private String normalizeIdempotencyKey(String value) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty() || normalized.length() > 100) {
            throw badRequest("Idempotency-Key 必须为 1..100 个字符");
        }
        return normalized;
    }

    private void requireExpectedVersion(long value) {
        if (value < 0) {
            throw badRequest("expected_profile_version 不能小于 0");
        }
    }

    private void requireUser(long userId) {
        if (userId <= 0) {
            throw badRequest("用户身份无效");
        }
    }

    private BigDecimal percentage(BigDecimal value, String field) {
        BigDecimal result = nonNegative(value, field);
        if (result.compareTo(new BigDecimal("100")) > 0) {
            throw badRequest(field + " 必须在 0..100");
        }
        return result;
    }

    private BigDecimal ratio(BigDecimal value, String field) {
        BigDecimal result = nonNegative(value, field);
        if (result.compareTo(BigDecimal.ONE) > 0) {
            throw badRequest(field + " 必须在 0..1");
        }
        return result;
    }

    private BigDecimal positive(BigDecimal value, String field) {
        if (value == null || value.compareTo(BigDecimal.ZERO) <= 0) {
            throw badRequest(field + " 必须大于 0");
        }
        return value;
    }

    private BigDecimal nonNegative(BigDecimal value, String field) {
        if (value == null || value.compareTo(BigDecimal.ZERO) < 0) {
            throw badRequest(field + " 不能为空且不能小于 0");
        }
        return value;
    }

    private String requiredUpper(String value, String field, int min, int max) {
        String normalized = required(value, field, max).toUpperCase(Locale.ROOT);
        if (normalized.length() < min) {
            throw badRequest(field + " 长度不足");
        }
        return normalized;
    }

    private String requiredLower(String value, String field, int max) {
        return required(value, field, max).toLowerCase(Locale.ROOT);
    }

    private String required(String value, String field, int max) {
        String normalized = value == null ? "" : value.trim();
        if (normalized.isEmpty() || normalized.length() > max) {
            throw badRequest(field + " 必须为 1.." + max + " 个字符");
        }
        return normalized;
    }

    private String optional(String value, int max) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String normalized = value.trim();
        if (normalized.length() > max) {
            throw badRequest("可选文本字段长度不能超过 " + max);
        }
        return normalized;
    }

    private String fingerprint(String canonical) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(canonical.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (NoSuchAlgorithmException exc) {
            throw new IllegalStateException("SHA-256 unavailable", exc);
        }
    }

    private static String component(Object value) {
        String text;
        if (value instanceof BigDecimal decimal) {
            text = decimal.stripTrailingZeros().toPlainString();
        } else {
            text = String.valueOf(value);
        }
        return text.length() + ":" + text;
    }

    private OffsetDateTime now() {
        return OffsetDateTime.now(ZoneOffset.UTC);
    }

    private ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    private ResponseStatusException conflict(String message) {
        return new ResponseStatusException(HttpStatus.CONFLICT, message);
    }

    private record ValidatedProfile(
            long expectedVersion,
            String currency,
            BigDecimal cash,
            String riskTolerance,
            BigDecimal maxLossTolerancePct,
            BigDecimal liquidAssets,
            BigDecimal nearTermCashNeeds,
            int nearTermCashNeedsHorizonDays) {

        String canonical() {
            return String.join("|",
                    "PROFILE",
                    component(currency),
                    component(cash),
                    component(riskTolerance),
                    component(maxLossTolerancePct),
                    component(liquidAssets),
                    component(nearTermCashNeeds),
                    component(nearTermCashNeedsHorizonDays));
        }
    }

    private record ValidatedPositions(long expectedVersion, List<ValidatedPosition> positions) {
        String canonical() {
            StringBuilder result = new StringBuilder("POSITIONS");
            for (ValidatedPosition position : positions) {
                result.append('|').append(position.canonical());
            }
            return result.toString();
        }
    }

    private record ValidatedPosition(
            String symbol,
            String name,
            String assetType,
            BigDecimal quantity,
            BigDecimal costPrice,
            java.time.LocalDate buyDate,
            BigDecimal targetWeight,
            String sector,
            String riskRole,
            String exchange,
            String currency) {

        String canonical() {
            return String.join("|",
                    component(symbol),
                    component(name),
                    component(assetType),
                    component(quantity),
                    component(costPrice),
                    component(buyDate),
                    component(targetWeight),
                    component(sector),
                    component(riskRole),
                    component(exchange),
                    component(currency));
        }
    }
}

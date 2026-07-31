package com.stockwise.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.stockwise.entity.PortfolioPosition;
import com.stockwise.entity.UserConfig;
import com.stockwise.mapper.PortfolioPositionMapper;
import com.stockwise.mapper.UserConfigMapper;
import com.stockwise.tool.PortfolioAnalysisInput;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;

/**
 * 按用户加载真实持仓与资金配置，构建传给分析 Skill 的不可变业务快照。
 */
@Service
public class UserPortfolioService {

    private final PortfolioPositionMapper positionMapper;
    private final UserConfigMapper configMapper;

    public UserPortfolioService(PortfolioPositionMapper positionMapper,
                                UserConfigMapper configMapper) {
        this.positionMapper = positionMapper;
        this.configMapper = configMapper;
    }

    /**
     * 加载用户有效持仓；缺少任何必需业务事实时明确追问，不允许回退示例持仓。
     */
    public PortfolioAnalysisInput loadRequired(Long userId) {
        if (userId == null) {
            throw new PortfolioDataMissingException("缺少用户身份，无法读取真实持仓");
        }
        UserConfig config = configMapper.selectById(userId);
        if (config == null || config.getMonthlyBudget() == null || config.getMonthlyBudget() <= 0) {
            throw new PortfolioDataMissingException("请先配置每月可投资预算和现金余额");
        }
        List<PortfolioPosition> positions = positionMapper.selectList(
                new LambdaQueryWrapper<PortfolioPosition>()
                        .eq(PortfolioPosition::getUserId, userId)
                        .eq(PortfolioPosition::getActive, true)
                        .orderByAsc(PortfolioPosition::getCode));
        if (positions.isEmpty()) {
            throw new PortfolioDataMissingException("请先录入至少一条有效持仓");
        }

        // 1. 业务实体只转换为 Skill 契约允许的字段，不发送数据库主键和审计时间
        List<PortfolioAnalysisInput.Position> inputs = positions.stream()
                .map(this::toInput)
                .toList();
        return new PortfolioAnalysisInput(
                BigDecimal.valueOf(config.getMonthlyBudget()),
                defaultDecimal(config.getCash()),
                defaultReserve(config.getCashReserveRatio()),
                inputs);
    }

    private PortfolioAnalysisInput.Position toInput(PortfolioPosition position) {
        if (position.getCode() == null
                || position.getName() == null
                || position.getAvgCost() == null
                || position.getShares() == null
                || position.getBuyDate() == null
                || position.getTargetWeight() == null) {
            throw new PortfolioDataMissingException(
                    "持仓 " + position.getCode() + " 缺少成本、份额、日期或目标权重");
        }
        return new PortfolioAnalysisInput.Position(
                position.getCode(),
                position.getName(),
                position.getAssetType(),
                position.getAvgCost(),
                position.getShares(),
                position.getBuyDate(),
                position.getTargetWeight(),
                position.getSector(),
                position.getRiskRole());
    }

    private BigDecimal defaultDecimal(BigDecimal value) {
        return value == null ? BigDecimal.ZERO : value;
    }

    private BigDecimal defaultReserve(BigDecimal value) {
        BigDecimal floor = new BigDecimal("0.15");
        return value == null || value.compareTo(floor) < 0 ? floor : value;
    }
}

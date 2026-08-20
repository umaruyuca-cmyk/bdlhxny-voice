"""SuitabilityEngine：确定性风险匹配筛查（v0 启发式）。

输入同轮 StockResearchResult + FinancialSnapshot，按 SuitabilityV0RuleSet 评估。
对外定位是个性化风险匹配筛查，不是法定适当性、也不是买卖建议。
v0 永不输出 SUITABLE（缺少已确认拟投入金额/配置时一律封顶 CONDITIONALLY_SUITABLE）。
"""

from __future__ import annotations

from typing import Any, Literal

from .contracts import (
    ConcentrationConflict,
    FinancialDataMode,
    FinancialSnapshot,
    LiquidityImpact,
    MarketRiskProxy,
    PortfolioImpact,
    StockResearchResult,
    SuitabilityAssessment,
    SuitabilityCondition,
    SuitabilityRuleEvaluation,
    SuitabilityV0RuleSet,
)
from .suitability_v0_ruleset import RULE_IDS, default_suitability_v0_rule_set

RuleOutcome = Literal["PASS", "CONDITIONAL", "BLOCK", "UNKNOWN"]
RiskBand = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
RiskLevel = Literal["CONSERVATIVE", "BALANCED", "AGGRESSIVE"]


class SuitabilityEngine:
    """纯函数式规则引擎：无 I/O、无 LLM、无时钟。"""

    def __init__(self, rule_set: SuitabilityV0RuleSet | None = None) -> None:
        self._rule_set = rule_set or default_suitability_v0_rule_set()

    @property
    def rule_set(self) -> SuitabilityV0RuleSet:
        return self._rule_set

    def evaluate(
        self,
        *,
        research: StockResearchResult,
        snapshot: FinancialSnapshot,
    ) -> SuitabilityAssessment:
        evidence = sorted(set(snapshot.provenance))
        if not evidence:
            raise ValueError("SUITABILITY_EVIDENCE_REQUIRED: snapshot provenance is required")

        proxy = self._market_risk_proxy(research=research, evidence_refs=evidence)
        evaluations = [
            self._rule_research_coverage(research, evidence),
            self._rule_data_authenticity(snapshot, evidence),
            self._rule_risk_level(snapshot, proxy, evidence),
            self._rule_max_loss(snapshot, proxy, evidence),
            self._rule_concentration(research, snapshot, evidence),
            self._rule_liquidity(snapshot, evidence),
            self._rule_goal_horizon(snapshot, proxy, evidence),
        ]

        result, required, reasons, limitations = self._aggregate(evaluations)
        limitations = list(
            dict.fromkeys(
                limitations
                + list(snapshot.limitations)
                + list(research.limitations)
                + list(proxy.limitations)
                + [
                    "本结果为内部风险匹配筛查（suitability-v0.1 DRAFT），不是法定适当性评估或投资建议",
                ]
            )
        )

        concentration_conflicts = [
            ConcentrationConflict(
                conflict_id=f"concentration:{item.rule_id}",
                exposure_type=str(item.actual_values.get("exposure_type") or "POSITION"),
                current_value=_as_float(item.actual_values.get("current_value")),
                threshold=_as_float(item.threshold_values.get("block_above_pct")),
                rule_id=item.rule_id,
            )
            for item in evaluations
            if item.rule_id == "SUIT-CONCENTRATION-001" and item.outcome == "BLOCK"
        ]

        portfolio_impact = PortfolioImpact(
            current_exposure={
                key: value
                for key, value in {
                    "single_position_weight_pct": _as_float(
                        next(
                            (
                                item.actual_values.get("weight_pct")
                                for item in evaluations
                                if item.rule_id == "SUIT-CONCENTRATION-001"
                            ),
                            None,
                        )
                    ),
                }.items()
                if value is not None
            },
            projected_exposure={},
            rule_ids=["SUIT-CONCENTRATION-001"],
        )

        liquidity_eval = next(item for item in evaluations if item.rule_id == "SUIT-LIQUIDITY-001")
        liquidity_impact = LiquidityImpact(
            status=(
                "OK"
                if liquidity_eval.outcome == "PASS"
                else "CONSTRAINED"
                if liquidity_eval.outcome in {"CONDITIONAL", "BLOCK"}
                else "UNKNOWN"
            ),
            reasons=[liquidity_eval.public_reason],
        )

        return SuitabilityAssessment(
            rule_set_version=self._rule_set.version,
            rule_ids=list(RULE_IDS),
            evidence_refs=evidence,
            result=result,
            market_risk_proxy=proxy,
            rule_evaluations=evaluations,
            proposed_allocation_confirmed=False,
            portfolio_impact=portfolio_impact,
            liquidity_impact=liquidity_impact,
            concentration_conflicts=concentration_conflicts,
            required_conditions=required,
            reasons=reasons,
            limitations=limitations,
        )

    def _aggregate(
        self,
        evaluations: list[SuitabilityRuleEvaluation],
    ) -> tuple[
        Literal[
            "SUITABLE",
            "CONDITIONALLY_SUITABLE",
            "CURRENTLY_NOT_SUITABLE",
            "INSUFFICIENT_INFORMATION",
        ],
        list[SuitabilityCondition],
        list[str],
        list[str],
    ]:
        reasons = [item.public_reason for item in evaluations if item.outcome != "PASS"]
        limitations = [lim for item in evaluations for lim in item.limitations]

        if any(item.critical and item.outcome == "UNKNOWN" for item in evaluations):
            return (
                "INSUFFICIENT_INFORMATION",
                [
                    SuitabilityCondition(
                        condition_id="SUITABILITY_INPUT_GAP",
                        description="关键适配规则缺少可审计输入，无法完成风险匹配筛查",
                        verification_source="research_and_snapshot",
                    )
                ],
                reasons or ["关键规则输入不足"],
                limitations,
            )
        if any(item.outcome == "BLOCK" for item in evaluations):
            return (
                "CURRENTLY_NOT_SUITABLE",
                [],
                reasons,
                limitations,
            )
        if any(item.outcome == "CONDITIONAL" for item in evaluations):
            return (
                "CONDITIONALLY_SUITABLE",
                [
                    SuitabilityCondition(
                        condition_id="SUITABILITY_CONDITIONS_PRESENT",
                        description="存在需确认的匹配条件，请审阅筛查理由后再决定下一步",
                        verification_source="user_review",
                    )
                ],
                reasons,
                limitations,
            )
        # v0：即使全 PASS 也封顶，缺少已确认拟投入金额/配置
        return (
            "CONDITIONALLY_SUITABLE",
            [
                SuitabilityCondition(
                    condition_id="SUITABILITY_PROPOSED_AMOUNT_REQUIRED",
                    description="缺少已确认的拟投入金额或拟配置比例，不能给出适合配置结论",
                    verification_source="user_confirmed_proposed_allocation",
                )
            ],
            ["规则均通过，但 v0 在缺少拟投入确认时封顶为有条件匹配"],
            limitations,
        )

    def _market_risk_proxy(
        self,
        *,
        research: StockResearchResult,
        evidence_refs: list[str],
    ) -> MarketRiskProxy:
        thresholds = self._rule_set.market_risk_proxy_thresholds
        mdd = self._extract_max_drawdown_pct(research)
        vol = self._extract_vol_ann_pct(research)
        severity = self._highest_risk_severity(research)
        limitations: list[str] = []
        if mdd is None and vol is None and severity is None:
            limitations.append("Insufficient objective inputs for market risk proxy band")
            return MarketRiskProxy(
                band="UNKNOWN",
                evidence_refs=list(evidence_refs),
                limitations=limitations,
                price_adjustment=thresholds.price_adjustment,
                annualization_trading_days=thresholds.annualization_trading_days,
            )

        band: RiskBand = "UNKNOWN"
        if (
            (mdd is not None and mdd >= thresholds.high_max_drawdown_pct)
            or (vol is not None and vol >= thresholds.high_annualized_volatility_pct)
            or severity in {"HIGH", "CRITICAL"}
        ):
            band = "HIGH"
        elif (
            (mdd is not None and mdd >= thresholds.medium_max_drawdown_pct)
            or (vol is not None and vol >= thresholds.medium_annualized_volatility_pct)
            or severity == "MEDIUM"
        ):
            band = "MEDIUM"
        elif mdd is not None or vol is not None:
            band = "LOW"
        else:
            # 仅有 severity 且为 LOW：按 ADR 不得推断 LOW band
            limitations.append("Research risk severity alone cannot prove LOW market risk proxy band")
            band = "UNKNOWN"

        return MarketRiskProxy(
            band=band,
            max_drawdown_pct=mdd,
            annualized_volatility_pct=vol,
            highest_research_risk_severity=severity,
            evidence_refs=list(evidence_refs),
            limitations=limitations,
            price_adjustment=thresholds.price_adjustment,
            annualization_trading_days=thresholds.annualization_trading_days,
        )

    def _rule_research_coverage(
        self, research: StockResearchResult, evidence: list[str]
    ) -> SuitabilityRuleEvaluation:
        level = research.confidence.level
        ok = research.coverage == "COMPLETE" and level in {"MEDIUM", "HIGH"}
        return SuitabilityRuleEvaluation(
            rule_id="SUIT-RESEARCH-COVERAGE-001",
            outcome="PASS" if ok else "UNKNOWN",
            critical=True,
            reason_code="RESEARCH_COVERAGE_OK" if ok else "RESEARCH_COVERAGE_INSUFFICIENT",
            public_reason=(
                f"研究覆盖或置信度不足，无法做个性化匹配。coverage={research.coverage}, confidence={level}"
                if not ok
                else "研究覆盖与置信度满足匹配门禁。"
            ),
            actual_values={"coverage": research.coverage, "confidence": level},
            evidence_refs=list(evidence) if ok else [],
            limitations=[] if ok else ["Research coverage or confidence below suitability gate"],
        )

    def _rule_data_authenticity(
        self, snapshot: FinancialSnapshot, evidence: list[str]
    ) -> SuitabilityRuleEvaluation:
        mode = snapshot.data_mode
        confirmed = mode == FinancialDataMode.USER_CONFIRMED and any(
            item.confirmation_ref for item in snapshot.data_references
        )
        live_ok = mode == FinancialDataMode.LIVE and not snapshot.is_mock
        completeness_ok = snapshot.completeness in {"COMPLETE", "PARTIAL"}
        ok = (live_ok or confirmed) and completeness_ok and mode not in {
            FinancialDataMode.MOCK,
            FinancialDataMode.UNAVAILABLE,
            FinancialDataMode.TEST_FIXTURE,
        }
        return SuitabilityRuleEvaluation(
            rule_id="SUIT-DATA-AUTHENTICITY-001",
            outcome="PASS" if ok else "UNKNOWN",
            critical=True,
            reason_code="DATA_AUTHENTICITY_OK" if ok else "DATA_AUTHENTICITY_INSUFFICIENT",
            public_reason=(
                f"用户金融数据真实性或完整性不满足适配评估要求。data_mode={mode.value}"
                if not ok
                else "用户金融数据模式满足匹配门禁。"
            ),
            actual_values={
                "data_mode": mode.value,
                "is_mock": snapshot.is_mock,
                "completeness": snapshot.completeness,
            },
            evidence_refs=list(evidence) if ok else [],
            limitations=[] if ok else ["Snapshot authenticity/completeness gate failed"],
        )

    def _rule_risk_level(
        self,
        snapshot: FinancialSnapshot,
        proxy: MarketRiskProxy,
        evidence: list[str],
    ) -> SuitabilityRuleEvaluation:
        risk_level = snapshot.risk_profile.risk_level if snapshot.risk_profile else None
        band = proxy.band
        if risk_level is None or band == "UNKNOWN":
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-RISK-LEVEL-001",
                outcome="UNKNOWN",
                critical=True,
                reason_code="RISK_LEVEL_INPUT_MISSING",
                public_reason="缺少风险承受等级或标的市场风险代理带，无法匹配。",
                actual_values={"risk_level": risk_level, "asset_risk_band": band},
                evidence_refs=[],
                limitations=["risk_level or asset_risk_band unavailable"],
            )
        matrix: dict[RiskLevel, dict[str, RuleOutcome]] = {
            "CONSERVATIVE": {"LOW": "PASS", "MEDIUM": "BLOCK", "HIGH": "BLOCK"},
            "BALANCED": {"LOW": "PASS", "MEDIUM": "PASS", "HIGH": "BLOCK"},
            "AGGRESSIVE": {"LOW": "PASS", "MEDIUM": "PASS", "HIGH": "PASS"},
        }
        outcome = matrix[risk_level][band]
        return SuitabilityRuleEvaluation(
            rule_id="SUIT-RISK-LEVEL-001",
            outcome=outcome,
            critical=True,
            reason_code=f"RISK_LEVEL_{outcome}",
            public_reason=(
                f"标的风险带与您的风险承受等级不匹配。您的等级为 {risk_level}，标的风险带为 {band}。"
                if outcome == "BLOCK"
                else f"风险等级与标的风险带匹配（{risk_level} / {band}）。"
            ),
            actual_values={"risk_level": risk_level, "asset_risk_band": band},
            evidence_refs=list(evidence),
        )

    def _rule_max_loss(
        self,
        snapshot: FinancialSnapshot,
        proxy: MarketRiskProxy,
        evidence: list[str],
    ) -> SuitabilityRuleEvaluation:
        tolerance = snapshot.risk_profile.max_loss_tolerance_pct if snapshot.risk_profile else None
        mdd = proxy.max_drawdown_pct
        if tolerance is None or mdd is None:
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-MAX-LOSS-001",
                outcome="UNKNOWN",
                critical=True,
                reason_code="MAX_LOSS_INPUT_MISSING",
                public_reason="缺少最大损失容忍或标的历史最大回撤，无法评估。",
                actual_values={"max_loss_tolerance_pct": tolerance, "max_drawdown_pct": mdd},
                evidence_refs=[],
                limitations=["max_loss_tolerance_pct or max_drawdown_pct unavailable"],
            )
        if mdd > tolerance:
            outcome: RuleOutcome = "BLOCK"
        elif mdd == tolerance:
            outcome = "CONDITIONAL"
        else:
            outcome = "PASS"
        return SuitabilityRuleEvaluation(
            rule_id="SUIT-MAX-LOSS-001",
            outcome=outcome,
            critical=True,
            reason_code=f"MAX_LOSS_{outcome}",
            public_reason=(
                f"标的历史最大回撤 {mdd}% 超过您设定的最大损失容忍 {tolerance}%。"
                if outcome == "BLOCK"
                else f"标的历史最大回撤恰好达到您的最大损失容忍 {tolerance}%，请确认是否可接受。"
                if outcome == "CONDITIONAL"
                else f"标的历史最大回撤 {mdd}% 低于您的最大损失容忍 {tolerance}%。"
            ),
            actual_values={"max_loss_tolerance_pct": tolerance, "max_drawdown_pct": mdd},
            threshold_values={"equal_outcome": self._rule_set.max_loss_equal_outcome},
            evidence_refs=list(evidence),
            limitations=["历史最大回撤不是对未来损失的承诺"],
        )

    def _rule_concentration(
        self,
        research: StockResearchResult,
        snapshot: FinancialSnapshot,
        evidence: list[str],
    ) -> SuitabilityRuleEvaluation:
        risk_level = snapshot.risk_profile.risk_level if snapshot.risk_profile else None
        if risk_level is None:
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-CONCENTRATION-001",
                outcome="UNKNOWN",
                critical=True,
                reason_code="CONCENTRATION_PROFILE_MISSING",
                public_reason="缺少风险等级，无法评估集中度阈值。",
                actual_values={},
                evidence_refs=[],
                limitations=["risk_level unavailable for concentration"],
            )
        symbol = research.instrument.symbol
        weight = 0.0
        has_weight = True
        matched = next((item for item in snapshot.positions if item.symbol == symbol), None)
        if matched is not None:
            if matched.weight_pct is None:
                has_weight = False
            else:
                weight = float(matched.weight_pct)
        if not has_weight:
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-CONCENTRATION-001",
                outcome="UNKNOWN",
                critical=True,
                reason_code="CONCENTRATION_WEIGHT_MISSING",
                public_reason="当前持仓缺少可审计权重，无法评估集中度。",
                actual_values={"symbol": symbol},
                evidence_refs=[],
                limitations=["position weight_pct unavailable"],
            )

        single = self._rule_set.single_position_thresholds[risk_level]
        industry_weight = self._industry_weight_pct(snapshot, matched.industry if matched else None)
        industry = self._rule_set.industry_thresholds[risk_level]
        outcome: RuleOutcome = "PASS"
        exposure_type = "POSITION"
        current = weight
        block_thr = single.block_above_pct
        cond_thr = single.conditional_above_pct
        if weight > single.block_above_pct:
            outcome = "BLOCK"
        elif weight > single.conditional_above_pct:
            outcome = "CONDITIONAL"
        if industry_weight is not None:
            if industry_weight > industry.block_above_pct:
                outcome = "BLOCK"
                exposure_type = "INDUSTRY"
                current = industry_weight
                block_thr = industry.block_above_pct
                cond_thr = industry.conditional_above_pct
            elif industry_weight > industry.conditional_above_pct and outcome == "PASS":
                outcome = "CONDITIONAL"
                exposure_type = "INDUSTRY"
                current = industry_weight
                block_thr = industry.block_above_pct
                cond_thr = industry.conditional_above_pct

        return SuitabilityRuleEvaluation(
            rule_id="SUIT-CONCENTRATION-001",
            outcome=outcome,
            critical=True,
            reason_code=f"CONCENTRATION_{outcome}",
            public_reason=(
                f"当前单标的或行业集中度过高。类型={exposure_type}，当前={current}%，阈值={block_thr}%。"
                if outcome == "BLOCK"
                else f"当前集中度接近阈值。类型={exposure_type}，当前={current}%，条件阈值={cond_thr}%。"
                if outcome == "CONDITIONAL"
                else f"当前单标的集中度 {weight}% 在可接受范围内。"
            ),
            actual_values={
                "weight_pct": weight,
                "industry_weight_pct": industry_weight,
                "exposure_type": exposure_type,
                "current_value": current,
            },
            threshold_values={
                "conditional_above_pct": cond_thr,
                "block_above_pct": block_thr,
            },
            evidence_refs=list(evidence),
        )

    def _rule_liquidity(
        self, snapshot: FinancialSnapshot, evidence: list[str]
    ) -> SuitabilityRuleEvaluation:
        liquidity = snapshot.liquidity
        if (
            liquidity is None
            or liquidity.liquid_assets is None
            or liquidity.near_term_cash_needs is None
            or liquidity.status == "UNKNOWN"
        ):
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-LIQUIDITY-001",
                outcome="UNKNOWN",
                critical=True,
                reason_code="LIQUIDITY_INPUT_MISSING",
                public_reason="缺少可变现资产或近期资金需求，无法评估流动性。",
                actual_values={},
                evidence_refs=[],
                limitations=["liquidity facts unavailable"],
            )
        assets = float(liquidity.liquid_assets)
        needs = float(liquidity.near_term_cash_needs)
        ratio = self._rule_set.liquidity_pass_buffer_ratio
        if assets < needs:
            outcome: RuleOutcome = "BLOCK"
        elif assets < needs * ratio:
            outcome = "CONDITIONAL"
        else:
            outcome = "PASS"
        return SuitabilityRuleEvaluation(
            rule_id="SUIT-LIQUIDITY-001",
            outcome=outcome,
            critical=True,
            reason_code=f"LIQUIDITY_{outcome}",
            public_reason=(
                "可变现资产不足以覆盖近期资金需求。"
                if outcome == "BLOCK"
                else "可变现资产对近期资金需求的缓冲不足 20%，请确认短期开支安排。"
                if outcome == "CONDITIONAL"
                else "可变现资产覆盖近期资金需求并保留缓冲。"
            ),
            actual_values={"liquid_assets": assets, "near_term_cash_needs": needs},
            threshold_values={"pass_buffer_ratio": ratio},
            evidence_refs=list(evidence),
        )

    def _rule_goal_horizon(
        self,
        snapshot: FinancialSnapshot,
        proxy: MarketRiskProxy,
        evidence: list[str],
    ) -> SuitabilityRuleEvaluation:
        goals = list(snapshot.goals)
        if not goals:
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-GOAL-HORIZON-001",
                outcome="UNKNOWN",
                critical=False,
                reason_code="GOAL_HORIZON_ABSENT",
                public_reason="未提供已确认投资目标，目标期限规则不单独裁决。",
                actual_values={"goal_count": 0},
                evidence_refs=[],
                limitations=["No confirmed goals"],
            )
        band = proxy.band
        if band == "UNKNOWN":
            return SuitabilityRuleEvaluation(
                rule_id="SUIT-GOAL-HORIZON-001",
                outcome="UNKNOWN",
                critical=False,
                reason_code="GOAL_HORIZON_BAND_UNKNOWN",
                public_reason="标的风险带未知，目标期限规则无法比较。",
                actual_values={"goal_count": len(goals)},
                evidence_refs=[],
                limitations=["asset_risk_band unknown"],
            )
        outcome: RuleOutcome = "PASS"
        for goal in goals:
            horizon = goal.horizon
            if horizon == "SHORT_TERM" and band == "HIGH":
                outcome = "BLOCK"
                break
            if (horizon == "SHORT_TERM" and band == "MEDIUM") or (
                horizon == "MEDIUM_TERM" and band == "HIGH"
            ):
                outcome = "CONDITIONAL"
        return SuitabilityRuleEvaluation(
            rule_id="SUIT-GOAL-HORIZON-001",
            outcome=outcome,
            critical=False,
            reason_code=f"GOAL_HORIZON_{outcome}",
            public_reason=(
                "存在短期目标，但标的风险带为高，期限与风险不匹配。"
                if outcome == "BLOCK"
                else "目标期限与标的风险带存在需确认的张力。"
                if outcome == "CONDITIONAL"
                else "已确认目标期限与标的风险带暂无明显冲突。"
            ),
            actual_values={
                "goals": [{"goal_id": g.goal_id, "horizon": g.horizon} for g in goals],
                "asset_risk_band": band,
            },
            evidence_refs=list(evidence),
        )

    @staticmethod
    def _industry_weight_pct(snapshot: FinancialSnapshot, industry: str | None) -> float | None:
        if not industry:
            return None
        total = 0.0
        saw = False
        for item in snapshot.positions:
            if item.industry != industry:
                continue
            if item.weight_pct is None:
                return None
            total += float(item.weight_pct)
            saw = True
        return total if saw else None

    @staticmethod
    def _extract_max_drawdown_pct(research: StockResearchResult) -> float | None:
        indicators = research.technicals.indicators if research.technicals else {}
        for key in ("max_drawdown_pct", "max_drawdown", "mdd_pct", "mdd"):
            value = _as_float(indicators.get(key)) if isinstance(indicators, dict) else None
            if value is None:
                continue
            # 若是比例 0..1，转为百分数点
            if 0 <= value <= 1:
                return abs(value) * 100
            return abs(value)
        return None

    @staticmethod
    def _extract_vol_ann_pct(research: StockResearchResult) -> float | None:
        indicators = research.technicals.indicators if research.technicals else {}
        for key in ("annualized_volatility_pct", "annualized_volatility", "vol_ann_pct"):
            value = _as_float(indicators.get(key)) if isinstance(indicators, dict) else None
            if value is None:
                continue
            if 0 <= value <= 1:
                return value * 100
            return value
        return None

    @staticmethod
    def _highest_risk_severity(
        research: StockResearchResult,
    ) -> Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None:
        order = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        best: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
        for item in research.risks:
            severity = item.severity
            if severity not in order:
                continue
            if best is None or order[severity] > order[best]:
                best = severity  # type: ignore[assignment]
        return best


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

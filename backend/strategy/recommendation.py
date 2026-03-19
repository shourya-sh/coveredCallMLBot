"""
Recommendation Engine

Decides whether to SELL or HOLD and generates human-readable explanations.

Decision logic considers:
- Option availability and quality
- Scoring thresholds
- Market conditions
- Risk/reward balance
"""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field

from models.options import ScoredOption
from models.risk_profiles import RiskProfile


class RecommendationAction(str, Enum):
    """Recommendation action"""
    SELL = "SELL"
    HOLD = "HOLD"


class Recommendation(BaseModel):
    """
    Covered call recommendation
    
    Contains:
    - Action (SELL/HOLD)
    - Best contract (if SELL)
    - Reasoning
    - Metrics
    """
    action: RecommendationAction
    ticker: str
    risk_profile: RiskProfile
    
    # If action is SELL
    recommended_contract: Optional[dict] = None
    metrics: Optional[dict] = None
    
    # Human-readable explanation
    explanation: str
    confidence: str = Field(default="medium", description="high/medium/low")
    
    # Additional context
    alternative_contracts: List[dict] = Field(default_factory=list, description="Other viable options")
    warnings: List[str] = Field(default_factory=list, description="Risk warnings")


class RecommendationEngine:
    """
    Generates actionable recommendations for covered calls
    
    Decision Criteria:
    ------------------
    SELL when:
    - Best option score > threshold
    - Annualized return meets minimum
    - Assignment risk acceptable
    - Adequate liquidity
    
    HOLD when:
    - No contracts meet criteria
    - Market conditions unfavorable
    - Risk too high for reward
    """
    
    # Minimum score thresholds by risk profile
    SCORE_THRESHOLDS = {
        RiskProfile.CONSERVATIVE: 60.0,
        RiskProfile.MODERATE: 50.0,
        RiskProfile.AGGRESSIVE: 40.0,
    }
    
    # Minimum annualized return thresholds
    MIN_ANNUAL_RETURN = {
        RiskProfile.CONSERVATIVE: 8.0,   # 8% annual
        RiskProfile.MODERATE: 12.0,      # 12% annual
        RiskProfile.AGGRESSIVE: 18.0,    # 18% annual
    }
    
    def __init__(self, risk_profile: RiskProfile):
        """
        Initialize recommendation engine
        
        Args:
            risk_profile: User's risk tolerance
        """
        self.risk_profile = risk_profile
        self.score_threshold = self.SCORE_THRESHOLDS[risk_profile]
        self.min_return = self.MIN_ANNUAL_RETURN[risk_profile]
    
    def generate_recommendation(
        self,
        ticker: str,
        best_option: Optional[ScoredOption],
        all_scored_options: List[ScoredOption] = None
    ) -> Recommendation:
        """
        Generate recommendation based on analyzed options
        
        Args:
            ticker: Stock ticker
            best_option: Highest-scored option (or None if none available)
            all_scored_options: All scored options for alternatives
            
        Returns:
            Recommendation object with action and explanation
        """
        if all_scored_options is None:
            all_scored_options = []
        
        # Case 1: No options available
        if best_option is None:
            return self._recommend_hold_no_options(ticker)
        
        # Case 2: Best option doesn't meet score threshold
        if best_option.score < self.score_threshold:
            return self._recommend_hold_low_score(ticker, best_option)
        
        # Case 3: Best option doesn't meet return threshold
        if best_option.metrics.annualized_return < self.min_return:
            return self._recommend_hold_low_return(ticker, best_option)
        
        # Case 4: Assignment risk too high (even for aggressive)
        if best_option.delta and best_option.delta > 0.75:
            return self._recommend_hold_high_risk(ticker, best_option)
        
        # Case 5: All checks passed - SELL recommendation
        return self._recommend_sell(ticker, best_option, all_scored_options)
    
    def _recommend_sell(
        self,
        ticker: str,
        best_option: ScoredOption,
        all_options: List[ScoredOption]
    ) -> Recommendation:
        """Generate SELL recommendation"""
        
        # Build contract details
        contract_details = {
            "strike": best_option.strike,
            "expiration": best_option.expiration.strftime("%Y-%m-%d"),
            "premium": round(best_option.premium, 2),
            "delta": round(best_option.delta, 2) if best_option.delta else None,
        }
        
        # Build metrics
        metrics = best_option.metrics.to_dict()
        
        # Generate explanation
        explanation = self._generate_sell_explanation(best_option)
        
        # Determine confidence
        confidence = self._determine_confidence(best_option)
        
        # Find alternatives (next 2-3 options)
        alternatives = []
        for opt in all_options[1:4]:  # Skip first (best), take next 3
            alternatives.append({
                "strike": opt.strike,
                "expiration": opt.expiration.strftime("%Y-%m-%d"),
                "premium": round(opt.premium, 2),
                "score": round(opt.score, 2),
            })
        
        # Generate warnings
        warnings = self._generate_warnings(best_option)
        
        return Recommendation(
            action=RecommendationAction.SELL,
            ticker=ticker,
            risk_profile=self.risk_profile,
            recommended_contract=contract_details,
            metrics=metrics,
            explanation=explanation,
            confidence=confidence,
            alternative_contracts=alternatives,
            warnings=warnings
        )
    
    def _recommend_hold_no_options(self, ticker: str) -> Recommendation:
        """Generate HOLD recommendation when no options available"""
        return Recommendation(
            action=RecommendationAction.HOLD,
            ticker=ticker,
            risk_profile=self.risk_profile,
            explanation=f"No suitable covered call contracts found for {ticker} that match your {self.risk_profile.value} risk profile. This could be due to low option liquidity, unfavorable strike prices, or expiration dates outside your preferred range.",
            confidence="high"
        )
    
    def _recommend_hold_low_score(self, ticker: str, option: ScoredOption) -> Recommendation:
        """Generate HOLD recommendation when best option scores too low"""
        return Recommendation(
            action=RecommendationAction.HOLD,
            ticker=ticker,
            risk_profile=self.risk_profile,
            explanation=f"Available options for {ticker} do not meet quality thresholds. The best contract (${option.strike} strike) scored {option.score:.1f}/100, below the {self.score_threshold} threshold for your {self.risk_profile.value} profile. Consider waiting for better opportunities or adjusting your risk profile.",
            confidence="high"
        )
    
    def _recommend_hold_low_return(self, ticker: str, option: ScoredOption) -> Recommendation:
        """Generate HOLD recommendation when returns are too low"""
        return Recommendation(
            action=RecommendationAction.HOLD,
            ticker=ticker,
            risk_profile=self.risk_profile,
            explanation=f"The best available option for {ticker} offers {option.metrics.annualized_return:.1f}% annualized return, below your {self.min_return:.1f}% minimum for {self.risk_profile.value} profile. The premium of ${option.premium:.2f} does not justify the assignment risk. Wait for higher implied volatility or consider a different strike.",
            confidence="medium"
        )
    
    def _recommend_hold_high_risk(self, ticker: str, option: ScoredOption) -> Recommendation:
        """Generate HOLD recommendation when assignment risk is too high"""
        assignment_prob = option.delta * 100 if option.delta else 0
        return Recommendation(
            action=RecommendationAction.HOLD,
            ticker=ticker,
            risk_profile=self.risk_profile,
            explanation=f"The best available option has {assignment_prob:.0f}% assignment probability (delta {option.delta:.2f}), which is excessively high even for aggressive strategies. If assigned, your shares would be called away at ${option.strike}, potentially limiting upside. Wait for better strike prices or accept the assignment risk consciously.",
            confidence="high",
            warnings=["Very high assignment probability"]
        )
    
    def _generate_sell_explanation(self, option: ScoredOption) -> str:
        """Generate explanation for SELL recommendation"""
        
        parts = []
        
        # Opening statement
        if option.metrics.annualized_return > 25:
            parts.append("Exceptional opportunity identified.")
        elif option.metrics.annualized_return > 18:
            parts.append("Strong covered call opportunity.")
        else:
            parts.append("Favorable covered call setup.")
        
        # Return component
        parts.append(f"This ${option.strike} strike offers {option.metrics.annualized_return:.1f}% annualized return with {option.metrics.premium_yield:.2f}% premium yield.")
        
        # Risk component
        if option.delta:
            assignment_prob = option.delta * 100
            if assignment_prob < 30:
                parts.append(f"Low assignment risk ({assignment_prob:.0f}% probability) provides income stability.")
            elif assignment_prob < 50:
                parts.append(f"Moderate assignment risk ({assignment_prob:.0f}% probability) balances income and potential appreciation.")
            else:
                parts.append(f"Higher assignment risk ({assignment_prob:.0f}% probability) is compensated by premium income.")
        
        # Downside protection
        parts.append(f"Provides {option.metrics.downside_protection:.2f}% downside protection with break-even at ${option.metrics.break_even_price:.2f}.")
        
        # Time component
        if option.metrics.days_to_expiration <= 21:
            parts.append(f"Short {option.metrics.days_to_expiration}-day expiration allows quick turnaround.")
        elif option.metrics.days_to_expiration <= 45:
            parts.append(f"Medium-term {option.metrics.days_to_expiration}-day expiration balances theta decay and flexibility.")
        else:
            parts.append(f"Longer {option.metrics.days_to_expiration}-day expiration provides extended premium collection.")
        
        return " ".join(parts)
    
    def _determine_confidence(self, option: ScoredOption) -> str:
        """Determine confidence level for recommendation"""
        
        # High confidence criteria
        if (option.score >= 75 and 
            option.metrics.annualized_return >= self.min_return * 1.5):
            return "high"
        
        # Low confidence criteria
        if (option.score < self.score_threshold * 1.2 or
            option.metrics.annualized_return < self.min_return * 1.1):
            return "low"
        
        return "medium"
    
    def _generate_warnings(self, option: ScoredOption) -> List[str]:
        """Generate risk warnings for the recommendation"""
        warnings = []
        
        # High assignment risk warning
        if option.delta and option.delta > 0.60:
            warnings.append(f"High assignment probability ({option.delta * 100:.0f}%) - shares may be called away")
        
        # Short expiration warning
        if option.metrics.days_to_expiration < 14:
            warnings.append("Very short expiration requires close monitoring")
        
        # ITM option warning
        if option.strike < option.metrics.stock_price:
            warnings.append("In-the-money option - immediate assignment risk if exercised early")
        
        # Low premium warning
        if option.metrics.premium_yield < 1.0:
            warnings.append("Relatively low premium yield - ensure risk/reward is acceptable")
        
        return warnings


# Example usage
if __name__ == "__main__":
    from datetime import datetime, timedelta
    from data_ingestion.options_scraper import OptionContract
    from models.options import OptionMetrics
    
    # Create sample scored option
    expiration = datetime.now() + timedelta(days=30)
    
    # Simulate a good option
    good_metrics = OptionMetrics.calculate(
        stock_price=175.00,
        strike=180.00,
        premium=2.50,
        expiration=expiration,
        delta=0.35
    )
    
    good_option = ScoredOption(
        ticker="AAPL",
        strike=180.00,
        expiration=expiration,
        premium=2.50,
        delta=0.35,
        metrics=good_metrics,
        score=72.0,
        rank=1
    )
    
    # Test recommendation engine
    for profile in [RiskProfile.CONSERVATIVE, RiskProfile.MODERATE, RiskProfile.AGGRESSIVE]:
        print(f"\n{'='*70}")
        print(f"{profile.value.upper()} Profile Recommendation")
        print(f"{'='*70}")
        
        engine = RecommendationEngine(profile)
        rec = engine.generate_recommendation("AAPL", good_option, [good_option])
        
        print(f"\nAction: {rec.action.value}")
        print(f"Confidence: {rec.confidence}")
        print(f"\nExplanation:\n{rec.explanation}")
        
        if rec.warnings:
            print(f"\nWarnings:")
            for warning in rec.warnings:
                print(f"  - {warning}")

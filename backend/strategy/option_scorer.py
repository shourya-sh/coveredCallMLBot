"""
Option Scoring and Ranking Engine

Scores and ranks option contracts based on multiple factors:
- Annualized return potential
- Assignment risk (via delta)
- Downside protection
- Risk profile alignment

The scoring function produces a single numeric score for each contract,
allowing us to rank and select the optimal covered call.
"""

from typing import List
import numpy as np

from models.options import OptionMetrics, ScoredOption
from models.risk_profiles import RiskProfile, RiskProfileConfig, get_risk_profile_config
from data_ingestion.options_scraper import OptionContract


class OptionScorer:
    """
    Scores and ranks option contracts for covered call strategies
    
    Scoring Formula:
    ----------------
    score = w1 * return_score + w2 * safety_score + w3 * profile_fit_score
    
    Where:
    - return_score: Normalized annualized return (higher is better)
    - safety_score: Inverse of assignment risk (lower delta is safer)
    - profile_fit_score: How well the option fits the user's risk profile
    
    Weights (w1, w2, w3) vary by risk profile:
    - Conservative: Heavy weight on safety
    - Moderate: Balanced weights
    - Aggressive: Heavy weight on returns
    """
    
    def __init__(self, risk_profile: RiskProfile):
        """
        Initialize scorer with risk profile
        
        Args:
            risk_profile: User's risk tolerance
        """
        self.risk_profile = risk_profile
        self.config = get_risk_profile_config(risk_profile)
        
        # Set scoring weights based on risk profile
        self.weights = self._get_weights()
    
    def score_contracts(
        self,
        contracts: List[OptionContract],
        stock_price: float
    ) -> List[ScoredOption]:
        """
        Score and rank all contracts
        
        Args:
            contracts: List of option contracts to evaluate
            stock_price: Current stock price
            
        Returns:
            List of ScoredOption objects, sorted by score (best first)
        """
        if not contracts:
            return []
        
        scored_options = []
        
        for contract in contracts:
            # Calculate metrics for this contract
            metrics = OptionMetrics.calculate(
                stock_price=stock_price,
                strike=contract.strike,
                premium=contract.mid_price,
                expiration=contract.expiration,
                delta=contract.delta
            )
            
            # Calculate composite score
            score = self._calculate_score(contract, metrics)
            
            scored_options.append(ScoredOption(
                ticker=contract.ticker,
                strike=contract.strike,
                expiration=contract.expiration,
                premium=contract.mid_price,
                delta=contract.delta,
                metrics=metrics,
                score=score
            ))
        
        # Sort by score (descending) and assign ranks
        scored_options.sort(key=lambda x: x.score, reverse=True)
        for rank, option in enumerate(scored_options, start=1):
            option.rank = rank
        
        return scored_options
    
    def _calculate_score(
        self,
        contract: OptionContract,
        metrics: OptionMetrics
    ) -> float:
        """
        Calculate composite score for a contract
        
        Score = w1*return + w2*safety + w3*profile_fit
        
        Args:
            contract: Option contract
            metrics: Calculated metrics
            
        Returns:
            Composite score (0-100 scale)
        """
        # Component 1: Return Score (0-100)
        # Normalize annualized return to 0-100 scale
        # Assume max return of 50% for normalization
        return_score = min(100, (metrics.annualized_return / 50.0) * 100)
        
        # Component 2: Safety Score (0-100)
        # Lower delta = safer = higher score
        # Inverse relationship: safety = 100 * (1 - delta)
        if contract.delta is not None:
            safety_score = 100 * (1 - contract.delta)
        else:
            # If no delta available, assume moderate risk
            safety_score = 50
        
        # Component 3: Profile Fit Score (0-100)
        # How well does this contract match the user's risk profile?
        profile_fit = self._calculate_profile_fit(contract, metrics)
        
        # Weighted composite score
        score = (
            self.weights['return'] * return_score +
            self.weights['safety'] * safety_score +
            self.weights['profile_fit'] * profile_fit
        )
        
        return score
    
    def _calculate_profile_fit(
        self,
        contract: OptionContract,
        metrics: OptionMetrics
    ) -> float:
        """
        Calculate how well the contract fits the user's risk profile
        
        Checks:
        - Delta within profile range?
        - DTE within profile range?
        - Premium yield meets minimum?
        
        Args:
            contract: Option contract
            metrics: Calculated metrics
            
        Returns:
            Fit score (0-100)
        """
        score = 0
        
        # Check delta range (40 points)
        if contract.delta is not None:
            delta_min, delta_max = self.config.delta_range
            if delta_min <= contract.delta <= delta_max:
                # Perfect fit
                score += 40
            else:
                # Partial credit based on how close
                if contract.delta < delta_min:
                    distance = delta_min - contract.delta
                elif contract.delta > delta_max:
                    distance = contract.delta - delta_max
                else:
                    distance = 0
                
                # Penalize distance from range
                score += max(0, 40 - (distance * 100))
        else:
            # No delta: assume moderate fit
            score += 20
        
        # Check DTE range (40 points)
        dte_min, dte_max = self.config.dte_range
        if dte_min <= metrics.days_to_expiration <= dte_max:
            score += 40
        else:
            # Partial credit
            if metrics.days_to_expiration < dte_min:
                distance = dte_min - metrics.days_to_expiration
            else:
                distance = metrics.days_to_expiration - dte_max
            
            score += max(0, 40 - (distance / 10))
        
        # Check minimum premium yield (20 points)
        if metrics.premium_yield >= (self.config.min_premium_yield * 100):
            score += 20
        else:
            # Partial credit
            ratio = metrics.premium_yield / (self.config.min_premium_yield * 100)
            score += 20 * ratio
        
        return min(100, score)
    
    def _get_weights(self) -> dict:
        """
        Get scoring weights based on risk profile
        
        Returns:
            Dictionary with weights for each score component
        """
        if self.risk_profile == RiskProfile.CONSERVATIVE:
            return {
                'return': 0.2,      # 20% weight on returns
                'safety': 0.5,      # 50% weight on safety
                'profile_fit': 0.3  # 30% weight on profile fit
            }
        elif self.risk_profile == RiskProfile.MODERATE:
            return {
                'return': 0.4,
                'safety': 0.3,
                'profile_fit': 0.3
            }
        else:  # AGGRESSIVE
            return {
                'return': 0.5,      # 50% weight on returns
                'safety': 0.2,      # 20% weight on safety
                'profile_fit': 0.3
            }
    
    def get_best_contract(
        self,
        contracts: List[OptionContract],
        stock_price: float
    ) -> ScoredOption:
        """
        Get the single best contract based on scoring
        
        Args:
            contracts: List of contracts to evaluate
            stock_price: Current stock price
            
        Returns:
            Best ScoredOption (rank 1)
            
        Raises:
            ValueError: If no contracts provided
        """
        scored = self.score_contracts(contracts, stock_price)
        
        if not scored:
            raise ValueError("No contracts available to score")
        
        return scored[0]  # First item is highest scored


# Example usage
if __name__ == "__main__":
    from datetime import datetime, timedelta
    from data_ingestion.options_scraper import OptionContract
    
    # Create sample contracts
    stock_price = 175.00
    expiration = datetime.now() + timedelta(days=30)
    
    contracts = [
        OptionContract(
            ticker="AAPL",
            contract_type="CALL",
            strike=180.0,
            expiration=expiration,
            bid=2.40,
            ask=2.60,
            delta=0.35
        ),
        OptionContract(
            ticker="AAPL",
            contract_type="CALL",
            strike=185.0,
            expiration=expiration,
            bid=1.20,
            ask=1.40,
            delta=0.20
        ),
        OptionContract(
            ticker="AAPL",
            contract_type="CALL",
            strike=177.5,
            expiration=expiration,
            bid=3.50,
            ask=3.70,
            delta=0.50
        ),
    ]
    
    # Test with different risk profiles
    for profile in [RiskProfile.CONSERVATIVE, RiskProfile.MODERATE, RiskProfile.AGGRESSIVE]:
        print(f"\n{'='*60}")
        print(f"{profile.value.upper()} Profile")
        print(f"{'='*60}")
        
        scorer = OptionScorer(profile)
        scored = scorer.score_contracts(contracts, stock_price)
        
        for opt in scored:
            print(f"\nRank {opt.rank}: Strike ${opt.strike}")
            print(f"  Score: {opt.score:.2f}")
            print(f"  Premium: ${opt.premium:.2f}")
            print(f"  Delta: {opt.delta:.2f}")
            print(f"  Annualized Return: {opt.metrics.annualized_return:.1f}%")

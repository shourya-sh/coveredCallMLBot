"""
Risk Profile Definitions

Defines three risk profiles for covered call strategies:
- Conservative: Low risk, income stability
- Moderate: Balanced risk/reward
- Aggressive: Maximum premium, accept higher assignment risk
"""

from enum import Enum
from dataclasses import dataclass
from typing import Tuple


class RiskProfile(str, Enum):
    """Risk profile selection for covered call strategies"""
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


@dataclass
class RiskProfileConfig:
    """
    Configuration parameters for a risk profile
    
    Attributes:
        delta_range: (min, max) delta for option selection
        dte_range: (min, max) days to expiration
        min_premium_yield: Minimum acceptable premium as % of stock price
        max_assignment_risk: Maximum acceptable assignment probability
        description: Human-readable explanation
    """
    delta_range: Tuple[float, float]
    dte_range: Tuple[int, int]
    min_premium_yield: float
    max_assignment_risk: float
    description: str


# Risk Profile Definitions
RISK_PROFILES = {
    RiskProfile.CONSERVATIVE: RiskProfileConfig(
        delta_range=(0.15, 0.30),
        dte_range=(30, 60),
        min_premium_yield=0.005,  # 0.5% minimum
        max_assignment_risk=0.30,  # 30% max probability
        description="Low assignment risk with stable income. Targets out-of-the-money options with longer expiration periods."
    ),
    
    RiskProfile.MODERATE: RiskProfileConfig(
        delta_range=(0.30, 0.45),
        dte_range=(21, 45),
        min_premium_yield=0.01,  # 1.0% minimum
        max_assignment_risk=0.50,  # 50% max probability
        description="Balanced approach between income and assignment risk. Suitable for most investors."
    ),
    
    RiskProfile.AGGRESSIVE: RiskProfileConfig(
        delta_range=(0.45, 0.65),
        dte_range=(7, 30),
        min_premium_yield=0.02,  # 2.0% minimum
        max_assignment_risk=0.70,  # 70% max probability
        description="Maximum premium generation with higher assignment risk. Targets near-the-money options with shorter expirations."
    ),
}


def get_risk_profile_config(profile: RiskProfile) -> RiskProfileConfig:
    """
    Get configuration for a risk profile
    
    Args:
        profile: Risk profile enum value
        
    Returns:
        RiskProfileConfig with parameters for the profile
    """
    return RISK_PROFILES[profile]


def validate_risk_profile(profile: str) -> RiskProfile:
    """
    Validate and convert string to RiskProfile enum
    
    Args:
        profile: Risk profile string (case-insensitive)
        
    Returns:
        RiskProfile enum value
        
    Raises:
        ValueError: If profile is invalid
    """
    try:
        return RiskProfile(profile.lower())
    except ValueError:
        valid = [p.value for p in RiskProfile]
        raise ValueError(f"Invalid risk profile '{profile}'. Valid options: {valid}")


# Example usage
if __name__ == "__main__":
    for profile in RiskProfile:
        config = get_risk_profile_config(profile)
        print(f"\n{profile.value.upper()}")
        print(f"  Delta Range: {config.delta_range[0]:.2f} - {config.delta_range[1]:.2f}")
        print(f"  DTE Range: {config.dte_range[0]} - {config.dte_range[1]} days")
        print(f"  Min Premium Yield: {config.min_premium_yield:.1%}")
        print(f"  Max Assignment Risk: {config.max_assignment_risk:.0%}")
        print(f"  Description: {config.description}")

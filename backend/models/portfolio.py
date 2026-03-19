"""
Portfolio and Position Models

Defines data structures for user portfolios and stock positions.
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from .risk_profiles import RiskProfile, validate_risk_profile


class Position(BaseModel):
    """
    Individual stock position in portfolio
    
    Attributes:
        ticker: Stock symbol (e.g., "AAPL")
        shares: Number of shares owned
        cost_basis: Average cost per share (optional, for profit calculations)
    """
    ticker: str = Field(..., description="Stock ticker symbol")
    shares: int = Field(..., gt=0, description="Number of shares owned")
    cost_basis: Optional[float] = Field(None, ge=0, description="Average cost per share")
    
    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, v: str) -> str:
        """Ensure ticker is uppercase and non-empty"""
        if not v or not v.strip():
            raise ValueError("Ticker cannot be empty")
        return v.strip().upper()
    
    @property
    def is_covered_call_eligible(self) -> bool:
        """
        Check if position is eligible for covered calls
        
        Covered calls require at least 100 shares (1 contract = 100 shares)
        """
        return self.shares >= 100
    
    @property
    def max_contracts(self) -> int:
        """Calculate maximum number of covered call contracts possible"""
        return self.shares // 100
    
    def __repr__(self) -> str:
        return f"Position(ticker={self.ticker}, shares={self.shares}, contracts={self.max_contracts})"


class Portfolio(BaseModel):
    """
    User's stock portfolio
    
    Attributes:
        positions: List of stock positions
        risk_profile: User's risk tolerance (conservative/moderate/aggressive)
        created_at: Portfolio creation timestamp
    """
    positions: List[Position] = Field(..., min_length=1, description="List of positions")
    risk_profile: RiskProfile = Field(
        default=RiskProfile.MODERATE,
        description="Risk tolerance for covered call selection"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    
    @field_validator("risk_profile", mode="before")
    @classmethod
    def validate_risk_profile_field(cls, v):
        """Convert string to RiskProfile enum"""
        if isinstance(v, str):
            return validate_risk_profile(v)
        return v
    
    @property
    def eligible_positions(self) -> List[Position]:
        """Filter positions eligible for covered calls (≥100 shares)"""
        return [pos for pos in self.positions if pos.is_covered_call_eligible]
    
    @property
    def total_positions(self) -> int:
        """Total number of positions in portfolio"""
        return len(self.positions)
    
    @property
    def eligible_count(self) -> int:
        """Number of positions eligible for covered calls"""
        return len(self.eligible_positions)
    
    def get_position(self, ticker: str) -> Optional[Position]:
        """
        Get position by ticker symbol
        
        Args:
            ticker: Stock symbol to find
            
        Returns:
            Position if found, None otherwise
        """
        ticker = ticker.upper()
        for pos in self.positions:
            if pos.ticker == ticker:
                return pos
        return None
    
    def __repr__(self) -> str:
        return f"Portfolio(positions={self.total_positions}, eligible={self.eligible_count}, risk={self.risk_profile.value})"


class EligiblePosition(BaseModel):
    """
    Position analysis result with eligibility info
    
    Used in API responses to show which positions can sell covered calls
    """
    ticker: str
    shares: int
    cost_basis: Optional[float] = None
    current_price: float
    contracts_available: int
    is_eligible: bool
    reason: Optional[str] = None  # If not eligible, why?
    
    @property
    def position_value(self) -> float:
        """Calculate current position value"""
        return self.current_price * self.shares
    
    @property
    def unrealized_pnl(self) -> Optional[float]:
        """Calculate unrealized P&L if cost basis is available"""
        if self.cost_basis is not None:
            return (self.current_price - self.cost_basis) * self.shares
        return None
    
    @property
    def unrealized_pnl_percent(self) -> Optional[float]:
        """Calculate unrealized P&L as percentage"""
        if self.cost_basis is not None and self.cost_basis > 0:
            return ((self.current_price - self.cost_basis) / self.cost_basis) * 100
        return None


class PortfolioSummary(BaseModel):
    """
    Summary of portfolio analysis
    
    Used as API response for portfolio evaluation
    """
    eligible_positions: List[EligiblePosition]
    total_positions: int
    eligible_count: int
    risk_profile: RiskProfile
    analysis_timestamp: datetime = Field(default_factory=datetime.now)
    
    @property
    def total_value(self) -> float:
        """Calculate total portfolio value"""
        return sum(pos.position_value for pos in self.eligible_positions)


# Example usage
if __name__ == "__main__":
    # Create sample portfolio
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=200, cost_basis=150.00),
            Position(ticker="MSFT", shares=150, cost_basis=300.00),
            Position(ticker="GOOGL", shares=50, cost_basis=2500.00),  # Not eligible
            Position(ticker="TSLA", shares=300, cost_basis=200.00),
        ],
        risk_profile=RiskProfile.MODERATE
    )
    
    print(f"Portfolio: {portfolio}")
    print(f"\nEligible positions:")
    for pos in portfolio.eligible_positions:
        print(f"  {pos}")
    
    # Test validation
    try:
        invalid = Portfolio(positions=[])  # Empty positions
    except Exception as e:
        print(f"\nValidation error (expected): {e}")

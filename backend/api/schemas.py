"""
API Request and Response Schemas

Defines the API contracts for frontend consumption.
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

from models.risk_profiles import RiskProfile


# ============================================================================
# REQUEST SCHEMAS
# ============================================================================

class PositionRequest(BaseModel):
    """Individual position in portfolio evaluation request"""
    ticker: str = Field(..., example="AAPL", description="Stock ticker symbol")
    shares: int = Field(..., gt=0, example=200, description="Number of shares owned")
    cost_basis: Optional[float] = Field(None, ge=0, example=150.00, description="Average cost per share")


class PortfolioEvaluationRequest(BaseModel):
    """Request to evaluate entire portfolio"""
    positions: List[PositionRequest] = Field(..., min_length=1, description="List of positions")
    risk_profile: str = Field(
        default="moderate",
        example="moderate",
        description="Risk profile: conservative, moderate, or aggressive"
    )


class CoveredCallRecommendationRequest(BaseModel):
    """Request for covered call recommendation on specific position"""
    ticker: str = Field(..., example="AAPL", description="Stock ticker symbol")
    shares: int = Field(..., gt=0, example=200, description="Number of shares owned")
    cost_basis: Optional[float] = Field(None, ge=0, example=150.00, description="Average cost per share")
    risk_profile: str = Field(
        default="moderate",
        example="moderate",
        description="Risk profile: conservative, moderate, or aggressive"
    )


# ============================================================================
# RESPONSE SCHEMAS
# ============================================================================

class EligiblePositionResponse(BaseModel):
    """Individual position analysis result"""
    ticker: str
    shares: int
    cost_basis: Optional[float]
    current_price: float
    contracts_available: int
    is_eligible: bool
    reason: Optional[str] = None


class PortfolioEvaluationResponse(BaseModel):
    """Response for portfolio evaluation"""
    eligible_positions: List[EligiblePositionResponse]
    total_positions: int
    eligible_count: int
    risk_profile: str
    analysis_timestamp: datetime


class ContractDetailsResponse(BaseModel):
    """Option contract details"""
    strike: float
    expiration: str  # ISO format date
    premium: float
    delta: Optional[float]


class MetricsResponse(BaseModel):
    """Calculated metrics for recommended option"""
    premium_yield: float = Field(..., description="Premium as % of stock price")
    annualized_return: float = Field(..., description="Annualized return %")
    max_profit: float = Field(..., description="Maximum profit per contract")
    downside_protection: float = Field(..., description="% cushion against price drop")
    break_even_price: float = Field(..., description="Stock price where position breaks even")
    assignment_probability: Optional[float] = Field(None, description="Probability of assignment %")
    days_to_expiration: int


class AlternativeContractResponse(BaseModel):
    """Alternative option contract"""
    strike: float
    expiration: str
    premium: float
    score: float


class CoveredCallRecommendationResponse(BaseModel):
    """Response for covered call recommendation"""
    action: str = Field(..., description="SELL or HOLD")
    ticker: str
    risk_profile: str
    
    # Present if action is SELL
    recommended_contract: Optional[ContractDetailsResponse] = None
    metrics: Optional[MetricsResponse] = None
    
    # Human-readable explanation
    explanation: str
    confidence: str = Field(..., description="high, medium, or low")
    
    # Additional context
    alternative_contracts: List[AlternativeContractResponse] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    timestamp: datetime


class HealthCheckResponse(BaseModel):
    """Health check response"""
    status: str = Field(default="healthy")
    timestamp: datetime
    services: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Error response"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime

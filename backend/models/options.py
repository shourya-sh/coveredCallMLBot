"""
Options Contract Models

Extended models for option contracts used in strategy calculations.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class OptionMetrics(BaseModel):
    """
    Calculated metrics for a covered call option contract
    
    All formulas are documented inline.
    """
    # Input data
    stock_price: float
    strike: float
    premium: float  # Mid-price of bid/ask
    expiration: datetime
    delta: Optional[float] = None
    
    # Calculated metrics
    premium_yield: float = Field(..., description="Premium as % of stock price")
    annualized_return: float = Field(..., description="Annualized return %")
    max_profit: float = Field(..., description="Maximum profit per contract")
    downside_protection: float = Field(..., description="% cushion against price drop")
    break_even_price: float = Field(..., description="Stock price where position breaks even")
    assignment_probability: Optional[float] = Field(None, description="Probability of assignment (via delta)")
    days_to_expiration: int = Field(..., description="Days until expiration")
    
    @classmethod
    def calculate(
        cls,
        stock_price: float,
        strike: float,
        premium: float,
        expiration: datetime,
        delta: Optional[float] = None,
        shares: int = 100
    ) -> "OptionMetrics":
        """
        Calculate all metrics for a covered call contract
        
        Formulas:
        ---------
        Premium Yield = (Premium / Stock Price) * 100
        
        Annualized Return = Premium Yield * (365 / DTE)
        
        Max Profit = (Strike - Stock Price + Premium) * Shares
                     If Strike > Stock Price (OTM call)
        
        Downside Protection = Premium Yield
                              (Premium received offsets price drop)
        
        Break-Even Price = Stock Price - Premium
                           (Price where premium offsets loss)
        
        Assignment Probability ≈ Delta
                                 (Delta is proxy for ITM probability)
        
        Args:
            stock_price: Current stock price
            strike: Option strike price
            premium: Option premium (mid-price)
            expiration: Expiration date
            delta: Option delta (if available)
            shares: Number of shares per contract (typically 100)
            
        Returns:
            OptionMetrics object with all calculated values
        """
        # Days to expiration
        dte = max(1, (expiration - datetime.now()).days)
        
        # Premium yield: Premium as % of stock price
        # Formula: (Premium / Stock Price) * 100
        premium_yield = (premium / stock_price) * 100
        
        # Annualized return: Extrapolate premium yield to 1 year
        # Formula: Premium Yield * (365 / DTE)
        annualized_return = premium_yield * (365 / dte)
        
        # Max profit: Maximum gain if stock closes at or above strike
        # Formula: (Strike - Stock Price) * Shares + (Premium * Shares)
        # Simplified: ((Strike - Stock Price) + Premium) * Shares
        if strike >= stock_price:
            # OTM call: Gain from stock appreciation + premium
            max_profit = ((strike - stock_price) + premium) * shares
        else:
            # ITM call: Premium only (stock called away below current price)
            max_profit = premium * shares
        
        # Downside protection: How much stock can drop before losing money
        # Formula: Premium received offsets price drop dollar-for-dollar
        # As percentage: (Premium / Stock Price) * 100
        downside_protection = premium_yield
        
        # Break-even price: Stock price where total position breaks even
        # Formula: Purchase Price - Premium Received
        # Since we're calculating from current price:
        break_even_price = stock_price - premium
        
        # Assignment probability: Use delta as proxy
        # Delta represents approximate probability of option finishing ITM
        assignment_probability = delta if delta else None
        
        return cls(
            stock_price=stock_price,
            strike=strike,
            premium=premium,
            expiration=expiration,
            delta=delta,
            premium_yield=premium_yield,
            annualized_return=annualized_return,
            max_profit=max_profit,
            downside_protection=downside_protection,
            break_even_price=break_even_price,
            assignment_probability=assignment_probability,
            days_to_expiration=dte
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API responses"""
        return {
            "premium_yield": round(self.premium_yield, 2),
            "annualized_return": round(self.annualized_return, 2),
            "max_profit": round(self.max_profit, 2),
            "downside_protection": round(self.downside_protection, 2),
            "break_even_price": round(self.break_even_price, 2),
            "assignment_probability": round(self.assignment_probability * 100, 1) if self.assignment_probability else None,
            "days_to_expiration": self.days_to_expiration
        }


class ScoredOption(BaseModel):
    """
    Option contract with calculated score
    
    Used for ranking and selecting best contracts
    """
    ticker: str
    strike: float
    expiration: datetime
    premium: float
    delta: Optional[float] = None
    metrics: OptionMetrics
    score: float = Field(..., description="Composite score (higher is better)")
    rank: int = Field(default=0, description="Rank among all options (1 = best)")
    
    def __repr__(self) -> str:
        return f"ScoredOption(strike={self.strike}, exp={self.expiration.date()}, score={self.score:.2f}, rank={self.rank})"


# Example usage
if __name__ == "__main__":
    from datetime import timedelta
    
    # Example covered call scenario
    stock_price = 175.00
    strike = 180.00
    premium = 2.50
    expiration = datetime.now() + timedelta(days=30)
    delta = 0.35
    
    metrics = OptionMetrics.calculate(
        stock_price=stock_price,
        strike=strike,
        premium=premium,
        expiration=expiration,
        delta=delta
    )
    
    print("Covered Call Metrics")
    print("=" * 50)
    print(f"Stock Price: ${metrics.stock_price:.2f}")
    print(f"Strike Price: ${metrics.strike:.2f}")
    print(f"Premium: ${metrics.premium:.2f}")
    print(f"Days to Expiration: {metrics.days_to_expiration}")
    print(f"\nCalculated Metrics:")
    print(f"  Premium Yield: {metrics.premium_yield:.2f}%")
    print(f"  Annualized Return: {metrics.annualized_return:.2f}%")
    print(f"  Max Profit: ${metrics.max_profit:.2f}")
    print(f"  Downside Protection: {metrics.downside_protection:.2f}%")
    print(f"  Break-Even Price: ${metrics.break_even_price:.2f}")
    if metrics.assignment_probability:
        print(f"  Assignment Probability: {metrics.assignment_probability * 100:.1f}%")

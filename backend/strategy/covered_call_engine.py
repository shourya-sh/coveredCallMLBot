"""
Covered Call Strategy Engine

Core logic for evaluating covered call opportunities:
- Filters valid contracts based on risk profile
- Coordinates data fetching
- Orchestrates scoring and ranking
"""

from typing import List, Optional, Dict
from datetime import datetime

from models.portfolio import Position
from models.risk_profiles import RiskProfile, get_risk_profile_config
from models.options import ScoredOption
from data_ingestion.twelve_data_client import TwelveDataClient
from data_ingestion.options_scraper import YahooFinanceOptionsScraper, OptionContract
from strategy.option_scorer import OptionScorer


class CoveredCallEngine:
    """
    Main strategy engine for covered call analysis
    
    Workflow:
    1. Validate position is eligible (≥100 shares)
    2. Fetch current stock price
    3. Fetch option chains for multiple expirations
    4. Filter contracts based on risk profile
    5. Score and rank filtered contracts
    6. Return best recommendation
    """
    
    def __init__(
        self,
        stock_client: TwelveDataClient,
        options_scraper: YahooFinanceOptionsScraper
    ):
        """
        Initialize engine with data sources
        
        Args:
            stock_client: Client for stock price data
            options_scraper: Scraper for options chains
        """
        self.stock_client = stock_client
        self.options_scraper = options_scraper
    
    def analyze_position(
        self,
        position: Position,
        risk_profile: RiskProfile
    ) -> Optional[ScoredOption]:
        """
        Analyze a position and recommend the best covered call
        
        Args:
            position: Stock position to analyze
            risk_profile: User's risk tolerance
            
        Returns:
            Best ScoredOption, or None if no suitable contracts found
        """
        # Validate eligibility
        if not position.is_covered_call_eligible:
            return None
        
        # Fetch current stock price
        try:
            stock_price_data = self.stock_client.get_current_price(position.ticker)
            stock_price = stock_price_data.price
        except Exception as e:
            print(f"Error fetching price for {position.ticker}: {e}")
            return None
        
        # Fetch option chains
        try:
            option_chains = self.options_scraper.get_all_expirations(
                position.ticker,
                max_expirations=6  # Fetch next 6 expirations
            )
        except Exception as e:
            print(f"Error fetching options for {position.ticker}: {e}")
            return None
        
        if not option_chains:
            return None
        
        # Flatten all contracts from multiple expirations
        all_contracts = []
        for expiration, contracts in option_chains.items():
            all_contracts.extend(contracts)
        
        # Filter contracts based on risk profile
        filtered = self._filter_contracts(all_contracts, stock_price, risk_profile)
        
        if not filtered:
            return None
        
        # Score and rank contracts
        scorer = OptionScorer(risk_profile)
        scored_contracts = scorer.score_contracts(filtered, stock_price)
        
        # Return best contract
        return scored_contracts[0] if scored_contracts else None
    
    def _filter_contracts(
        self,
        contracts: List[OptionContract],
        stock_price: float,
        risk_profile: RiskProfile
    ) -> List[OptionContract]:
        """
        Filter contracts based on risk profile criteria
        
        Filters:
        - Delta within profile range
        - DTE within profile range
        - Strike >= current price (OTM or ATM only)
        - Reasonable bid-ask spread
        - Minimum liquidity (volume or open interest)
        
        Args:
            contracts: All available contracts
            stock_price: Current stock price
            risk_profile: User's risk profile
            
        Returns:
            Filtered list of contracts
        """
        config = get_risk_profile_config(risk_profile)
        
        filtered = []
        
        for contract in contracts:
            # Filter 1: Delta range
            if contract.delta is not None:
                if not (config.delta_range[0] <= contract.delta <= config.delta_range[1]):
                    continue
            
            # Filter 2: DTE range
            dte = contract.days_to_expiration
            if not (config.dte_range[0] <= dte <= config.dte_range[1]):
                continue
            
            # Filter 3: Strike price (covered calls should be OTM or ATM)
            # We want strike >= stock_price for income generation
            # Allow slight ITM for aggressive profile
            if risk_profile == RiskProfile.AGGRESSIVE:
                # Allow up to 5% ITM
                min_strike = stock_price * 0.95
            else:
                # Only OTM or ATM
                min_strike = stock_price
            
            if contract.strike < min_strike:
                continue
            
            # Filter 4: Bid-ask spread (quality check)
            # Reject if spread > 30% of mid price (illiquid)
            if contract.bid > 0:
                spread_pct = (contract.ask - contract.bid) / contract.mid_price
                if spread_pct > 0.30:
                    continue
            
            # Filter 5: Minimum premium
            # Must meet profile's minimum yield requirement
            premium_yield = (contract.mid_price / stock_price)
            if premium_yield < config.min_premium_yield:
                continue
            
            # Filter 6: Minimum liquidity
            # Ensure contract has some trading activity
            if contract.volume == 0 and contract.open_interest < 10:
                continue
            
            filtered.append(contract)
        
        return filtered
    
    def get_eligible_contracts_count(
        self,
        position: Position,
        risk_profile: RiskProfile
    ) -> int:
        """
        Count how many eligible contracts are available for a position
        
        Useful for API responses showing opportunity count
        
        Args:
            position: Stock position
            risk_profile: Risk profile
            
        Returns:
            Number of eligible contracts
        """
        try:
            stock_price = self.stock_client.get_current_price(position.ticker).price
            option_chains = self.options_scraper.get_all_expirations(position.ticker, max_expirations=3)
            
            all_contracts = []
            for contracts in option_chains.values():
                all_contracts.extend(contracts)
            
            filtered = self._filter_contracts(all_contracts, stock_price, risk_profile)
            return len(filtered)
            
        except Exception:
            return 0


# Example usage
if __name__ == "__main__":
    from data_ingestion import get_twelve_data_client, get_options_scraper
    
    # NOTE: Requires TWELVE_DATA_API_KEY environment variable
    
    try:
        # Initialize clients
        with get_twelve_data_client() as stock_client:
            options_scraper = get_options_scraper()
            
            # Create engine
            engine = CoveredCallEngine(stock_client, options_scraper)
            
            # Test position
            position = Position(
                ticker="AAPL",
                shares=200,
                cost_basis=150.00
            )
            
            # Analyze for moderate profile
            print(f"Analyzing {position.ticker} for covered call opportunity...\n")
            
            best_option = engine.analyze_position(position, RiskProfile.MODERATE)
            
            if best_option:
                print(f"Recommendation: SELL covered call")
                print(f"  Strike: ${best_option.strike}")
                print(f"  Expiration: {best_option.expiration.strftime('%Y-%m-%d')}")
                print(f"  Premium: ${best_option.premium:.2f}")
                print(f"  Score: {best_option.score:.2f}")
                print(f"\nMetrics:")
                print(f"  Premium Yield: {best_option.metrics.premium_yield:.2f}%")
                print(f"  Annualized Return: {best_option.metrics.annualized_return:.2f}%")
                print(f"  Max Profit: ${best_option.metrics.max_profit:.2f}")
                print(f"  Break-Even: ${best_option.metrics.break_even_price:.2f}")
            else:
                print("No suitable covered call contracts found")
                
    except Exception as e:
        print(f"Error: {e}")

"""
Demo Mode

Provides mock data for testing and development without requiring
external API connections.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Optional
import random

from data_ingestion.options_scraper import OptionContract
from data_ingestion.twelve_data_client import StockPrice, OHLCData, VolatilityMetrics


# Demo stock data
DEMO_STOCKS = {
    "AAPL": {"price": 175.50, "hv": 0.22},
    "MSFT": {"price": 420.25, "hv": 0.19},
    "GOOGL": {"price": 180.75, "hv": 0.25},
    "TSLA": {"price": 248.50, "hv": 0.45},
    "NVDA": {"price": 890.25, "hv": 0.38},
    "META": {"price": 525.00, "hv": 0.28},
    "AMZN": {"price": 195.50, "hv": 0.24},
    "AMD": {"price": 178.25, "hv": 0.35},
}


class DemoTwelveDataClient:
    """Demo client for testing without API key"""
    
    def get_current_price(self, ticker: str) -> StockPrice:
        """Return mock current price"""
        ticker = ticker.upper()
        
        if ticker in DEMO_STOCKS:
            price = DEMO_STOCKS[ticker]["price"]
        else:
            # Generate random price for unknown tickers
            price = round(random.uniform(50, 500), 2)
        
        # Add small random variation
        price *= random.uniform(0.99, 1.01)
        
        return StockPrice(
            ticker=ticker,
            price=round(price, 2),
            timestamp=datetime.now()
        )
    
    def get_ohlc_data(
        self,
        ticker: str,
        interval: str = "1day",
        outputsize: int = 30
    ) -> List[OHLCData]:
        """Return mock OHLC data"""
        ticker = ticker.upper()
        base_price = DEMO_STOCKS.get(ticker, {}).get("price", 150.0)
        
        ohlc_list = []
        current_price = base_price
        
        for i in range(outputsize):
            date = datetime.now() - timedelta(days=i)
            
            # Generate realistic OHLC
            daily_change = random.uniform(-0.03, 0.03)
            open_price = current_price
            close_price = open_price * (1 + daily_change)
            high_price = max(open_price, close_price) * random.uniform(1.0, 1.02)
            low_price = min(open_price, close_price) * random.uniform(0.98, 1.0)
            volume = random.randint(10_000_000, 100_000_000)
            
            ohlc_list.append(OHLCData(
                ticker=ticker,
                open=round(open_price, 2),
                high=round(high_price, 2),
                low=round(low_price, 2),
                close=round(close_price, 2),
                volume=volume,
                date=date
            ))
            
            current_price = close_price
        
        return ohlc_list
    
    def calculate_historical_volatility(
        self,
        ticker: str,
        period: int = 30
    ) -> VolatilityMetrics:
        """Return mock volatility metrics"""
        ticker = ticker.upper()
        hv = DEMO_STOCKS.get(ticker, {}).get("hv", 0.25)
        
        # Add small random variation
        hv *= random.uniform(0.95, 1.05)
        
        return VolatilityMetrics(
            ticker=ticker,
            historical_volatility=hv,
            avg_true_range=hv * 100 * random.uniform(0.8, 1.2),
            calculation_period=period
        )


class DemoOptionsScraper:
    """Demo scraper for testing without web scraping"""
    
    def get_expiration_dates(self, ticker: str) -> List[datetime]:
        """Return mock expiration dates (next 6 monthly expirations)"""
        expirations = []
        current = datetime.now()
        
        for month_offset in range(1, 7):
            # Third Friday of each month
            target_month = current.month + month_offset
            target_year = current.year + (target_month - 1) // 12
            target_month = ((target_month - 1) % 12) + 1
            
            first_day = datetime(target_year, target_month, 1)
            first_friday = (4 - first_day.weekday()) % 7 + 1
            third_friday = first_friday + 14
            
            exp_date = datetime(target_year, target_month, third_friday)
            expirations.append(exp_date)
        
        return expirations
    
    def get_option_chain(
        self,
        ticker: str,
        expiration_date: Optional[datetime] = None
    ) -> List[OptionContract]:
        """Return mock option chain for a single expiration"""
        ticker = ticker.upper()
        
        expirations = self.get_expiration_dates(ticker)
        if expiration_date:
            target_exp = min(expirations, key=lambda d: abs(d - expiration_date))
        else:
            target_exp = expirations[0]
        
        return self._generate_option_chain(ticker, target_exp)
    
    def get_all_expirations(
        self,
        ticker: str,
        max_expirations: int = 6
    ) -> Dict[datetime, List[OptionContract]]:
        """Return mock option chains for multiple expirations"""
        ticker = ticker.upper()
        expirations = self.get_expiration_dates(ticker)[:max_expirations]
        
        result = {}
        for exp in expirations:
            result[exp] = self._generate_option_chain(ticker, exp)
        
        return result
    
    def _generate_option_chain(
        self,
        ticker: str,
        expiration: datetime
    ) -> List[OptionContract]:
        """Generate realistic mock option chain"""
        base_price = DEMO_STOCKS.get(ticker, {}).get("price", 150.0)
        hv = DEMO_STOCKS.get(ticker, {}).get("hv", 0.25)
        
        dte = (expiration - datetime.now()).days
        
        contracts = []
        
        # Generate strikes from 90% to 120% of current price
        min_strike = round(base_price * 0.90 / 2.5) * 2.5
        max_strike = round(base_price * 1.20 / 2.5) * 2.5
        
        strike = min_strike
        while strike <= max_strike:
            # Calculate theoretical option value (simplified Black-Scholes approximation)
            moneyness = (strike - base_price) / base_price
            time_factor = (dte / 365) ** 0.5
            
            # ATM options have ~0.5 delta, OTM options have lower delta
            if strike >= base_price:
                delta = max(0.05, 0.50 - (moneyness / (hv * time_factor * 2)))
            else:
                delta = min(0.95, 0.50 + abs(moneyness) / (hv * time_factor * 2))
            
            # Premium calculation (simplified)
            iv = hv * random.uniform(1.0, 1.3)  # IV usually higher than HV
            time_value = base_price * iv * time_factor * 0.4 * delta
            intrinsic_value = max(0, base_price - strike) if strike < base_price else 0
            premium = intrinsic_value + time_value
            
            # Bid-ask spread (narrower for liquid options)
            spread = premium * random.uniform(0.02, 0.10)
            bid = max(0.01, premium - spread / 2)
            ask = premium + spread / 2
            
            contracts.append(OptionContract(
                ticker=ticker,
                contract_type="CALL",
                strike=strike,
                expiration=expiration,
                bid=round(bid, 2),
                ask=round(ask, 2),
                last=round(premium, 2),
                volume=random.randint(100, 10000),
                open_interest=random.randint(500, 50000),
                implied_volatility=round(iv, 4),
                delta=round(delta, 3)
            ))
            
            strike += 2.5
        
        return contracts


# Factory functions for demo mode
def get_demo_stock_client() -> DemoTwelveDataClient:
    """Get demo stock client"""
    return DemoTwelveDataClient()


def get_demo_options_scraper() -> DemoOptionsScraper:
    """Get demo options scraper"""
    return DemoOptionsScraper()


# Example usage
if __name__ == "__main__":
    print("Demo Mode - Testing with mock data")
    print("=" * 60)
    
    stock_client = get_demo_stock_client()
    options_scraper = get_demo_options_scraper()
    
    for ticker in ["AAPL", "TSLA", "NVDA"]:
        print(f"\n{ticker}")
        print("-" * 40)
        
        # Get price
        price = stock_client.get_current_price(ticker)
        print(f"Price: ${price.price:.2f}")
        
        # Get volatility
        vol = stock_client.calculate_historical_volatility(ticker)
        print(f"HV (30d): {vol.historical_volatility:.1%}")
        
        # Get option chain
        chains = options_scraper.get_all_expirations(ticker, max_expirations=2)
        for exp, contracts in chains.items():
            print(f"\n  Expiration: {exp.strftime('%Y-%m-%d')}")
            print(f"  Contracts: {len(contracts)}")
            
            # Show a few contracts
            for contract in contracts[:3]:
                print(f"    Strike ${contract.strike}: Bid ${contract.bid:.2f} / Ask ${contract.ask:.2f}, Δ={contract.delta:.2f}")

"""
Twelve Data API Client

Fetches stock price data, OHLC, and volatility metrics.
Documentation: https://twelvedata.com/docs
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass

import httpx
from pydantic import BaseModel


class StockPrice(BaseModel):
    """Current stock price data"""
    ticker: str
    price: float
    timestamp: datetime
    currency: str = "USD"


class OHLCData(BaseModel):
    """OHLC candlestick data"""
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    date: datetime


class VolatilityMetrics(BaseModel):
    """Volatility calculations"""
    ticker: str
    historical_volatility: float  # Annualized HV
    avg_true_range: float  # ATR
    calculation_period: int = 30  # Days used for calculation


@dataclass
class TwelveDataConfig:
    """Configuration for Twelve Data API"""
    api_key: str
    base_url: str = "https://api.twelvedata.com"
    timeout: int = 10
    max_retries: int = 3


class TwelveDataClient:
    """
    Client for Twelve Data API
    
    Provides methods to fetch:
    - Real-time stock prices
    - Historical OHLC data
    - Volatility proxies (using historical price data)
    """
    
    def __init__(self, config: TwelveDataConfig):
        self.config = config
        self.client = httpx.Client(timeout=config.timeout)
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()
    
    def get_current_price(self, ticker: str) -> StockPrice:
        """
        Fetch current stock price
        
        Args:
            ticker: Stock symbol (e.g., "AAPL")
            
        Returns:
            StockPrice object with current price data
            
        Raises:
            httpx.HTTPError: If API request fails
            ValueError: If response is invalid
        """
        url = f"{self.config.base_url}/price"
        params = {
            "symbol": ticker,
            "apikey": self.config.api_key
        }
        
        response = self._make_request(url, params)
        
        # Response format: {"price": "175.43"}
        if "price" not in response:
            raise ValueError(f"Invalid response for {ticker}: {response}")
        
        return StockPrice(
            ticker=ticker,
            price=float(response["price"]),
            timestamp=datetime.now()
        )
    
    def get_ohlc_data(
        self,
        ticker: str,
        interval: str = "1day",
        outputsize: int = 30
    ) -> List[OHLCData]:
        """
        Fetch historical OHLC data
        
        Args:
            ticker: Stock symbol
            interval: Time interval (1day, 1week, etc.)
            outputsize: Number of data points to return
            
        Returns:
            List of OHLCData objects
        """
        url = f"{self.config.base_url}/time_series"
        params = {
            "symbol": ticker,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": self.config.api_key
        }
        
        response = self._make_request(url, params)
        
        # Response format: {"values": [{"datetime": "2024-01-15", "open": "175.00", ...}]}
        if "values" not in response:
            raise ValueError(f"Invalid OHLC response for {ticker}: {response}")
        
        ohlc_list = []
        for item in response["values"]:
            ohlc_list.append(OHLCData(
                ticker=ticker,
                open=float(item["open"]),
                high=float(item["high"]),
                low=float(item["low"]),
                close=float(item["close"]),
                volume=int(item["volume"]),
                date=datetime.strptime(item["datetime"], "%Y-%m-%d")
            ))
        
        return ohlc_list
    
    def calculate_historical_volatility(
        self,
        ticker: str,
        period: int = 30
    ) -> VolatilityMetrics:
        """
        Calculate historical volatility from OHLC data
        
        Uses close-to-close method:
        HV = StdDev(daily_returns) * sqrt(252)
        
        Args:
            ticker: Stock symbol
            period: Number of days for calculation
            
        Returns:
            VolatilityMetrics with annualized HV and ATR
        """
        # Fetch OHLC data
        ohlc_data = self.get_ohlc_data(ticker, interval="1day", outputsize=period + 1)
        
        if len(ohlc_data) < 2:
            raise ValueError(f"Insufficient data for {ticker} volatility calculation")
        
        # Calculate daily returns
        import numpy as np
        
        prices = [item.close for item in reversed(ohlc_data)]
        returns = np.diff(np.log(prices))
        
        # Annualized historical volatility
        # Formula: σ_annual = σ_daily * sqrt(252 trading days)
        hv = np.std(returns) * np.sqrt(252)
        
        # Average True Range (ATR) for volatility proxy
        true_ranges = []
        ohlc_reversed = list(reversed(ohlc_data))
        for i in range(1, len(ohlc_reversed)):
            curr = ohlc_reversed[i]
            prev = ohlc_reversed[i-1]
            
            tr = max(
                curr.high - curr.low,
                abs(curr.high - prev.close),
                abs(curr.low - prev.close)
            )
            true_ranges.append(tr)
        
        atr = np.mean(true_ranges) if true_ranges else 0.0
        
        return VolatilityMetrics(
            ticker=ticker,
            historical_volatility=float(hv),
            avg_true_range=float(atr),
            calculation_period=period
        )
    
    def _make_request(self, url: str, params: Dict) -> Dict:
        """
        Make HTTP request with retry logic
        
        Args:
            url: API endpoint URL
            params: Query parameters
            
        Returns:
            Parsed JSON response
            
        Raises:
            httpx.HTTPError: If all retries fail
        """
        for attempt in range(self.config.max_retries):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                
                data = response.json()
                
                # Check for API errors
                if "status" in data and data["status"] == "error":
                    raise ValueError(f"API error: {data.get('message', 'Unknown error')}")
                
                return data
                
            except httpx.HTTPError as e:
                if attempt == self.config.max_retries - 1:
                    raise
                # Exponential backoff
                import time
                time.sleep(2 ** attempt)
        
        raise httpx.HTTPError("Max retries exceeded")


def get_twelve_data_client() -> TwelveDataClient:
    """
    Factory function to create TwelveDataClient with environment config
    
    Reads API key from environment variable: TWELVE_DATA_API_KEY
    """
    api_key = os.getenv("TWELVE_DATA_API_KEY")
    if not api_key:
        raise ValueError("TWELVE_DATA_API_KEY environment variable not set")
    
    config = TwelveDataConfig(api_key=api_key)
    return TwelveDataClient(config)


# Example usage
if __name__ == "__main__":
    # Demo code (requires valid API key in environment)
    try:
        with get_twelve_data_client() as client:
            # Get current price
            price = client.get_current_price("AAPL")
            print(f"Current {price.ticker} price: ${price.price}")
            
            # Get OHLC data
            ohlc = client.get_ohlc_data("AAPL", outputsize=5)
            print(f"\nRecent OHLC data: {len(ohlc)} days")
            
            # Calculate volatility
            vol = client.calculate_historical_volatility("AAPL", period=30)
            print(f"\nHistorical Volatility (30d): {vol.historical_volatility:.2%}")
            print(f"Average True Range: ${vol.avg_true_range:.2f}")
            
    except Exception as e:
        print(f"Error: {e}")

"""
Yahoo Finance Options Chain Scraper

Scrapes option chain data for covered call analysis.
Extracts: strikes, expirations, bid/ask/last prices, implied volatility

NOTE: Web scraping is used for MVP. Production systems should use
      official data providers (e.g., Polygon, IEX, CBOE DataShop)
"""

import re
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field

try:
    import yfinance as yf
except Exception:
    yf = None


class OptionContract(BaseModel):
    """Individual option contract data"""
    ticker: str
    contract_type: str  # "CALL" or "PUT"
    strike: float
    expiration: datetime
    bid: float
    ask: float
    last: Optional[float] = None
    volume: int = 0
    open_interest: int = 0
    implied_volatility: Optional[float] = None  # As decimal (0.25 = 25%)
    delta: Optional[float] = None  # Estimated from IV if available
    
    @property
    def mid_price(self) -> float:
        """Calculate mid-point between bid and ask"""
        return (self.bid + self.ask) / 2
    
    @property
    def days_to_expiration(self) -> int:
        """Calculate days until expiration"""
        delta = self.expiration - datetime.now()
        return max(0, delta.days)


@dataclass
class ScraperConfig:
    """Configuration for options scraper"""
    timeout: int = 4
    max_retries: int = 1
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    rate_limit_delay: float = 0.25  # Seconds between requests


class YahooFinanceOptionsScraper:
    """
    Scrapes option chain data from Yahoo Finance
    
    Yahoo Finance URL pattern:
    https://finance.yahoo.com/quote/{TICKER}/options?date={UNIX_TIMESTAMP}
    
    Defense mechanisms:
    - User-Agent spoofing
    - Retry logic with exponential backoff
    - Rate limiting
    - Timeout protection
    - Robust HTML parsing
    """
    
    def __init__(self, config: ScraperConfig = ScraperConfig()):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})
    
    def get_option_chain(
        self,
        ticker: str,
        expiration_date: Optional[datetime] = None
    ) -> List[OptionContract]:
        """
        Fetch option chain for a given ticker
        
        Args:
            ticker: Stock symbol (e.g., "AAPL")
            expiration_date: Specific expiration to fetch (None = nearest)
            
        Returns:
            List of OptionContract objects (calls only for covered calls)
        """
        # Get available expiration dates first
        expirations = self.get_expiration_dates(ticker)
        
        if not expirations:
            raise ValueError(f"No option expirations found for {ticker}")
        
        # Use specified date or nearest expiration
        if expiration_date:
            target_exp = min(expirations, key=lambda d: abs(d - expiration_date))
        else:
            target_exp = expirations[0]  # Nearest expiration
        
        # Fetch the option chain
        return self._scrape_option_chain(ticker, target_exp)
    
    def get_all_expirations(
        self,
        ticker: str,
        max_expirations: int = 6,
        include_puts: bool = False,
    ) -> Dict[datetime, List[OptionContract]]:
        """
        Fetch option chains for multiple expiration dates
        
        Args:
            ticker: Stock symbol
            max_expirations: Maximum number of expirations to fetch
            
        Returns:
            Dictionary mapping expiration date to list of contracts
        """
        expirations = self.get_expiration_dates(ticker)
        
        result = {}
        for exp_date in expirations[:max_expirations]:
            try:
                contracts = self._scrape_option_chain(ticker, exp_date, include_puts=include_puts)
                result[exp_date] = contracts
                
                # Rate limiting
                time.sleep(self.config.rate_limit_delay)
                
            except Exception as e:
                print(f"Warning: Failed to fetch {ticker} options for {exp_date}: {e}")
                continue
        
        return result
    
    def get_expiration_dates(self, ticker: str) -> List[datetime]:
        """
        Get available option expiration dates for a ticker
        
        Args:
            ticker: Stock symbol
            
        Returns:
            Sorted list of expiration dates (nearest first)
        """
        url = f"https://finance.yahoo.com/quote/{ticker}/options"
        
        expiration_dates = []
        try:
            html = self._fetch_page(url)
            soup = BeautifulSoup(html, "lxml")

            # Find expiration dropdown/select element
            # Yahoo Finance stores expirations in a select element with Unix timestamps
            select_elem = soup.find("select", {"class": re.compile(".*expiration.*", re.I)})
            if not select_elem:
                # Fallback: search for any select with option values that look like timestamps
                select_elem = soup.find("select")

            if select_elem:
                for option in select_elem.find_all("option"):
                    value = option.get("value")
                    if value and value.isdigit():
                        timestamp = int(value)
                        exp_date = datetime.fromtimestamp(timestamp)
                        expiration_dates.append(exp_date)
        except Exception:
            expiration_dates = []
        
        # If scraping failed, generate standard monthly expirations as fallback
        if not expiration_dates:
            expiration_dates = self._get_expirations_from_yfinance(ticker)
        if not expiration_dates:
            print(f"Warning: Could not scrape expirations for {ticker}, using fallback")
            expiration_dates = self._generate_fallback_expirations()
        
        return sorted(expiration_dates)
    
    def _scrape_option_chain(
        self,
        ticker: str,
        expiration: datetime,
        include_puts: bool = False,
    ) -> List[OptionContract]:
        """
        Scrape option chain for specific expiration date
        
        Args:
            ticker: Stock symbol
            expiration: Target expiration date
            
        Returns:
            List of CALL option contracts
        """
        # Convert expiration to Unix timestamp
        timestamp = int(expiration.timestamp())
        url = f"https://finance.yahoo.com/quote/{ticker}/options?date={timestamp}"
        
        try:
            html = self._fetch_page(url)
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return self._scrape_option_chain_yfinance(ticker, expiration, include_puts=include_puts)
        
        contracts = []

        # Yahoo typically renders calls and puts as the first two options tables.
        option_tables = []
        for table in soup.find_all("table"):
            header_text = table.get_text().lower()
            if "strike" in header_text and "bid" in header_text and "ask" in header_text:
                option_tables.append(table)
            if len(option_tables) >= 2:
                break

        if not option_tables:
            raise ValueError(f"Could not find options table for {ticker}")

        table_types = ["CALL"]
        if include_puts and len(option_tables) > 1:
            table_types.append("PUT")

        for idx, contract_type in enumerate(table_types):
            table = option_tables[idx]
            rows = table.find_all("tr")[1:]
            for row in rows:
                try:
                    cells = row.find_all("td")
                    if len(cells) < 10:
                        continue

                    strike = self._parse_float(cells[2].get_text())
                    last = self._parse_float(cells[3].get_text())
                    bid = self._parse_float(cells[4].get_text())
                    ask = self._parse_float(cells[5].get_text())
                    volume = self._parse_int(cells[8].get_text())
                    open_interest = self._parse_int(cells[9].get_text())

                    iv = None
                    if len(cells) > 10:
                        iv_text = cells[10].get_text().strip()
                        if "%" in iv_text:
                            iv = self._parse_float(iv_text.replace("%", "")) / 100.0

                    delta = self._estimate_delta_from_iv(iv) if iv else None

                    contracts.append(
                        OptionContract(
                            ticker=ticker,
                            contract_type=contract_type,
                            strike=strike,
                            expiration=expiration,
                            bid=bid,
                            ask=ask,
                            last=last,
                            volume=volume,
                            open_interest=open_interest,
                            implied_volatility=iv,
                            delta=delta,
                        )
                    )
                except Exception:
                    # Skip malformed rows
                    continue

        if not contracts:
            contracts = self._scrape_option_chain_yfinance(
                ticker=ticker,
                expiration=expiration,
                include_puts=include_puts,
            )
        
        return contracts

    def _get_expirations_from_yfinance(self, ticker: str) -> List[datetime]:
        if yf is None:
            return []
        try:
            tk = yf.Ticker(ticker)
            out = []
            for exp in tk.options:
                out.append(datetime.strptime(exp, "%Y-%m-%d"))
            return sorted(out)
        except Exception:
            return []

    def _scrape_option_chain_yfinance(
        self,
        ticker: str,
        expiration: datetime,
        include_puts: bool = False,
    ) -> List[OptionContract]:
        if yf is None:
            return []
        try:
            tk = yf.Ticker(ticker)
            opt = tk.option_chain(expiration.strftime("%Y-%m-%d"))
            contracts: List[OptionContract] = []

            for _, row in opt.calls.iterrows():
                contracts.append(
                    OptionContract(
                        ticker=ticker,
                        contract_type="CALL",
                        strike=float(row.get("strike", 0.0)),
                        expiration=expiration,
                        bid=float(row.get("bid", 0.0) or 0.0),
                        ask=float(row.get("ask", 0.0) or 0.0),
                        last=float(row.get("lastPrice", 0.0) or 0.0),
                        volume=int(row.get("volume", 0) or 0),
                        open_interest=int(row.get("openInterest", 0) or 0),
                        implied_volatility=float(row.get("impliedVolatility", 0.0) or 0.0),
                        delta=None,
                    )
                )

            if include_puts:
                for _, row in opt.puts.iterrows():
                    contracts.append(
                        OptionContract(
                            ticker=ticker,
                            contract_type="PUT",
                            strike=float(row.get("strike", 0.0)),
                            expiration=expiration,
                            bid=float(row.get("bid", 0.0) or 0.0),
                            ask=float(row.get("ask", 0.0) or 0.0),
                            last=float(row.get("lastPrice", 0.0) or 0.0),
                            volume=int(row.get("volume", 0) or 0),
                            open_interest=int(row.get("openInterest", 0) or 0),
                            implied_volatility=float(row.get("impliedVolatility", 0.0) or 0.0),
                            delta=None,
                        )
                    )

            return contracts
        except Exception:
            return []
    
    def _fetch_page(self, url: str) -> str:
        """
        Fetch HTML page with retry logic
        
        Args:
            url: Target URL
            
        Returns:
            HTML content as string
            
        Raises:
            requests.RequestException: If all retries fail
        """
        for attempt in range(self.config.max_retries):
            try:
                response = self.session.get(url, timeout=self.config.timeout)
                response.raise_for_status()
                return response.text
                
            except requests.RequestException as e:
                if attempt == self.config.max_retries - 1:
                    raise
                # Exponential backoff
                time.sleep(2 ** attempt)
        
        raise requests.RequestException("Max retries exceeded")
    
    def _parse_float(self, text: str) -> float:
        """Parse float from HTML text, handling edge cases"""
        cleaned = text.strip().replace(",", "")
        if cleaned == "-" or not cleaned:
            return 0.0
        return float(cleaned)
    
    def _parse_int(self, text: str) -> int:
        """Parse integer from HTML text"""
        cleaned = text.strip().replace(",", "")
        if cleaned == "-" or not cleaned:
            return 0
        return int(float(cleaned))
    
    def _estimate_delta_from_iv(self, iv: float) -> float:
        """
        Rough delta estimation from implied volatility
        
        This is a simplified heuristic for MVP purposes.
        Production code should use Black-Scholes or similar.
        
        Assumption: Higher IV generally correlates with higher delta
        for near-the-money options.
        
        Args:
            iv: Implied volatility as decimal
            
        Returns:
            Estimated delta between 0.0 and 1.0
        """
        # Very rough approximation
        # ATM options typically have ~0.5 delta
        # OTM options have lower delta
        # This is NOT accurate and should be replaced with proper calculations
        
        # For covered calls, we typically target 0.20 - 0.40 delta
        # Map IV to reasonable delta range
        if iv < 0.15:
            return 0.15
        elif iv < 0.30:
            return 0.30
        elif iv < 0.50:
            return 0.40
        else:
            return 0.50
    
    def _generate_fallback_expirations(self) -> List[datetime]:
        """
        Generate standard monthly expiration dates as fallback
        
        Options typically expire on the 3rd Friday of each month
        """
        expirations = []
        current_date = datetime.now()
        
        for month_offset in range(6):  # Next 6 months
            target_month = current_date.month + month_offset
            target_year = current_date.year + (target_month - 1) // 12
            target_month = ((target_month - 1) % 12) + 1
            
            # Find 3rd Friday
            first_day = datetime(target_year, target_month, 1)
            first_friday = (4 - first_day.weekday()) % 7 + 1
            third_friday = first_friday + 14
            
            exp_date = datetime(target_year, target_month, third_friday)
            
            # Only include future dates
            if exp_date > current_date:
                expirations.append(exp_date)
        
        return expirations


def get_options_scraper() -> YahooFinanceOptionsScraper:
    """Factory function to create scraper with default config"""
    return YahooFinanceOptionsScraper()


# Example usage
if __name__ == "__main__":
    scraper = get_options_scraper()
    
    try:
        ticker = "AAPL"
        print(f"Fetching option chain for {ticker}...")
        
        # Get expiration dates
        expirations = scraper.get_expiration_dates(ticker)
        print(f"\nAvailable expirations: {len(expirations)}")
        for exp in expirations[:3]:
            print(f"  - {exp.strftime('%Y-%m-%d')}")
        
        # Get nearest expiration chain
        contracts = scraper.get_option_chain(ticker)
        print(f"\nFound {len(contracts)} call contracts")
        
        # Show first few contracts
        for contract in contracts[:5]:
            print(f"\n  Strike: ${contract.strike}")
            print(f"  Bid/Ask: ${contract.bid} / ${contract.ask}")
            print(f"  DTE: {contract.days_to_expiration}")
            if contract.implied_volatility:
                print(f"  IV: {contract.implied_volatility:.1%}")
        
    except Exception as e:
        print(f"Error: {e}")
        print("\nNote: Scraping may fail due to Yahoo Finance page structure changes")
        print("Production systems should use official data providers")

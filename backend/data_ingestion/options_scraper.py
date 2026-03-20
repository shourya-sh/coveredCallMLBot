from __future__ import annotations

"""
Nasdaq Options Chain Scraper

Primary source:
https://api.nasdaq.com/api/quote/{TICKER}/option-chain?assetclass=stocks
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

import requests
from pydantic import BaseModel


class OptionContract(BaseModel):
    ticker: str
    contract_type: str  # CALL or PUT
    strike: float
    expiration: datetime
    bid: float
    ask: float
    last: Optional[float] = None
    volume: int = 0
    open_interest: int = 0
    implied_volatility: Optional[float] = None
    delta: Optional[float] = None

    @property
    def mid_price(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def days_to_expiration(self) -> int:
        return max(0, (self.expiration - datetime.now()).days)


@dataclass
class ScraperConfig:
    timeout: int = 8
    max_retries: int = 2
    rate_limit_delay: float = 0.2


class YahooFinanceOptionsScraper:
    """Compatibility name; implementation now pulls from Nasdaq."""

    def __init__(self, config: ScraperConfig = ScraperConfig()):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.nasdaq.com",
                "Referer": "https://www.nasdaq.com/",
            }
        )

    def get_option_chain(self, ticker: str, expiration_date: Optional[datetime] = None) -> List[OptionContract]:
        expirations = self.get_expiration_dates(ticker)
        if not expirations:
            raise ValueError(f"No option expirations found for {ticker}")

        target_exp = expirations[0] if expiration_date is None else min(expirations, key=lambda d: abs(d - expiration_date))
        return self._fetch_expiration_contracts(ticker, target_exp, include_puts=False)

    def get_all_expirations(
        self,
        ticker: str,
        max_expirations: int = 6,
        include_puts: bool = False,
    ) -> Dict[datetime, List[OptionContract]]:
        expirations = self.get_expiration_dates(ticker)
        result: Dict[datetime, List[OptionContract]] = {}

        for exp_date in expirations[:max_expirations]:
            try:
                contracts = self._fetch_expiration_contracts(ticker, exp_date, include_puts=include_puts)
                if contracts:
                    result[exp_date] = contracts
                time.sleep(self.config.rate_limit_delay)
            except Exception as exc:
                print(f"Warning: Failed to fetch {ticker} options for {exp_date.date()}: {exc}")
                continue

        return result

    def get_expiration_dates(self, ticker: str) -> List[datetime]:
        payload = self._fetch_chain_json(ticker=ticker)
        rows = (((payload or {}).get("data") or {}).get("table") or {}).get("rows") or []

        expirations: list[datetime] = []
        seen = set()
        for row in rows:
            exp_group = (row or {}).get("expirygroup")
            if not exp_group:
                continue
            exp = self._parse_expirygroup(exp_group)
            if exp and exp.date() not in seen:
                seen.add(exp.date())
                expirations.append(exp)

        return sorted(expirations)

    def _fetch_expiration_contracts(self, ticker: str, expiration: datetime, include_puts: bool) -> List[OptionContract]:
        params = {
            "fromdate": expiration.strftime("%Y-%m-%d"),
            "todate": expiration.strftime("%Y-%m-%d"),
        }
        payload = self._fetch_chain_json(ticker=ticker, extra_params=params)
        rows = (((payload or {}).get("data") or {}).get("table") or {}).get("rows") or []
        return self._parse_rows(ticker=ticker, rows=rows, include_puts=include_puts, fallback_expiration=expiration)

    def _fetch_chain_json(self, ticker: str, extra_params: Optional[dict] = None) -> dict:
        url = f"https://api.nasdaq.com/api/quote/{ticker.upper()}/option-chain"
        params = {"assetclass": "stocks"}
        if extra_params:
            params.update(extra_params)

        last_exc: Exception | None = None
        for attempt in range(self.config.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.config.timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_exc = exc
                if attempt < self.config.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))

        raise RuntimeError(f"Nasdaq options API failed for {ticker}: {last_exc}")

    def _parse_rows(
        self,
        ticker: str,
        rows: list,
        include_puts: bool,
        fallback_expiration: Optional[datetime] = None,
    ) -> List[OptionContract]:
        contracts: List[OptionContract] = []
        current_exp = fallback_expiration

        for row in rows:
            row = row or {}
            if row.get("expirygroup"):
                maybe_exp = self._parse_expirygroup(row.get("expirygroup"))
                if maybe_exp:
                    current_exp = maybe_exp
                continue

            strike = self._parse_float(row.get("strike"))
            if strike is None or current_exp is None:
                continue

            call_bid = self._parse_num(row.get("c_Bid"))
            call_ask = self._parse_num(row.get("c_Ask"))
            call_last = self._parse_num(row.get("c_Last"))
            call_vol = self._parse_int(row.get("c_Volume"))
            call_oi = self._parse_int(row.get("c_Openinterest"))

            if call_bid is not None and call_ask is not None:
                contracts.append(
                    OptionContract(
                        ticker=ticker.upper(),
                        contract_type="CALL",
                        strike=strike,
                        expiration=current_exp,
                        bid=call_bid,
                        ask=call_ask,
                        last=call_last,
                        volume=call_vol,
                        open_interest=call_oi,
                    )
                )

            if include_puts:
                put_bid = self._parse_num(row.get("p_Bid"))
                put_ask = self._parse_num(row.get("p_Ask"))
                put_last = self._parse_num(row.get("p_Last"))
                put_vol = self._parse_int(row.get("p_Volume"))
                put_oi = self._parse_int(row.get("p_Openinterest"))

                if put_bid is not None and put_ask is not None:
                    contracts.append(
                        OptionContract(
                            ticker=ticker.upper(),
                            contract_type="PUT",
                            strike=strike,
                            expiration=current_exp,
                            bid=put_bid,
                            ask=put_ask,
                            last=put_last,
                            volume=put_vol,
                            open_interest=put_oi,
                        )
                    )

        return contracts

    @staticmethod
    def _parse_expirygroup(value: str | None) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%B %d, %Y")
        except ValueError:
            return None

    @staticmethod
    def _parse_num(value) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip().replace(",", "")
        if not text or text == "--":
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _parse_float(value) -> Optional[float]:
        return YahooFinanceOptionsScraper._parse_num(value)

    @staticmethod
    def _parse_int(value) -> int:
        num = YahooFinanceOptionsScraper._parse_num(value)
        if num is None:
            return 0
        return int(num)


def get_options_scraper() -> YahooFinanceOptionsScraper:
    return YahooFinanceOptionsScraper()

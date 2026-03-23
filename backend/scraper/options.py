from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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


class NasdaqOptionsScraper:
    def __init__(self, config: ScraperConfig = ScraperConfig()):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/",
        })

    def get_expiration_dates(self, ticker: str) -> list[datetime]:
        payload = self._fetch_chain_json(ticker)
        rows = (((payload or {}).get("data") or {}).get("table") or {}).get("rows") or []
        expirations, seen = [], set()
        for row in rows:
            exp = self._parse_expiry(row.get("expirygroup"))
            if exp and exp.date() not in seen:
                seen.add(exp.date())
                expirations.append(exp)
        return sorted(expirations)

    def get_all_expirations(
        self,
        ticker: str,
        max_expirations: int = 6,
        include_puts: bool = True,
    ) -> dict[datetime, list[OptionContract]]:
        result: dict[datetime, list[OptionContract]] = {}
        for exp in self.get_expiration_dates(ticker)[:max_expirations]:
            try:
                payload = self._fetch_chain_json(ticker, {"fromdate": exp.strftime("%Y-%m-%d"), "todate": exp.strftime("%Y-%m-%d")})
                rows = (((payload or {}).get("data") or {}).get("table") or {}).get("rows") or []
                contracts = self._parse_rows(ticker, rows, include_puts, fallback_expiration=exp)
                if contracts:
                    result[exp] = contracts
                time.sleep(self.config.rate_limit_delay)
            except Exception as e:
                print(f"  [options] {ticker} {exp.date()} failed: {e}")
        return result

    def _fetch_chain_json(self, ticker: str, extra_params: dict | None = None) -> dict:
        url = f"https://api.nasdaq.com/api/quote/{ticker.upper()}/option-chain"
        params = {"assetclass": "stocks", **(extra_params or {})}
        last_exc = None
        for attempt in range(self.config.max_retries):
            try:
                resp = self.session.get(url, params=params, timeout=self.config.timeout)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_exc = e
                if attempt < self.config.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
        raise RuntimeError(f"Nasdaq API failed for {ticker}: {last_exc}")

    def _parse_rows(self, ticker: str, rows: list, include_puts: bool, fallback_expiration: datetime | None = None) -> list[OptionContract]:
        contracts = []
        current_exp = fallback_expiration
        for row in rows:
            row = row or {}
            if row.get("expirygroup"):
                exp = self._parse_expiry(row["expirygroup"])
                if exp:
                    current_exp = exp
                continue

            strike = self._num(row.get("strike"))
            if strike is None or current_exp is None:
                continue

            call_bid, call_ask = self._num(row.get("c_Bid")), self._num(row.get("c_Ask"))
            if call_bid is not None and call_ask is not None:
                contracts.append(OptionContract(
                    ticker=ticker.upper(), contract_type="CALL", strike=strike, expiration=current_exp,
                    bid=call_bid, ask=call_ask, last=self._num(row.get("c_Last")),
                    volume=self._int(row.get("c_Volume")), open_interest=self._int(row.get("c_Openinterest")),
                ))

            if include_puts:
                put_bid, put_ask = self._num(row.get("p_Bid")), self._num(row.get("p_Ask"))
                if put_bid is not None and put_ask is not None:
                    contracts.append(OptionContract(
                        ticker=ticker.upper(), contract_type="PUT", strike=strike, expiration=current_exp,
                        bid=put_bid, ask=put_ask, last=self._num(row.get("p_Last")),
                        volume=self._int(row.get("p_Volume")), open_interest=self._int(row.get("p_Openinterest")),
                    ))
        return contracts

    @staticmethod
    def _parse_expiry(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.strptime(value.strip(), "%B %d, %Y")
        except ValueError:
            return None

    @staticmethod
    def _num(value) -> float | None:
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
    def _int(value) -> int:
        num = NasdaqOptionsScraper._num(value)
        return int(num) if num is not None else 0


def get_scraper() -> NasdaqOptionsScraper:
    return NasdaqOptionsScraper()

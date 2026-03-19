"""
Shared dependencies and utilities for API endpoints

Supports two modes:
1. Production mode: Uses real Twelve Data API and web scraping
2. Demo mode: Uses mock data when API key is not configured
"""

import os
from pathlib import Path
from typing import Union

from dotenv import load_dotenv

# Ensure .env is loaded from backend/ directory
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from data_ingestion import get_twelve_data_client, get_options_scraper
from data_ingestion.twelve_data_client import TwelveDataClient
from data_ingestion.options_scraper import YahooFinanceOptionsScraper
from demo_mode import DemoTwelveDataClient, DemoOptionsScraper, get_demo_stock_client, get_demo_options_scraper
from strategy import CoveredCallEngine


# Global clients (initialized once)
_stock_client = None
_options_scraper = None
_engine = None
_demo_mode = None


def is_demo_mode() -> bool:
    """Check if running in demo mode (no API key)"""
    global _demo_mode
    if _demo_mode is None:
        _demo_mode = not bool(os.getenv("TWELVE_DATA_API_KEY"))
    return _demo_mode


def get_stock_client() -> Union[TwelveDataClient, DemoTwelveDataClient]:
    """Get or create stock data client (real or demo)"""
    global _stock_client
    if _stock_client is None:
        if is_demo_mode():
            _stock_client = get_demo_stock_client()
        else:
            _stock_client = get_twelve_data_client()
    return _stock_client


def get_scraper() -> Union[YahooFinanceOptionsScraper, DemoOptionsScraper]:
    """Get or create options scraper (real or demo)"""
    global _options_scraper
    if _options_scraper is None:
        if is_demo_mode():
            _options_scraper = get_demo_options_scraper()
        else:
            _options_scraper = get_options_scraper()
    return _options_scraper


def get_engine() -> CoveredCallEngine:
    """Get or create strategy engine"""
    global _engine
    if _engine is None:
        _engine = CoveredCallEngine(
            stock_client=get_stock_client(),
            options_scraper=get_scraper()
        )
    return _engine


def validate_api_key() -> bool:
    """Check if Twelve Data API key is configured (or in demo mode)"""
    # In demo mode, we always return True since we don't need the API key
    if is_demo_mode():
        return True
    return bool(os.getenv("TWELVE_DATA_API_KEY"))


def get_services_status() -> dict:
    """Check status of external services"""
    services = {}
    
    if is_demo_mode():
        services["mode"] = "demo"
        services["twelve_data_api"] = "demo_mode"
        services["options_scraper"] = "demo_mode"
    else:
        services["mode"] = "production"
        services["twelve_data_api"] = "configured" if os.getenv("TWELVE_DATA_API_KEY") else "not_configured"
        
        # Check if scraper is accessible
        try:
            scraper = get_scraper()
            services["options_scraper"] = "ready"
        except Exception:
            services["options_scraper"] = "error"
    
    return services

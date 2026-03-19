"""
Application Configuration

Centralized configuration management using Pydantic Settings.
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # API Configuration
    app_name: str = "Covered Call Dashboard"
    app_version: str = "1.0.0"
    debug: bool = False
    
    # Twelve Data API
    twelve_data_api_key: Optional[str] = None
    twelve_data_base_url: str = "https://api.twelvedata.com"
    twelve_data_timeout: int = 10
    twelve_data_max_retries: int = 3
    twelve_data_max_outputsize: int = 5000
    
    # Rate Limiting
    rate_limit_calls_per_minute: int = 8
    rate_limit_calls_per_day: int = 800

    # Storage + Cache Infrastructure
    postgres_dsn: Optional[str] = None
    redis_url: Optional[str] = None

    # Scheduler / Ingestion
    ingestion_intervals: str = "5min,1day"
    ingestion_batch_size: int = 5
    ingestion_cycle_seconds: int = 60
    ingestion_high_priority_threshold: int = 3
    
    # Scraper Configuration
    scraper_timeout: int = 10
    scraper_max_retries: int = 3
    scraper_rate_limit_delay: float = 1.0
    
    # Default Settings
    default_risk_profile: str = "moderate"
    max_expirations_to_fetch: int = 6
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Export for convenience
settings = get_settings()

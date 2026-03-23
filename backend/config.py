from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    twelve_data_api_key: str
    postgres_dsn: str | None = None

    dashboard_refresh_minutes: int = 15
    ohlc_outputsize: int = 1825  # ~5 years of daily bars
    dashboard_cache_ttl_seconds: int = 120
    options_cache_max_age_minutes: int = 30

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

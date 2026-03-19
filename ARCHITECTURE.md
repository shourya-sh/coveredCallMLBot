# Covered Call Dashboard - System Architecture

## Overview
This application provides decision support for covered call option strategies on a stock portfolio.

## Data Flow
1. User submits portfolio via REST API
2. System validates positions and filters for ≥100 shares
3. Data ingestion layer fetches:
   - Stock prices from Twelve Data API
   - Option chains from Yahoo Finance (scraped)
4. Strategy engine:
   - Applies user risk profile (Conservative/Moderate/Aggressive)
   - Filters valid contracts
   - Computes metrics (yield, annualized return, break-even, etc.)
   - Scores and ranks options
5. Recommendation engine decides SELL vs HOLD with explanation
6. Clean JSON response returned to mobile app

## Core Modules

### data_ingestion/
Handles all external data retrieval
- **twelve_data_client.py**: Stock price & OHLC data
- **options_scraper.py**: Option chain scraping & parsing

### models/
Pydantic schemas for data validation
- **portfolio.py**: Portfolio/Position models
- **options.py**: Option contract models
- **risk_profiles.py**: Risk profile enums & configs

### strategy/
Core covered call logic
- **covered_call_engine.py**: Main strategy coordinator
- **metrics_calculator.py**: Financial calculations
- **option_scorer.py**: Ranking algorithm
- **recommendation.py**: Decision logic

### api/
FastAPI REST interface
- **main.py**: Application entry point
- **schemas.py**: API contracts
- **dependencies.py**: Shared utilities

## Key Assumptions
- No broker integration (decision support only)
- No auto-trading capabilities
- Web scraping is acceptable for MVP
- Implied volatility from option chains used for delta proxy
- No tax considerations
- No margin calculations
- Covered calls only (no spreads or other strategies)

## Tech Stack
- Python 3.11
- FastAPI for REST API
- Pydantic for validation
- Requests/httpx for HTTP
- BeautifulSoup for scraping
- Pandas/NumPy for calculations

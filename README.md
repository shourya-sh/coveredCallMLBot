# Dashy — Covered Call Dashboard

Full-stack covered call decision support system.  
**Backend:** FastAPI + Python &nbsp;|&nbsp; **Frontend:** React + Vite + Recharts

## Quick Start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
```

Create `backend/.env`:
```
TWELVE_DATA_API_KEY=your_api_key_here
DASHBOARD_REFRESH_MINUTES=15
MODEL_RETRAIN_AFTER_HOUR_ET=17
MODEL_RETRAIN_AFTER_MINUTE_ET=45
OPTIONS_ALLOW_SYNTHETIC_FALLBACK=false
```
> No API key? The app runs in **demo mode** with mock data automatically.

### Automated Operations

- Price refresh runs every 10-15 minutes (`DASHBOARD_REFRESH_MINUTES`, defaults to 15) and updates SQLite (`stock_prices`, `ohlc_history`).
- Nightly model retraining runs after market close (ET) and writes updated artifacts under `backend/strategy_ml/artifacts/`.
- The API hot-reloads the model automatically when a new nightly artifact appears.
- Options execution plans are sourced from Yahoo data (HTML/yfinance). Synthetic fallback is disabled by default.

```bash
cd backend
uvicorn api.main:app --reload
```

API docs: http://localhost:8000/docs

### 1.1 Train Options Strategy Classifier

The dashboard analysis now comes from a strategy classifier that maps market state to one of:

- BULL_CALL_SPREAD
- BEAR_PUT_SPREAD
- IRON_CONDOR
- LONG_STRADDLE
- NO_TRADE

Training command:

```bash
cd backend
python train_model.py --tickers AAPL,MSFT,GOOGL,TSLA,NVDA,META,AMZN,AMD,JPM,V --interval 1day --limit 700 --horizon 10 --model-type random_forest
```

Prediction command:

```bash
cd backend
python predict.py --ticker AAPL --interval 1day
```

You can also use the unified CLI:

```bash
cd backend
python -m strategy_ml.cli train
python -m strategy_ml.cli predict --ticker AAPL
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### How It Works

- The **dashboard** shows 10 default stocks with sparkline charts and strategy analysis.
- Analysis includes per-strategy probabilities, top strategy, confidence, risk flags, and an options execution plan.
- The backend limits stock analysis to the 10 dashboard tickers.
- Stock data is **cached for 15 minutes** — a "Last updated" timestamp shows when data was last fetched.
- No real-time streaming; the backend fetches from Twelve Data at most once per 15 minutes per ticker.

### Strategy Modeling Pipeline

Implemented under backend/strategy_ml:

- db/: PostgreSQL candle access
- data_loader.py: historical data retrieval
- feature_engineering.py: trend, momentum, volatility, context features
- label_generator.py: rule-based labels + performance-optimized relabeling
- backtester.py: simplified options PnL simulation and model-level backtest metrics
- train_model.py: time-series-safe training and artifact persistence
- predict.py: real-time strategy probabilities and execution-plan output

Model artifacts are stored at:

- backend/strategy_ml/artifacts/options_strategy_model.joblib
- backend/strategy_ml/artifacts/options_strategy_model.metrics.json

## API Endpoints

### POST /portfolio/evaluate
Analyze a portfolio and identify covered call opportunities

**Request:**
```json
{
  "positions": [
    {
      "ticker": "AAPL",
      "shares": 200,
      "cost_basis": 150.00
    }
  ],
  "risk_profile": "moderate"
}
```

**Response:**
```json
{
  "eligible_positions": [
    {
      "ticker": "AAPL",
      "shares": 200,
      "current_price": 175.50,
      "contracts_available": 2
    }
  ],
  "total_positions": 1,
  "eligible_count": 1
}
```

### POST /covered-calls/recommendation
Get covered call recommendation for a specific position

**Request:**
```json
{
  "ticker": "AAPL",
  "shares": 200,
  "cost_basis": 150.00,
  "risk_profile": "moderate"
}
```

**Response:**
```json
{
  "action": "SELL",
  "recommended_contract": {
    "strike": 180.0,
    "expiration": "2026-02-20",
    "premium": 2.50,
    "delta": 0.35
  },
  "metrics": {
    "premium_yield": 1.43,
    "annualized_return": 18.5,
    "max_profit": 650.00,
    "downside_protection": 1.43,
    "break_even_price": 173.00,
    "assignment_probability": 35.0
  },
  "explanation": "High implied volatility and low assignment risk make this strike favorable for income generation."
}
```

### GET /health
Health check endpoint

## Project Structure

```
dashy/
├── api/                    # FastAPI application
│   ├── main.py            # App entry point & routes
│   ├── schemas.py         # Request/response models
│   └── dependencies.py    # Shared utilities
├── models/                # Data models
│   ├── portfolio.py       # Portfolio schemas
│   ├── options.py         # Option contracts
│   └── risk_profiles.py   # Risk configurations
├── strategy/              # Core logic
│   ├── covered_call_engine.py
│   ├── metrics_calculator.py
│   ├── option_scorer.py
│   └── recommendation.py
├── data_ingestion/        # External data
│   ├── twelve_data_client.py
│   └── options_scraper.py
├── requirements.txt
└── README.md
```

## Risk Profiles

### Conservative
- **Delta Range:** 0.15 - 0.30
- **DTE Range:** 30 - 60 days
- **Goal:** Income stability, low assignment risk

### Moderate
- **Delta Range:** 0.30 - 0.45
- **DTE Range:** 21 - 45 days
- **Goal:** Balanced income and risk

### Aggressive
- **Delta Range:** 0.45 - 0.65
- **DTE Range:** 7 - 30 days
- **Goal:** Maximum premium, accept higher assignment risk

## Metrics Explained

- **Premium Yield:** Premium as % of stock price
- **Annualized Return:** Extrapolated annual return %
- **Max Profit:** Total gain if stock closes at strike
- **Downside Protection:** Premium cushion against price drop
- **Break-Even Price:** Stock price where position breaks even
- **Assignment Probability:** Estimated via delta

## Constraints

- ✅ Covered calls only (no naked calls, spreads, or other strategies)
- ✅ Decision support (no auto-trading)
- ✅ No broker integration
- ✅ No tax optimization
- ✅ No margin calculations

## Data Sources

- **Stock Data:** Twelve Data API (https://twelvedata.com/)
- **Options Data:** Yahoo Finance (web scraping)

## Development

### Run Tests
```bash
pytest tests/
```

### Format Code
```bash
black .
isort .
```

## License

MIT

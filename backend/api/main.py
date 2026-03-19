"""
FastAPI Application

Main API endpoints for covered call decision support.

Endpoints:
- POST /portfolio/evaluate - Analyze portfolio for covered call opportunities
- POST /covered-calls/recommendation - Get recommendation for specific position
- GET /health - Health check
- GET /dashboard/stocks - Get cached data for dashboard stocks
- GET /stock/{ticker} - Get stock + recommendation for a single ticker
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from dotenv import load_dotenv

# Load .env from backend/ directory regardless of cwd
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import db
from scraper import start_background_scraper
from options_cache import get_options_chain_for_ticker

from api.schemas import (
    PortfolioEvaluationRequest,
    PortfolioEvaluationResponse,
    CoveredCallRecommendationRequest,
    CoveredCallRecommendationResponse,
    HealthCheckResponse,
    EligiblePositionResponse,
    ContractDetailsResponse,
    MetricsResponse,
    AlternativeContractResponse,
    ErrorResponse,
)
from api.dependencies import (
    get_engine,
    get_stock_client,
    get_scraper,
    validate_api_key,
    get_services_status,
)
from models.portfolio import Portfolio, Position, EligiblePosition
from models.risk_profiles import RiskProfile, validate_risk_profile
from strategy.option_scorer import OptionScorer
from strategy.recommendation import RecommendationEngine
from strategy_ml.predict import StrategyPredictor
from strategy_ml.types import StrategyClass


# ============================================================================
# APPLICATION SETUP
# ============================================================================

app = FastAPI(
    title="Covered Call Dashboard API",
    description="""
    Decision support API for covered call option strategies.
    
    ## Features
    - Portfolio analysis for covered call eligibility
    - Option chain analysis with risk-adjusted scoring
    - SELL/HOLD recommendations with explanations
    - Multiple risk profiles (Conservative, Moderate, Aggressive)
    
    ## Data Sources
    - Stock prices: Twelve Data API
    - Options: Yahoo Finance (scraped)
    
    ## Notes
    - This is decision support only, not trading advice
    - No auto-execution or broker integration
    - Covered calls only (no spreads)
    """,
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    """Initialize DB and start background price scraper."""
    db.init_db()
    start_background_scraper()


# ============================================================================
# HEALTH CHECK ENDPOINT
# ============================================================================

@app.get(
    "/health",
    response_model=HealthCheckResponse,
    tags=["Health"],
    summary="Check API health status"
)
async def health_check():
    """
    Health check endpoint
    
    Returns:
    - API status
    - External service status
    - Timestamp
    """
    return HealthCheckResponse(
        status="healthy",
        timestamp=datetime.now(),
        services=get_services_status()
    )


# ============================================================================
# PORTFOLIO EVALUATION ENDPOINT
# ============================================================================

@app.post(
    "/portfolio/evaluate",
    response_model=PortfolioEvaluationResponse,
    tags=["Portfolio"],
    summary="Evaluate portfolio for covered call opportunities",
    responses={
        200: {"description": "Portfolio evaluation results"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
async def evaluate_portfolio(request: PortfolioEvaluationRequest):
    """
    Analyze a portfolio and identify positions eligible for covered calls.
    
    **Request Body:**
    - `positions`: List of positions with ticker, shares, and optional cost_basis
    - `risk_profile`: conservative, moderate, or aggressive
    
    **Response:**
    - `eligible_positions`: Positions with ≥100 shares
    - `total_positions`: Total positions submitted
    - `eligible_count`: Count of eligible positions
    
    **Example:**
    ```json
    {
        "positions": [
            {"ticker": "AAPL", "shares": 200, "cost_basis": 150.00}
        ],
        "risk_profile": "moderate"
    }
    ```
    """
    try:
        # Validate risk profile
        risk_profile = validate_risk_profile(request.risk_profile)
        
        # Create portfolio model
        positions = [
            Position(
                ticker=pos.ticker,
                shares=pos.shares,
                cost_basis=pos.cost_basis
            )
            for pos in request.positions
        ]
        
        portfolio = Portfolio(positions=positions, risk_profile=risk_profile)
        
        # Get stock client
        if not validate_api_key():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Twelve Data API key not configured"
            )
        
        stock_client = get_stock_client()
        
        # Analyze each position
        eligible_positions = []
        
        for position in portfolio.positions:
            is_eligible = position.is_covered_call_eligible
            
            # Fetch current price
            try:
                price_data = stock_client.get_current_price(position.ticker)
                current_price = price_data.price
            except Exception as e:
                # If price fetch fails, mark as ineligible
                eligible_positions.append(EligiblePositionResponse(
                    ticker=position.ticker,
                    shares=position.shares,
                    cost_basis=position.cost_basis,
                    current_price=0.0,
                    contracts_available=0,
                    is_eligible=False,
                    reason=f"Unable to fetch price: {str(e)}"
                ))
                continue
            
            reason = None
            if not is_eligible:
                reason = "Requires at least 100 shares for covered calls"
            
            eligible_positions.append(EligiblePositionResponse(
                ticker=position.ticker,
                shares=position.shares,
                cost_basis=position.cost_basis,
                current_price=current_price,
                contracts_available=position.max_contracts,
                is_eligible=is_eligible,
                reason=reason
            ))
        
        return PortfolioEvaluationResponse(
            eligible_positions=eligible_positions,
            total_positions=portfolio.total_positions,
            eligible_count=portfolio.eligible_count,
            risk_profile=risk_profile.value,
            analysis_timestamp=datetime.now()
        )
        
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# COVERED CALL RECOMMENDATION ENDPOINT
# ============================================================================

@app.post(
    "/covered-calls/recommendation",
    response_model=CoveredCallRecommendationResponse,
    tags=["Recommendations"],
    summary="Get covered call recommendation for a position",
    responses={
        200: {"description": "Covered call recommendation"},
        400: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Server error"}
    }
)
async def get_covered_call_recommendation(request: CoveredCallRecommendationRequest):
    """
    Get covered call recommendation for a specific stock position.
    
    **Request Body:**
    - `ticker`: Stock symbol
    - `shares`: Number of shares owned (≥100 required)
    - `cost_basis`: Optional average cost per share
    - `risk_profile`: conservative, moderate, or aggressive
    
    **Response:**
    - `action`: SELL or HOLD
    - `recommended_contract`: Strike, expiration, premium, delta
    - `metrics`: Premium yield, annualized return, max profit, etc.
    - `explanation`: Human-readable reasoning
    - `confidence`: high, medium, or low
    - `warnings`: Risk warnings if applicable
    
    **Example:**
    ```json
    {
        "ticker": "AAPL",
        "shares": 200,
        "cost_basis": 150.00,
        "risk_profile": "moderate"
    }
    ```
    """
    try:
        # Validate risk profile
        risk_profile = validate_risk_profile(request.risk_profile)
        
        # Create position
        position = Position(
            ticker=request.ticker,
            shares=request.shares,
            cost_basis=request.cost_basis
        )
        
        # Validate eligibility
        if not position.is_covered_call_eligible:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Position requires at least 100 shares. Current: {position.shares}"
            )
        
        # Check API key
        if not validate_api_key():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Twelve Data API key not configured"
            )
        
        # Get dependencies
        stock_client = get_stock_client()
        options_scraper = get_scraper()
        
        # Fetch current stock price
        try:
            price_data = stock_client.get_current_price(position.ticker)
            stock_price = price_data.price
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch stock price: {str(e)}"
            )
        
        # Fetch option chains
        try:
            option_chains = options_scraper.get_all_expirations(
                position.ticker,
                max_expirations=6
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch options data: {str(e)}"
            )
        
        # Flatten all contracts
        all_contracts = []
        for contracts in option_chains.values():
            all_contracts.extend(contracts)
        
        if not all_contracts:
            # No options available
            rec_engine = RecommendationEngine(risk_profile)
            recommendation = rec_engine.generate_recommendation(position.ticker, None)
            
            return CoveredCallRecommendationResponse(
                action=recommendation.action.value,
                ticker=recommendation.ticker,
                risk_profile=recommendation.risk_profile.value,
                explanation=recommendation.explanation,
                confidence=recommendation.confidence,
                timestamp=datetime.now()
            )
        
        # Score and filter contracts
        scorer = OptionScorer(risk_profile)
        scored_options = scorer.score_contracts(all_contracts, stock_price)
        
        # Generate recommendation
        rec_engine = RecommendationEngine(risk_profile)
        best_option = scored_options[0] if scored_options else None
        recommendation = rec_engine.generate_recommendation(
            position.ticker,
            best_option,
            scored_options
        )
        
        # Build response
        recommended_contract = None
        metrics = None
        
        if recommendation.recommended_contract:
            recommended_contract = ContractDetailsResponse(
                strike=recommendation.recommended_contract["strike"],
                expiration=recommendation.recommended_contract["expiration"],
                premium=recommendation.recommended_contract["premium"],
                delta=recommendation.recommended_contract.get("delta")
            )
        
        if recommendation.metrics:
            metrics = MetricsResponse(
                premium_yield=recommendation.metrics["premium_yield"],
                annualized_return=recommendation.metrics["annualized_return"],
                max_profit=recommendation.metrics["max_profit"],
                downside_protection=recommendation.metrics["downside_protection"],
                break_even_price=recommendation.metrics["break_even_price"],
                assignment_probability=recommendation.metrics.get("assignment_probability"),
                days_to_expiration=recommendation.metrics["days_to_expiration"]
            )
        
        alternatives = [
            AlternativeContractResponse(
                strike=alt["strike"],
                expiration=alt["expiration"],
                premium=alt["premium"],
                score=alt["score"]
            )
            for alt in recommendation.alternative_contracts
        ]
        
        return CoveredCallRecommendationResponse(
            action=recommendation.action.value,
            ticker=recommendation.ticker,
            risk_profile=recommendation.risk_profile.value,
            recommended_contract=recommended_contract,
            metrics=metrics,
            explanation=recommendation.explanation,
            confidence=recommendation.confidence,
            alternative_contracts=alternatives,
            warnings=recommendation.warnings,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# ROOT ENDPOINT
# ============================================================================

@app.get("/", tags=["Info"])
async def root():
    """API information"""
    return {
        "name": "Covered Call Dashboard API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# ============================================================================
# DASHBOARD STOCKS
# ============================================================================

DASHBOARD_TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMZN", "MSFT", "META", "SPX"]
_strategy_predictor: StrategyPredictor | None = None


def _get_strategy_predictor() -> StrategyPredictor | None:
    global _strategy_predictor
    if _strategy_predictor is not None:
        return _strategy_predictor

    model_path = Path(__file__).resolve().parent.parent / "strategy_ml" / "artifacts" / "options_strategy_model.joblib"
    if not model_path.exists():
        return None

    try:
        _strategy_predictor = StrategyPredictor(
            model_path=str(model_path),
            confidence_threshold=0.33,
            options_scraper=get_scraper(),
        )
        return _strategy_predictor
    except Exception:
        return None


def _ml_analysis_for_ticker(ticker: str, include_execution_plan: bool = False) -> dict:
    predictor = _get_strategy_predictor()
    if predictor is None:
        return {
            "ticker": ticker,
            "top_strategy": StrategyClass.NO_TRADE.value,
            "confidence": 0.0,
            "probabilities": {StrategyClass.NO_TRADE.value: 1.0},
            "risk_flags": ["model_not_trained"],
            "execution_plan": None,
        }

    try:
        if include_execution_plan:
            return predictor.predict_ticker_with_execution_plan(ticker)
        return predictor.predict_ticker(ticker)
    except Exception as exc:
        return {
            "ticker": ticker,
            "top_strategy": StrategyClass.NO_TRADE.value,
            "confidence": 0.0,
            "probabilities": {StrategyClass.NO_TRADE.value: 1.0},
            "risk_flags": [f"prediction_failed:{str(exc)}"],
            "execution_plan": None,
        }


def _snapshot_from_db(ticker: str) -> dict:
    """Build a snapshot dict from the SQLite database (instant, no API call)."""
    row = db.get_price(ticker)
    history = db.get_ohlc(ticker, limit=30)
    return {
        "ticker": ticker,
        "price": row["price"] if row else 0.0,
        "change_pct": row["change_pct"] if row else 0.0,
        "history": history,
        "last_updated": row["updated_at"] if row else None,
    }


@app.get("/dashboard/stocks", tags=["Dashboard"])
async def dashboard_stocks():
    """Return snapshots for the 10 default tickers — reads from local DB, zero latency."""
    stocks = []
    for ticker in DASHBOARD_TICKERS:
        snapshot = _snapshot_from_db(ticker)
        snapshot["analysis"] = _ml_analysis_for_ticker(ticker, include_execution_plan=False)
        stocks.append(snapshot)
    last = db.last_updated_any()
    return {"stocks": stocks, "last_updated": last}


@app.get("/stock/{ticker}", tags=["Dashboard"])
async def single_stock(ticker: str):
    """
    Return price snapshot + strategy analysis for one of the dashboard tickers.
    """
    ticker = ticker.strip().upper()
    if ticker not in DASHBOARD_TICKERS:
        raise HTTPException(status_code=400, detail="Ticker is not in dashboard universe")

    snapshot = _snapshot_from_db(ticker)
    predictor = _get_strategy_predictor()
    if predictor is None:
        return {**snapshot, "analysis": _ml_analysis_for_ticker(ticker, include_execution_plan=True)}

    options_contracts = []
    chain_source = "none"
    chain_updated_at = None
    try:
        options_contracts, chain_source = get_options_chain_for_ticker(
            ticker=ticker,
            scraper=get_scraper(),
            max_expirations=1,
            force_refresh=False,
        )
        chain_updated_at = db.get_option_chain_last_updated(ticker)
    except Exception:
        chain_source = "unavailable"

    analysis = predictor.predict_ticker_with_execution_plan(
        ticker=ticker,
        contracts_override=options_contracts if options_contracts else None,
    )
    analysis["options_chain_source"] = chain_source
    analysis["options_chain_updated_at"] = chain_updated_at
    return {**snapshot, "analysis": analysis}


# ============================================================================
# DEVELOPMENT SERVER
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

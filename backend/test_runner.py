"""
Test Runner Script

Verifies all modules load correctly and runs basic unit tests.
"""

import sys
import traceback
from datetime import datetime, timedelta


def test_imports():
    """Test all module imports"""
    print("Testing imports...")
    
    modules = [
        ("config", "from config import settings"),
        ("models.risk_profiles", "from models.risk_profiles import RiskProfile, get_risk_profile_config"),
        ("models.portfolio", "from models.portfolio import Portfolio, Position"),
        ("models.options", "from models.options import OptionMetrics, ScoredOption"),
        ("data_ingestion.twelve_data_client", "from data_ingestion.twelve_data_client import TwelveDataClient, StockPrice"),
        ("data_ingestion.options_scraper", "from data_ingestion.options_scraper import YahooFinanceOptionsScraper, OptionContract"),
        ("strategy.option_scorer", "from strategy.option_scorer import OptionScorer"),
        ("strategy.covered_call_engine", "from strategy.covered_call_engine import CoveredCallEngine"),
        ("strategy.recommendation", "from strategy.recommendation import RecommendationEngine, Recommendation"),
        ("api.schemas", "from api.schemas import PortfolioEvaluationRequest, CoveredCallRecommendationResponse"),
        ("demo_mode", "from demo_mode import DemoTwelveDataClient, DemoOptionsScraper"),
    ]
    
    failed = []
    for name, import_stmt in modules:
        try:
            exec(import_stmt)
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            failed.append(name)
    
    return len(failed) == 0


def test_risk_profiles():
    """Test risk profile configuration"""
    print("\nTesting risk profiles...")
    
    from models.risk_profiles import RiskProfile, get_risk_profile_config
    
    for profile in RiskProfile:
        config = get_risk_profile_config(profile)
        print(f"  {profile.value}:")
        print(f"    Delta: {config.delta_range}")
        print(f"    DTE: {config.dte_range}")
    
    return True


def test_portfolio_model():
    """Test portfolio model"""
    print("\nTesting portfolio model...")
    
    from models.portfolio import Portfolio, Position
    from models.risk_profiles import RiskProfile
    
    # Valid portfolio
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=200, cost_basis=150.00),
            Position(ticker="MSFT", shares=100),
            Position(ticker="GOOGL", shares=50),  # Not eligible
        ],
        risk_profile=RiskProfile.MODERATE
    )
    
    print(f"  Total positions: {portfolio.total_positions}")
    print(f"  Eligible positions: {portfolio.eligible_count}")
    
    assert portfolio.total_positions == 3
    assert portfolio.eligible_count == 2
    
    # Test validation
    try:
        Portfolio(positions=[])  # Should fail
        print("  ✗ Empty portfolio validation failed")
        return False
    except Exception:
        print("  ✓ Empty portfolio validation passed")
    
    return True


def test_option_metrics():
    """Test option metrics calculation"""
    print("\nTesting option metrics...")
    
    from models.options import OptionMetrics
    
    # Test calculation
    metrics = OptionMetrics.calculate(
        stock_price=175.00,
        strike=180.00,
        premium=2.50,
        expiration=datetime.now() + timedelta(days=30),
        delta=0.35
    )
    
    print(f"  Premium Yield: {metrics.premium_yield:.2f}%")
    print(f"  Annualized Return: {metrics.annualized_return:.2f}%")
    print(f"  Max Profit: ${metrics.max_profit:.2f}")
    print(f"  Break-Even: ${metrics.break_even_price:.2f}")
    
    # Verify calculations
    expected_yield = (2.50 / 175.00) * 100  # 1.43%
    assert abs(metrics.premium_yield - expected_yield) < 0.01, f"Premium yield mismatch: {metrics.premium_yield} vs {expected_yield}"
    
    print("  ✓ Metrics calculations verified")
    return True


def test_option_scoring():
    """Test option scoring"""
    print("\nTesting option scoring...")
    
    from models.risk_profiles import RiskProfile
    from strategy.option_scorer import OptionScorer
    from data_ingestion.options_scraper import OptionContract
    
    # Create test contracts
    expiration = datetime.now() + timedelta(days=30)
    contracts = [
        OptionContract(
            ticker="AAPL",
            contract_type="CALL",
            strike=180.0,
            expiration=expiration,
            bid=2.40,
            ask=2.60,
            delta=0.35,
            volume=1000,
            open_interest=5000
        ),
        OptionContract(
            ticker="AAPL",
            contract_type="CALL",
            strike=185.0,
            expiration=expiration,
            bid=1.20,
            ask=1.40,
            delta=0.20,
            volume=500,
            open_interest=3000
        ),
    ]
    
    scorer = OptionScorer(RiskProfile.MODERATE)
    scored = scorer.score_contracts(contracts, stock_price=175.00)
    
    print(f"  Scored {len(scored)} contracts")
    for opt in scored:
        print(f"    Rank {opt.rank}: ${opt.strike} strike, score={opt.score:.2f}")
    
    assert len(scored) == 2
    assert scored[0].rank == 1
    
    print("  ✓ Scoring verified")
    return True


def test_recommendation_engine():
    """Test recommendation engine"""
    print("\nTesting recommendation engine...")
    
    from models.risk_profiles import RiskProfile
    from models.options import OptionMetrics, ScoredOption
    from strategy.recommendation import RecommendationEngine
    
    # Create a scored option
    expiration = datetime.now() + timedelta(days=30)
    metrics = OptionMetrics.calculate(
        stock_price=175.00,
        strike=180.00,
        premium=2.50,
        expiration=expiration,
        delta=0.35
    )
    
    option = ScoredOption(
        ticker="AAPL",
        strike=180.00,
        expiration=expiration,
        premium=2.50,
        delta=0.35,
        metrics=metrics,
        score=70.0,
        rank=1
    )
    
    engine = RecommendationEngine(RiskProfile.MODERATE)
    rec = engine.generate_recommendation("AAPL", option, [option])
    
    print(f"  Action: {rec.action.value}")
    print(f"  Confidence: {rec.confidence}")
    print(f"  Explanation: {rec.explanation[:80]}...")
    
    assert rec.action.value in ["SELL", "HOLD"]
    
    print("  ✓ Recommendation engine verified")
    return True


def test_demo_mode():
    """Test demo mode (mock data)"""
    print("\nTesting demo mode...")
    
    from demo_mode import get_demo_stock_client, get_demo_options_scraper
    
    stock_client = get_demo_stock_client()
    options_scraper = get_demo_options_scraper()
    
    # Test stock price
    price = stock_client.get_current_price("AAPL")
    print(f"  AAPL price: ${price.price:.2f}")
    assert price.price > 0
    
    # Test option chain
    chains = options_scraper.get_all_expirations("AAPL", max_expirations=2)
    print(f"  Expirations fetched: {len(chains)}")
    
    total_contracts = sum(len(c) for c in chains.values())
    print(f"  Total contracts: {total_contracts}")
    assert total_contracts > 0
    
    print("  ✓ Demo mode verified")
    return True


def test_api_schemas():
    """Test API request/response schemas"""
    print("\nTesting API schemas...")
    
    from api.schemas import (
        PortfolioEvaluationRequest,
        PortfolioEvaluationResponse,
        CoveredCallRecommendationRequest,
        HealthCheckResponse,
    )
    
    # Test request validation
    req = PortfolioEvaluationRequest(
        positions=[
            {"ticker": "AAPL", "shares": 200, "cost_basis": 150.00}
        ],
        risk_profile="moderate"
    )
    print(f"  Request validated: {len(req.positions)} positions")
    
    # Test response
    resp = HealthCheckResponse(
        status="healthy",
        timestamp=datetime.now(),
        services={"api": "ok"}
    )
    print(f"  Response validated: status={resp.status}")
    
    print("  ✓ API schemas verified")
    return True


def run_all_tests():
    """Run all tests"""
    print("=" * 60)
    print("COVERED CALL DASHBOARD - TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Imports", test_imports),
        ("Risk Profiles", test_risk_profiles),
        ("Portfolio Model", test_portfolio_model),
        ("Option Metrics", test_option_metrics),
        ("Option Scoring", test_option_scoring),
        ("Recommendation Engine", test_recommendation_engine),
        ("Demo Mode", test_demo_mode),
        ("API Schemas", test_api_schemas),
    ]
    
    results = []
    for name, test_fn in tests:
        try:
            passed = test_fn()
            results.append((name, passed))
        except Exception as e:
            print(f"\n  ✗ EXCEPTION: {e}")
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

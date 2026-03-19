"""
Covered Call Dashboard - Quick Start Script

This script demonstrates how to run the complete system.
"""

import asyncio
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, ".")


def demo_portfolio_analysis():
    """
    Demonstrate portfolio analysis with demo data
    """
    print("=" * 70)
    print("COVERED CALL DASHBOARD - DEMO")
    print("=" * 70)
    
    # Import required modules
    from models.portfolio import Portfolio, Position
    from models.risk_profiles import RiskProfile, get_risk_profile_config
    from models.options import OptionMetrics
    from strategy.option_scorer import OptionScorer
    from strategy.recommendation import RecommendationEngine
    from demo_mode import get_demo_stock_client, get_demo_options_scraper
    
    # Create demo clients
    stock_client = get_demo_stock_client()
    options_scraper = get_demo_options_scraper()
    
    # Create sample portfolio
    portfolio = Portfolio(
        positions=[
            Position(ticker="AAPL", shares=200, cost_basis=150.00),
            Position(ticker="MSFT", shares=150, cost_basis=300.00),
            Position(ticker="TSLA", shares=100, cost_basis=200.00),
            Position(ticker="GOOGL", shares=50),  # Not eligible (< 100 shares)
        ],
        risk_profile=RiskProfile.MODERATE
    )
    
    print(f"\n📊 Portfolio Summary")
    print("-" * 40)
    print(f"Total Positions: {portfolio.total_positions}")
    print(f"Eligible for Covered Calls: {portfolio.eligible_count}")
    print(f"Risk Profile: {portfolio.risk_profile.value}")
    
    # Analyze each eligible position
    for position in portfolio.eligible_positions:
        print(f"\n{'='*70}")
        print(f"📈 {position.ticker} Analysis")
        print(f"{'='*70}")
        
        # Get current price
        price_data = stock_client.get_current_price(position.ticker)
        print(f"\nShares: {position.shares}")
        print(f"Contracts Available: {position.max_contracts}")
        print(f"Current Price: ${price_data.price:.2f}")
        
        if position.cost_basis:
            unrealized_pnl = (price_data.price - position.cost_basis) * position.shares
            pnl_pct = ((price_data.price - position.cost_basis) / position.cost_basis) * 100
            print(f"Cost Basis: ${position.cost_basis:.2f}")
            print(f"Unrealized P&L: ${unrealized_pnl:,.2f} ({pnl_pct:+.1f}%)")
        
        # Get option chains
        option_chains = options_scraper.get_all_expirations(position.ticker, max_expirations=3)
        
        # Flatten all contracts
        all_contracts = []
        for contracts in option_chains.values():
            all_contracts.extend(contracts)
        
        print(f"\nOptions Found: {len(all_contracts)} contracts across {len(option_chains)} expirations")
        
        # Score contracts based on risk profile
        scorer = OptionScorer(portfolio.risk_profile)
        scored_options = scorer.score_contracts(all_contracts, price_data.price)
        
        # Generate recommendation
        rec_engine = RecommendationEngine(portfolio.risk_profile)
        best_option = scored_options[0] if scored_options else None
        recommendation = rec_engine.generate_recommendation(
            position.ticker,
            best_option,
            scored_options
        )
        
        # Display recommendation
        print(f"\n🎯 RECOMMENDATION: {recommendation.action.value}")
        print(f"Confidence: {recommendation.confidence.upper()}")
        
        if recommendation.recommended_contract:
            rc = recommendation.recommended_contract
            print(f"\n📝 Recommended Contract:")
            print(f"   Strike: ${rc['strike']}")
            print(f"   Expiration: {rc['expiration']}")
            print(f"   Premium: ${rc['premium']:.2f}")
            if rc.get('delta'):
                print(f"   Delta: {rc['delta']:.2f}")
        
        if recommendation.metrics:
            m = recommendation.metrics
            print(f"\n📊 Key Metrics:")
            print(f"   Premium Yield: {m['premium_yield']:.2f}%")
            print(f"   Annualized Return: {m['annualized_return']:.1f}%")
            print(f"   Max Profit: ${m['max_profit']:.2f}")
            print(f"   Downside Protection: {m['downside_protection']:.2f}%")
            print(f"   Break-Even Price: ${m['break_even_price']:.2f}")
            if m.get('assignment_probability'):
                print(f"   Assignment Probability: {m['assignment_probability']:.0f}%")
            print(f"   Days to Expiration: {m['days_to_expiration']}")
        
        print(f"\n💡 Explanation:")
        print(f"   {recommendation.explanation}")
        
        if recommendation.warnings:
            print(f"\n⚠️ Warnings:")
            for warning in recommendation.warnings:
                print(f"   • {warning}")
        
        if recommendation.alternative_contracts:
            print(f"\n🔄 Alternative Contracts:")
            for alt in recommendation.alternative_contracts[:3]:
                print(f"   • ${alt['strike']} strike, {alt['expiration']}, ${alt['premium']:.2f} premium (score: {alt['score']:.1f})")


def print_risk_profile_details():
    """Print risk profile configurations"""
    from models.risk_profiles import RiskProfile, get_risk_profile_config
    
    print("\n" + "=" * 70)
    print("RISK PROFILE DETAILS")
    print("=" * 70)
    
    for profile in RiskProfile:
        config = get_risk_profile_config(profile)
        print(f"\n{profile.value.upper()}")
        print("-" * 30)
        print(f"Delta Range: {config.delta_range[0]:.2f} - {config.delta_range[1]:.2f}")
        print(f"DTE Range: {config.dte_range[0]} - {config.dte_range[1]} days")
        print(f"Min Premium Yield: {config.min_premium_yield:.1%}")
        print(f"Max Assignment Risk: {config.max_assignment_risk:.0%}")
        print(f"Description: {config.description}")


def print_startup_instructions():
    """Print instructions for starting the server"""
    print("\n" + "=" * 70)
    print("🚀 HOW TO RUN THE API SERVER")
    print("=" * 70)
    print("""
1. Install dependencies:
   pip install -r requirements.txt

2. (Optional) Configure API key for real data:
   Create .env file with: TWELVE_DATA_API_KEY=your_key_here
   
   Without API key, the system runs in DEMO MODE with realistic mock data.

3. Start the server:
   uvicorn api.main:app --reload

4. Access the API:
   - Swagger UI: http://localhost:8000/docs
   - ReDoc: http://localhost:8000/redoc
   - Health Check: http://localhost:8000/health

5. Example API calls:

   # Portfolio Evaluation
   curl -X POST http://localhost:8000/portfolio/evaluate \\
     -H "Content-Type: application/json" \\
     -d '{"positions": [{"ticker": "AAPL", "shares": 200}], "risk_profile": "moderate"}'

   # Covered Call Recommendation
   curl -X POST http://localhost:8000/covered-calls/recommendation \\
     -H "Content-Type: application/json" \\
     -d '{"ticker": "AAPL", "shares": 200, "risk_profile": "moderate"}'
""")


if __name__ == "__main__":
    print("\n" + "🏦 " * 20 + "\n")
    print("     COVERED CALL DASHBOARD")
    print("     Decision Support System for Covered Call Strategies")
    print("\n" + "🏦 " * 20)
    
    # Run demo analysis
    demo_portfolio_analysis()
    
    # Show risk profiles
    print_risk_profile_details()
    
    # Show startup instructions
    print_startup_instructions()
    
    print("\n" + "=" * 70)
    print("✅ DEMO COMPLETE")
    print("=" * 70 + "\n")

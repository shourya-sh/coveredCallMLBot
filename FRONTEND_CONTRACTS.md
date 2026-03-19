# Frontend Data Contracts

This document defines the exact JSON contracts for React Native mobile app consumption.

## Base URL

Development: `http://localhost:8000`
Production: Configure via environment variable

---

## 1. Health Check

### GET /health

Check API status before making requests.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2026-01-27T10:30:00.000Z",
  "services": {
    "twelve_data_api": "configured",
    "options_scraper": "ready"
  }
}
```

**TypeScript Interface:**
```typescript
interface HealthCheckResponse {
  status: "healthy" | "unhealthy";
  timestamp: string; // ISO 8601
  services: {
    twelve_data_api: "configured" | "not_configured";
    options_scraper: "ready" | "error";
  };
}
```

---

## 2. Portfolio Evaluation

### POST /portfolio/evaluate

Analyze portfolio for covered call eligibility.

**Request:**
```json
{
  "positions": [
    {
      "ticker": "AAPL",
      "shares": 200,
      "cost_basis": 150.00
    },
    {
      "ticker": "MSFT",
      "shares": 150,
      "cost_basis": 300.00
    },
    {
      "ticker": "GOOGL",
      "shares": 50
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
      "cost_basis": 150.00,
      "current_price": 175.50,
      "contracts_available": 2,
      "is_eligible": true,
      "reason": null
    },
    {
      "ticker": "MSFT",
      "shares": 150,
      "cost_basis": 300.00,
      "current_price": 420.25,
      "contracts_available": 1,
      "is_eligible": true,
      "reason": null
    },
    {
      "ticker": "GOOGL",
      "shares": 50,
      "cost_basis": null,
      "current_price": 180.75,
      "contracts_available": 0,
      "is_eligible": false,
      "reason": "Requires at least 100 shares for covered calls"
    }
  ],
  "total_positions": 3,
  "eligible_count": 2,
  "risk_profile": "moderate",
  "analysis_timestamp": "2026-01-27T10:30:00.000Z"
}
```

**TypeScript Interface:**
```typescript
interface Position {
  ticker: string;
  shares: number;
  cost_basis?: number | null;
}

interface PortfolioEvaluationRequest {
  positions: Position[];
  risk_profile: "conservative" | "moderate" | "aggressive";
}

interface EligiblePosition {
  ticker: string;
  shares: number;
  cost_basis: number | null;
  current_price: number;
  contracts_available: number;
  is_eligible: boolean;
  reason: string | null;
}

interface PortfolioEvaluationResponse {
  eligible_positions: EligiblePosition[];
  total_positions: number;
  eligible_count: number;
  risk_profile: string;
  analysis_timestamp: string;
}
```

---

## 3. Covered Call Recommendation

### POST /covered-calls/recommendation

Get recommendation for a specific position.

**Request:**
```json
{
  "ticker": "AAPL",
  "shares": 200,
  "cost_basis": 150.00,
  "risk_profile": "moderate"
}
```

**Response (SELL):**
```json
{
  "action": "SELL",
  "ticker": "AAPL",
  "risk_profile": "moderate",
  "recommended_contract": {
    "strike": 180.0,
    "expiration": "2026-02-21",
    "premium": 2.50,
    "delta": 0.35
  },
  "metrics": {
    "premium_yield": 1.43,
    "annualized_return": 18.56,
    "max_profit": 750.00,
    "downside_protection": 1.43,
    "break_even_price": 173.00,
    "assignment_probability": 35.0,
    "days_to_expiration": 25
  },
  "explanation": "Strong covered call opportunity. This $180 strike offers 18.6% annualized return with 1.43% premium yield. Moderate assignment risk (35% probability) balances income and potential appreciation. Provides 1.43% downside protection with break-even at $173.00. Medium-term 25-day expiration balances theta decay and flexibility.",
  "confidence": "medium",
  "alternative_contracts": [
    {
      "strike": 182.5,
      "expiration": "2026-02-21",
      "premium": 1.85,
      "score": 68.5
    },
    {
      "strike": 177.5,
      "expiration": "2026-02-21",
      "premium": 3.40,
      "score": 62.3
    }
  ],
  "warnings": [],
  "timestamp": "2026-01-27T10:30:00.000Z"
}
```

**Response (HOLD):**
```json
{
  "action": "HOLD",
  "ticker": "AAPL",
  "risk_profile": "moderate",
  "recommended_contract": null,
  "metrics": null,
  "explanation": "No suitable covered call contracts found for AAPL that match your moderate risk profile. This could be due to low option liquidity, unfavorable strike prices, or expiration dates outside your preferred range.",
  "confidence": "high",
  "alternative_contracts": [],
  "warnings": [],
  "timestamp": "2026-01-27T10:30:00.000Z"
}
```

**TypeScript Interface:**
```typescript
interface CoveredCallRequest {
  ticker: string;
  shares: number;
  cost_basis?: number | null;
  risk_profile: "conservative" | "moderate" | "aggressive";
}

interface ContractDetails {
  strike: number;
  expiration: string; // YYYY-MM-DD
  premium: number;
  delta: number | null;
}

interface Metrics {
  premium_yield: number;       // Percentage (1.43 = 1.43%)
  annualized_return: number;   // Percentage
  max_profit: number;          // Dollar amount
  downside_protection: number; // Percentage
  break_even_price: number;    // Dollar amount
  assignment_probability: number | null; // Percentage
  days_to_expiration: number;
}

interface AlternativeContract {
  strike: number;
  expiration: string;
  premium: number;
  score: number;
}

interface CoveredCallRecommendationResponse {
  action: "SELL" | "HOLD";
  ticker: string;
  risk_profile: string;
  recommended_contract: ContractDetails | null;
  metrics: Metrics | null;
  explanation: string;
  confidence: "high" | "medium" | "low";
  alternative_contracts: AlternativeContract[];
  warnings: string[];
  timestamp: string;
}
```

---

## 4. Error Response

All endpoints may return an error response:

```json
{
  "detail": "Error message describing what went wrong"
}
```

**HTTP Status Codes:**
- `200` - Success
- `400` - Bad Request (validation error)
- `502` - Bad Gateway (external API failure)
- `503` - Service Unavailable (API key not configured)
- `500` - Internal Server Error

**TypeScript Interface:**
```typescript
interface ErrorResponse {
  detail: string;
}
```

---

## 5. React Native Integration Example

```typescript
// api/coveredCalls.ts
import axios from 'axios';

const API_BASE = 'http://localhost:8000';

export async function evaluatePortfolio(
  positions: Position[],
  riskProfile: string
): Promise<PortfolioEvaluationResponse> {
  const response = await axios.post(`${API_BASE}/portfolio/evaluate`, {
    positions,
    risk_profile: riskProfile,
  });
  return response.data;
}

export async function getRecommendation(
  ticker: string,
  shares: number,
  costBasis: number | null,
  riskProfile: string
): Promise<CoveredCallRecommendationResponse> {
  const response = await axios.post(`${API_BASE}/covered-calls/recommendation`, {
    ticker,
    shares,
    cost_basis: costBasis,
    risk_profile: riskProfile,
  });
  return response.data;
}

export async function checkHealth(): Promise<HealthCheckResponse> {
  const response = await axios.get(`${API_BASE}/health`);
  return response.data;
}
```

---

## 6. Mobile Display Guidelines

### Portfolio Summary Screen
Display:
- Total positions count
- Eligible positions count
- List of positions with eligibility badges
- Current price and unrealized P&L

### Recommendation Detail Screen
Display:
- Action badge (SELL/HOLD) with confidence indicator
- Recommended contract card with strike, expiration, premium
- Metrics in organized grid:
  - Premium Yield (with trend indicator)
  - Annualized Return (highlighted)
  - Max Profit (dollar format)
  - Downside Protection (percentage)
  - Break-even Price (dollar format)
  - Assignment Probability (with risk color)
  - Days to Expiration
- Explanation text (full width, readable)
- Warnings as alert cards
- Alternative contracts as scrollable list

### Risk Profile Selector
Show descriptions for each profile:
- **Conservative**: Low risk, stable income
- **Moderate**: Balanced approach
- **Aggressive**: Maximum premium

### Color Coding Suggestions
- SELL action: Green
- HOLD action: Yellow/Orange
- High confidence: Green border
- Low confidence: Red border
- Warnings: Red/Orange

---

## 7. Metrics Explanation (For Help Text)

| Metric | Description |
|--------|-------------|
| Premium Yield | Income received as percentage of stock value |
| Annualized Return | Projected yearly return if strategy repeated |
| Max Profit | Best-case profit per contract if stock at strike |
| Downside Protection | Stock can drop this % before losing money |
| Break-even Price | Stock price where position has zero gain/loss |
| Assignment Probability | Estimated chance shares get called away |
| Days to Expiration | Time until option expires |

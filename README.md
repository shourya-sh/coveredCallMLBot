# CoveredCallMLBot

Backend-focused covered call dashboard with an options strategy classifier.
Backend now uses Supabase.

## Setup

1) Create `backend/.env` from `backend/.env.example`.

## Run

```bash
docker compose up -d --build
```

## Logs

Backend logs:

```bash
docker compose logs -f backend
```

Frontend logs:

```bash
docker compose logs -f frontend
```

## Train model

```bash
docker compose exec backend python -m scripts.train_model
```

## Strategy classes

The strategy enum supports 5 outcomes:

- `BULL_CALL_SPREAD`
- `BEAR_PUT_SPREAD`
- `IRON_CONDOR`
- `LONG_STRADDLE`
- `NO_TRADE`

Current trained artifact is using 4 learned labels (all except `NO_TRADE`), and backend logic can still output `NO_TRADE` as a safety fallback.

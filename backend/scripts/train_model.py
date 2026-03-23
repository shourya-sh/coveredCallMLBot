"""
CLI to train the options strategy model.

Usage (from backend/):
    python -m scripts.train_model
    python -m scripts.train_model --tickers AAPL,MSFT,NVDA --limit 1825
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from ml.train import train, TICKERS


def main():
    parser = argparse.ArgumentParser(description="Train options strategy classifier")
    parser.add_argument("--tickers", default=",".join(TICKERS), help="Comma-separated tickers")
    parser.add_argument("--limit", type=int, default=1825, help="Max candle bars per ticker")
    parser.add_argument("--horizon", type=int, default=10, help="Lookahead bars for labeling")
    parser.add_argument("--model-type", choices=["random_forest", "gradient_boosting"], default="random_forest")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    summary = train(
        tickers=tickers,
        limit=args.limit,
        horizon_bars=args.horizon,
        model_type=args.model_type,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

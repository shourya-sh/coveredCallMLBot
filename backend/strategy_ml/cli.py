from __future__ import annotations

import argparse
import json
from pathlib import Path

from strategy_ml.predict import StrategyPredictor
from strategy_ml.train_model import train


DEFAULT_MODEL_PATH = str(Path(__file__).resolve().parent / "artifacts" / "options_strategy_model.joblib")


def main() -> None:
    parser = argparse.ArgumentParser(description="Options strategy ML CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    train_cmd = sub.add_parser("train", help="Train and persist model")
    train_cmd.add_argument("--tickers", default="AAPL,MSFT,GOOGL,TSLA,NVDA,META,AMZN,AMD,JPM,V")
    train_cmd.add_argument("--interval", default="1day")
    train_cmd.add_argument("--limit", type=int, default=700)
    train_cmd.add_argument("--horizon", type=int, default=10)
    train_cmd.add_argument("--model-type", choices=["random_forest", "gradient_boosting"], default="random_forest")
    train_cmd.add_argument("--output", default=DEFAULT_MODEL_PATH)

    predict_cmd = sub.add_parser("predict", help="Predict strategy for a ticker")
    predict_cmd.add_argument("--ticker", required=True)
    predict_cmd.add_argument("--model", default=DEFAULT_MODEL_PATH)
    predict_cmd.add_argument("--interval", default="1day")

    args = parser.parse_args()

    if args.command == "train":
        summary = train(
            tickers=[t.strip().upper() for t in args.tickers.split(",") if t.strip()],
            interval=args.interval,
            limit=args.limit,
            horizon_bars=args.horizon,
            model_type=args.model_type,
            output_model_path=args.output,
        )
        print(json.dumps(summary, indent=2))
        return

    predictor = StrategyPredictor(model_path=args.model)
    result = predictor.predict_ticker(args.ticker, interval=args.interval)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

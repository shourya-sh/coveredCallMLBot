from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

from strategy_ml.backtester import StrategyBacktester
from strategy_ml.data_loader import CandleDataLoader
from strategy_ml.feature_engineering import build_feature_frame
from strategy_ml.label_generator import generate_performance_optimized_labels, generate_rule_based_labels
from strategy_ml.types import MODEL_FEATURE_COLUMNS, StrategyClass


def default_model_artifact_path() -> str:
    return str(Path(__file__).resolve().parent / "artifacts" / "options_strategy_model.joblib")


def _time_series_split(df: pd.DataFrame, train_ratio: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("datetime").reset_index(drop=True)
    split_idx = max(1, int(len(df) * train_ratio))
    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


def build_training_dataset(
    tickers: list[str],
    interval: str,
    limit: int,
    horizon_bars: int,
    loader: CandleDataLoader,
) -> pd.DataFrame:
    spy = loader.load_candles("SPY", interval=interval, limit=limit)
    dataset = []

    for ticker in tickers:
        candles = loader.load_candles(ticker, interval=interval, limit=limit)
        if candles.empty or len(candles) < 120:
            continue

        feat = build_feature_frame(candles, spy_candles=spy)
        feat["rule_label"] = generate_rule_based_labels(feat)
        feat["strategy_label"] = generate_performance_optimized_labels(feat, horizon_bars=horizon_bars)
        feat["ticker"] = ticker
        dataset.append(feat)

    if not dataset:
        return pd.DataFrame()

    full = pd.concat(dataset, axis=0, ignore_index=True)
    full = full.dropna(subset=["strategy_label", "datetime"]).reset_index(drop=True)
    return full


def train(
    tickers: list[str],
    interval: str = "1day",
    limit: int = 600,
    horizon_bars: int = 10,
    model_type: str = "random_forest",
    output_model_path: str | None = None,
) -> dict:
    output_model_path = output_model_path or default_model_artifact_path()
    loader = CandleDataLoader()
    data = build_training_dataset(tickers, interval, limit, horizon_bars, loader)
    if data.empty:
        raise RuntimeError("No training samples available. Check Postgres candles data and ticker list.")

    features = data[["datetime"] + MODEL_FEATURE_COLUMNS + ["strategy_label"]].copy()
    features = features.replace([np.inf, -np.inf], np.nan)
    features = features.dropna(subset=["strategy_label"]).reset_index(drop=True)

    train_df, test_df = _time_series_split(features, train_ratio=0.8)

    x_train = train_df[MODEL_FEATURE_COLUMNS]
    x_test = test_df[MODEL_FEATURE_COLUMNS]
    y_train_raw = train_df["strategy_label"].astype(str)
    y_test_raw = test_df["strategy_label"].astype(str)

    label_encoder = LabelEncoder()
    y_train = label_encoder.fit_transform(y_train_raw)

    seen = set(label_encoder.classes_)
    mask = y_test_raw.isin(seen)
    x_test = x_test.loc[mask]
    y_test_raw = y_test_raw.loc[mask]
    y_test = label_encoder.transform(y_test_raw) if len(y_test_raw) else np.array([])

    if model_type == "gradient_boosting":
        classifier = GradientBoostingClassifier(random_state=42)
    else:
        classifier = RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=8,
            random_state=42,
            class_weight="balanced_subsample",
            n_jobs=-1,
        )

    pipeline = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("model", classifier),
        ]
    )
    pipeline.fit(x_train, y_train)

    preds = pipeline.predict(x_test) if len(x_test) else np.array([])
    pred_labels = label_encoder.inverse_transform(preds) if len(preds) else np.array([])

    acc = float(accuracy_score(y_test, preds)) if len(y_test) > 0 else 0.0
    cm = confusion_matrix(y_test_raw, pred_labels, labels=label_encoder.classes_).tolist() if len(y_test_raw) else []
    report = (
        classification_report(
            y_test_raw,
            pred_labels,
            labels=list(label_encoder.classes_),
            output_dict=True,
            zero_division=0,
        )
        if len(y_test_raw)
        else {}
    )

    bt = StrategyBacktester()
    eval_df = test_df.loc[x_test.index] if len(x_test) else test_df.iloc[0:0]
    backtest_stats = bt.evaluate_predicted_signals(eval_df, pd.Series(pred_labels), horizon_bars=horizon_bars)

    feature_importance = {}
    model = pipeline.named_steps["model"]
    if hasattr(model, "feature_importances_"):
        for col, val in zip(MODEL_FEATURE_COLUMNS, model.feature_importances_):
            feature_importance[col] = float(val)

    artifact = {
        "pipeline": pipeline,
        "label_encoder": label_encoder,
        "feature_columns": MODEL_FEATURE_COLUMNS,
        "metadata": {
            "model_type": model_type,
            "interval": interval,
            "limit": limit,
            "horizon_bars": horizon_bars,
            "tickers": tickers,
        },
    }

    out_path = Path(output_model_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, out_path)

    summary = {
        "model_path": str(out_path),
        "samples_total": int(len(features)),
        "samples_train": int(len(train_df)),
        "samples_test": int(len(test_df)),
        "accuracy": acc,
        "confusion_matrix": cm,
        "labels": list(label_encoder.classes_),
        "classification_report": report,
        "feature_importance": feature_importance,
        "backtest": backtest_stats,
    }

    metrics_path = out_path.with_suffix(".metrics.json")
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train options strategy classifier")
    parser.add_argument(
        "--tickers",
        default="AAPL,MSFT,GOOGL,TSLA,NVDA,META,AMZN,AMD,JPM,V",
        help="Comma-separated ticker list",
    )
    parser.add_argument("--interval", default="1day")
    parser.add_argument("--limit", type=int, default=700)
    parser.add_argument("--horizon", type=int, default=10)
    parser.add_argument("--model-type", choices=["random_forest", "gradient_boosting"], default="random_forest")
    parser.add_argument("--output", default=default_model_artifact_path())
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    summary = train(
        tickers=tickers,
        interval=args.interval,
        limit=args.limit,
        horizon_bars=args.horizon,
        model_type=args.model_type,
        output_model_path=args.output,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

from __future__ import annotations

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

from ml.features import build_features
from ml.labels import generate_labels, evaluate_predictions
from ml.types import FEATURE_COLUMNS, StrategyClass

ARTIFACT_PATH = Path(__file__).parent / "artifacts" / "options_strategy_model.joblib"
TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMZN", "MSFT", "META"]


def _load_candles(ticker: str, interval: str = "1day", limit: int = 1825) -> pd.DataFrame:
    import db
    rows = db.load_candles(ticker, interval=interval, limit=limit)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
    return df


def _time_split(df: pd.DataFrame, train_ratio: float = 0.8):
    df = df.sort_values("datetime").reset_index(drop=True)
    split = max(1, int(len(df) * train_ratio))
    return df.iloc[:split].copy(), df.iloc[split:].copy()


def build_dataset(
    tickers: list[str],
    interval: str = "1day",
    limit: int = 1825,
    horizon_bars: int = 10,
) -> pd.DataFrame:
    spy = _load_candles("SPY", interval=interval, limit=limit)
    rows = []

    for ticker in tickers:
        candles = _load_candles(ticker, interval=interval, limit=limit)
        if candles.empty or len(candles) < 120:
            print(f"  [train] Skipping {ticker} — not enough data ({len(candles)} bars)")
            continue

        print(f"  [train] {ticker}: {len(candles)} candles → building features...", flush=True)
        feat = build_features(candles, spy_candles=spy)
        print(f"  [train] {ticker}: generating labels (simulating 4 strategies × {len(feat)} rows)...", flush=True)
        feat["label"] = generate_labels(feat, horizon_bars=horizon_bars)
        dist = feat["label"].value_counts().to_dict()
        print(f"  [train] {ticker}: label distribution: {dist}")
        feat["ticker"] = ticker
        rows.append(feat)

    if not rows:
        return pd.DataFrame()

    return pd.concat(rows, ignore_index=True).dropna(subset=["label", "datetime"]).reset_index(drop=True)


def train(
    tickers: list[str] = TICKERS,
    interval: str = "1day",
    limit: int = 1825,
    horizon_bars: int = 10,
    model_type: str = "random_forest",
    output_path: str | None = None,
) -> dict:
    output_path = Path(output_path or ARTIFACT_PATH)
    print(f"[train] Building dataset for {len(tickers)} tickers...")
    data = build_dataset(tickers, interval=interval, limit=limit, horizon_bars=horizon_bars)

    if data.empty:
        raise RuntimeError("No training data. Run the price scraper first to populate the database.")

    features = data[["datetime"] + FEATURE_COLUMNS + ["label"]].copy()
    features = features.replace([np.inf, -np.inf], np.nan).dropna(subset=["label"]).reset_index(drop=True)
    overall_dist = features["label"].value_counts().to_dict()
    print(f"[train] {len(features)} usable samples across {len(tickers)} tickers")
    print(f"[train] Overall label distribution: {overall_dist}")

    train_df, test_df = _time_split(features)
    print(f"[train] Train/test split: {len(train_df)} train / {len(test_df)} test (80/20 time-ordered)")

    x_train = train_df[FEATURE_COLUMNS]
    x_test = test_df[FEATURE_COLUMNS]
    y_train_raw = train_df["label"].astype(str)
    y_test_raw = test_df["label"].astype(str)

    le = LabelEncoder()
    y_train = le.fit_transform(y_train_raw)
    mask = y_test_raw.isin(set(le.classes_))
    x_test, y_test_raw = x_test.loc[mask], y_test_raw.loc[mask]
    y_test = le.transform(y_test_raw) if len(y_test_raw) else np.array([])

    print(f"[train] Classes: {list(le.classes_)}")
    print(f"[train] Fitting {model_type} on {len(x_train)} samples × {len(FEATURE_COLUMNS)} features...", flush=True)

    classifier = (
        GradientBoostingClassifier(random_state=42)
        if model_type == "gradient_boosting"
        else RandomForestClassifier(
            n_estimators=300,
            max_depth=8,
            min_samples_leaf=8,
            class_weight="balanced_subsample",
            random_state=42,
            n_jobs=-1,
        )
    )

    pipeline = Pipeline([("imputer", SimpleImputer(strategy="median")), ("model", classifier)])
    pipeline.fit(x_train, y_train)
    print(f"[train] Fit complete. Evaluating on {len(x_test)} test samples...", flush=True)

    preds = pipeline.predict(x_test) if len(x_test) else np.array([])
    pred_labels = le.inverse_transform(preds) if len(preds) else np.array([])
    acc = float(accuracy_score(y_test, preds)) if len(y_test) else 0.0

    feature_importance = {}
    model = pipeline.named_steps["model"]
    if hasattr(model, "feature_importances_"):
        feature_importance = dict(zip(FEATURE_COLUMNS, map(float, model.feature_importances_)))
        top5 = sorted(feature_importance.items(), key=lambda x: -x[1])[:5]
        print(f"[train] Top 5 features: {top5}")

    backtest = evaluate_predictions(
        test_df.loc[x_test.index] if len(x_test) else test_df.iloc[0:0],
        pd.Series(pred_labels),
        horizon_bars=horizon_bars,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "label_encoder": le, "feature_columns": FEATURE_COLUMNS}, output_path)

    cr = (
        classification_report(y_test_raw, pred_labels, labels=list(le.classes_), output_dict=True, zero_division=0)
        if len(y_test_raw) else {}
    )

    summary = {
        "model_path": str(output_path),
        "samples_total": len(features),
        "samples_train": len(train_df),
        "samples_test": len(test_df),
        "accuracy": acc,
        "labels": list(le.classes_),
        "classification_report": cr,
        "feature_importance": feature_importance,
        "backtest": backtest,
    }

    output_path.with_suffix(".metrics.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'='*50}")
    print(f"[train] Accuracy: {acc:.2%}")
    print(f"[train] Backtest — trades: {backtest['trades']}, win rate: {backtest['win_rate']:.1%}, avg return/trade: {backtest['avg_return_per_trade']:.4f}")
    if cr:
        print("[train] Per-class F1:")
        for cls in le.classes_:
            f1 = cr.get(cls, {}).get("f1-score", 0)
            support = cr.get(cls, {}).get("support", 0)
            print(f"  {cls:<25} f1={f1:.2f}  support={support}")
    print(f"[train] Model saved → {output_path}")
    print(f"{'='*50}\n")

    return summary

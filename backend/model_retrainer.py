from __future__ import annotations

import json
import os
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from strategy_ml.train_model import train


TRAIN_TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "TSLA", "NVDA", "AMZN", "MSFT", "META", "SPX"]
CHECK_INTERVAL_SECONDS = int(os.getenv("MODEL_RETRAIN_CHECK_SECONDS", "900"))
RETRAIN_AFTER_HOUR_ET = int(os.getenv("MODEL_RETRAIN_AFTER_HOUR_ET", "17"))
RETRAIN_AFTER_MINUTE_ET = int(os.getenv("MODEL_RETRAIN_AFTER_MINUTE_ET", "45"))
STATE_PATH = Path(__file__).resolve().parent / "strategy_ml" / "artifacts" / "last_retrain.json"

_thread: threading.Thread | None = None
_lock = threading.Lock()


def _load_last_retrain_date() -> str | None:
    if not STATE_PATH.exists():
        return None
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return payload.get("last_retrain_date")
    except Exception:
        return None


def _save_last_retrain_date(date_str: str, summary: dict | None = None) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "last_retrain_date": date_str,
        "updated_at": datetime.utcnow().isoformat(),
        "summary": summary or {},
    }
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _eligible_run_time(now_et: datetime) -> bool:
    if now_et.weekday() >= 5:
        return False
    cutoff = now_et.replace(
        hour=RETRAIN_AFTER_HOUR_ET,
        minute=RETRAIN_AFTER_MINUTE_ET,
        second=0,
        microsecond=0,
    )
    return now_et >= cutoff


def _run_retrain_once_if_due() -> None:
    now_et = datetime.now(ZoneInfo("America/New_York"))
    today = now_et.date().isoformat()
    if not _eligible_run_time(now_et):
        return

    if _load_last_retrain_date() == today:
        return

    with _lock:
        if _load_last_retrain_date() == today:
            return

        print(f"[retrainer] Starting nightly retrain for {today}...")
        try:
            summary = train(
                tickers=TRAIN_TICKERS,
                interval="1day",
                limit=1200,
                horizon_bars=7,
                model_type="random_forest",
            )
            _save_last_retrain_date(today, summary)
            print(
                f"[retrainer] Retrain complete: samples={summary.get('samples_total')} "
                f"accuracy={summary.get('accuracy')}"
            )
        except Exception as exc:
            print(f"[retrainer] Retrain failed: {exc}")
            traceback.print_exc()


def _run_loop() -> None:
    while True:
        try:
            _run_retrain_once_if_due()
        except Exception:
            traceback.print_exc()
        time.sleep(max(300, CHECK_INTERVAL_SECONDS))


def start_background_retrainer() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return

    _thread = threading.Thread(target=_run_loop, daemon=True)
    _thread.start()
    print(
        f"[retrainer] Background retrainer started — checks every "
        f"{max(300, CHECK_INTERVAL_SECONDS) // 60} min"
    )

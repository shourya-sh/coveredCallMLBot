from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent / ".env")

from scraper.prices import start_background_scraper
from routers import dashboard, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[startup] Dashy API starting up...")
    from config import settings
    print(f"[startup] Postgres: {'connected' if settings.postgres_dsn else 'NOT SET — check .env'}")
    model_path = Path(__file__).parent / "ml" / "artifacts" / "options_strategy_model.joblib"
    print(f"[startup] Model: {'found' if model_path.exists() else 'NOT FOUND — run train_model.py'}")
    start_background_scraper()
    print("[startup] Ready.")
    yield
    print("[shutdown] Dashy API shutting down.")


app = FastAPI(title="Dashy API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(dashboard.router)

from datetime import datetime
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

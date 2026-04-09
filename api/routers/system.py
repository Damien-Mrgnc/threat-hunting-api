from fastapi import APIRouter, Response, Depends
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from core.auth import get_current_admin

router = APIRouter()

@router.get("/metrics")
def metrics():
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

@router.get("/health")
def health():
    return {"status": "ok"}

from pydantic import BaseModel

class FeatureConfig(BaseModel):
    use_redis: bool = True

APP_CONFIG = FeatureConfig()

@router.get("/config/features")
def get_config():
    return APP_CONFIG

@router.post("/config/features")
def update_config(config: FeatureConfig, current_user: dict = Depends(get_current_admin)):
    global APP_CONFIG
    APP_CONFIG = config
    return {"status": "updated", "config": APP_CONFIG}

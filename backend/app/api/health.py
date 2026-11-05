from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.config import Settings, get_settings
from app.providers.registry import provider_status

router = APIRouter(prefix="/health", tags=["health"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get("")
async def health(settings: SettingsDep) -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/providers")
async def providers(settings: SettingsDep) -> dict:
    return provider_status(settings)

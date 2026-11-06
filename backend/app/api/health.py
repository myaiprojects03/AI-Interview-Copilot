from fastapi import APIRouter, Request

from app.core.deps import SettingsDep
from app.providers.registry import provider_status

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health(settings: SettingsDep) -> dict:
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/providers")
async def providers(settings: SettingsDep, request: Request) -> dict:
    status = provider_status(settings)
    store = getattr(request.app.state, "store", None)
    status["database"]["storage"] = store.name if store else None
    status["database"]["error"] = getattr(request.app.state, "store_error", None)
    return status

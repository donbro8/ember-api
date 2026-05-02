from fastapi import APIRouter
from ember_shared import settings

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok", "env": settings.ENV}

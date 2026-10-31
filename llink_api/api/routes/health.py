"""Route de disponibilité."""

from fastapi import APIRouter

from llink_api.schemas import HealthResponse

router = APIRouter()


@router.get("/", response_model=HealthResponse)
def root() -> dict[str, str]:
    return {"message": "Llink Backend API est opérationnel."}

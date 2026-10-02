"""Endpoints del catalogo de restaurantes (consumidos por todos los fronts)."""
import asyncio
import random
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.config import settings
from app.db import get_conn
from app.repositories.spots_repository import SpotsRepository
from app.schemas import ReviewCreatedOut, ReviewIn, SpotDetailOut, SpotSummaryOut
from app.security import require_user_id
from app.services.reviews_service import AlreadyReviewed, ReviewsService, SpotNotFound

router = APIRouter(prefix="/api/v1/spots", tags=["spots"])


def get_repo(conn: sqlite3.Connection = Depends(get_conn)) -> SpotsRepository:
    return SpotsRepository(conn)


@router.get("", response_model=list[SpotSummaryOut])
def list_spots(repo: SpotsRepository = Depends(get_repo)):
    return repo.list_spots()


@router.get("/{spot_id}", response_model=SpotDetailOut)
async def get_spot(spot_id: str, repo: SpotsRepository = Depends(get_repo)):
    # Inyeccion de fallas opcional (apagada por defecto) para demostrar las business questions.
    if settings.chaos_max_delay_ms:
        await asyncio.sleep(random.uniform(0, settings.chaos_max_delay_ms) / 1000)
    if random.random() < settings.chaos_failure_rate:
        raise HTTPException(status_code=503, detail="Injected failure (chaos mode)")

    spot = repo.get_spot(spot_id)
    if spot is None:
        raise HTTPException(status_code=404, detail=f"Spot '{spot_id}' not found")
    return spot

@router.post("/{spot_id}/reviews", response_model=ReviewCreatedOut, status_code=status.HTTP_201_CREATED)
def create_review(spot_id: str, body: ReviewIn, user_id: str = Depends(require_user_id),
                  conn: sqlite3.Connection = Depends(get_conn)):
    """Publica la calificacion del usuario del token (requiere sesion, la BQ10 cuenta usuarios reales)."""
    try:
        return ReviewsService(conn).submit(spot_id, user_id, body.stars, body.text)
    except SpotNotFound:
        raise HTTPException(status_code=404, detail=f"Spot '{spot_id}' not found")
    except AlreadyReviewed:
        raise HTTPException(status_code=409, detail="You already reviewed this spot")
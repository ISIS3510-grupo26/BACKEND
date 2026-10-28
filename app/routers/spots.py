"""Endpoints del catalogo de restaurantes (consumidos por todos los fronts)."""
import asyncio
import random
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import settings
from app.db import get_conn
from app.repositories.spots_repository import SpotsRepository
from app.schemas import (LastWaitTimesReport, ReviewCreatedOut, ReviewIn, SpotDetailOut, SpotSummaryOut,
                         WaitTimeReportIn, WaitTimeReportOut)
from app.security import optional_user_id, require_user_id
from app.services.reviews_service import AlreadyReviewed, ReviewsService, SpotNotFound
from app.services import wait_times_service
from app.services.wait_times_service import ReportFromFuture, WaitTimesService

router = APIRouter(prefix="/api/v1/spots", tags=["spots"])


def get_repo(conn: sqlite3.Connection = Depends(get_conn)) -> SpotsRepository:
    return SpotsRepository(conn)


def current_time() -> datetime:
    """Reloj inyectable: los tests lo reemplazan para fijar "ahora"."""
    return datetime.now(timezone.utc)


@router.get("", response_model=list[SpotSummaryOut])
def list_spots(repo: SpotsRepository = Depends(get_repo)):
    return repo.list_spots()


# Va antes de /{spot_id}: si no, FastAPI intentaria leer "wait-times" como un id de restaurante.
@router.get("/wait-times/latest", response_model=LastWaitTimesReport)
def last_wait_times(
    fresh_minutes: int = Query(120, alias="freshMinutes", ge=5, le=24 * 60,
                               description="Un reporte mas viejo que esto se marca como no reciente"),
    now: datetime = Depends(current_time),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """BQ4 (tipo 2): ultimo tiempo de espera reportado para cada restaurante."""
    return WaitTimesService(conn).last_reported(fresh_minutes, now=now)


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


@router.post("/{spot_id}/wait-times", response_model=WaitTimeReportOut, status_code=status.HTTP_201_CREATED)
def report_wait_time(spot_id: str, body: WaitTimeReportIn, now: datetime = Depends(current_time),
                     user_id: str | None = Depends(optional_user_id),
                     conn: sqlite3.Connection = Depends(get_conn)):
    """BQ4: un estudiante reporta cuanto esta esperando. El token es opcional (la app Kotlin todavia no tiene login)."""
    try:
        return WaitTimesService(conn).report(spot_id, body, user_id, now=now)
    except wait_times_service.SpotNotFound:
        raise HTTPException(status_code=404, detail=f"Spot '{spot_id}' not found")
    except ReportFromFuture:
        raise HTTPException(status_code=422, detail="reportedAt is in the future")

"""Endpoints del catalogo de restaurantes (consumidos por todos los fronts)."""
import asyncio
import random
import sqlite3
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config import settings
from app.db import get_conn
from app.repositories.spots_repository import SpotsRepository
from app.repositories.users_repository import UsersRepository
from app.schemas import (HelpfulVotesOut, LastWaitTimesReport, ReviewCreatedOut, ReviewIn, ReviewPageOut,
                         SpotDetailOut, SpotSummaryOut, WaitTimeReportIn, WaitTimeReportOut)
from app.security import get_users_repo, optional_user_id, require_user_id, resolve_acting_user, unauthorized
from app.services.reviews_service import AlreadyReviewed, ReviewNotFound, ReviewsService, SpotNotFound
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


@router.get("/{spot_id}/reviews", response_model=ReviewPageOut)
def list_reviews(
    spot_id: str,
    sort: Literal["newest", "highest", "lowest", "helpful"] = Query("newest"),
    stars: int | None = Query(None, ge=1, le=5, description="Solo reseñas con estas estrellas"),
    q: str | None = Query(None, max_length=100, description="Busca en el texto y el autor, sin distinguir mayusculas"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, alias="pageSize", ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """Todas las reseñas de un restaurante (vista "All reviews"), paginadas."""
    try:
        return ReviewsService(conn).page(spot_id, sort, stars, q, page, page_size)
    except SpotNotFound:
        raise HTTPException(status_code=404, detail=f"Spot '{spot_id}' not found")


def helpful_voter(
    user_id: str | None = Query(None, alias="userId", max_length=128,
                                description="Solo sin token: id de desarrollo, como en favoritos"),
    token_user_id: str | None = Depends(optional_user_id),
    users: UsersRepository = Depends(get_users_repo),
) -> str:
    """Quien vota, igual que en favoritos: el del token, o sin token un id de desarrollo que no sea una cuenta."""
    acting = resolve_acting_user(user_id, token_user_id, users)
    if acting is None:
        raise unauthorized("Sign in (or pass userId in development) to mark reviews as helpful")
    return acting


def _set_helpful(conn: sqlite3.Connection, spot_id: str, review_id: int, user_id: str, helpful: bool) -> Response:
    try:
        ReviewsService(conn).set_helpful(spot_id, review_id, user_id, helpful)
    except ReviewNotFound:
        raise HTTPException(status_code=404, detail=f"Review {review_id} not found in spot '{spot_id}'")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{spot_id}/reviews/helpful", response_model=HelpfulVotesOut)
def my_helpful_votes(spot_id: str, user_id: str = Depends(helpful_voter),
                     conn: sqlite3.Connection = Depends(get_conn)):
    """Las reseñas de este restaurante que el usuario marco como Helpful. Sin usuario, 401 como PUT/DELETE."""
    try:
        return ReviewsService(conn).helpful_votes(spot_id, user_id)
    except SpotNotFound:
        raise HTTPException(status_code=404, detail=f"Spot '{spot_id}' not found")


@router.put("/{spot_id}/reviews/{review_id}/helpful", status_code=status.HTTP_204_NO_CONTENT)
def mark_helpful(spot_id: str, review_id: int, user_id: str = Depends(helpful_voter),
                 conn: sqlite3.Connection = Depends(get_conn)):
    """Marca la reseña como Helpful. Idempotente: repetirlo responde 204 sin sumar otra vez."""
    return _set_helpful(conn, spot_id, review_id, user_id, helpful=True)


@router.delete("/{spot_id}/reviews/{review_id}/helpful", status_code=status.HTTP_204_NO_CONTENT)
def unmark_helpful(spot_id: str, review_id: int, user_id: str = Depends(helpful_voter),
                   conn: sqlite3.Connection = Depends(get_conn)):
    """Quita el Helpful. Idempotente: sin voto previo responde 204 sin restar."""
    return _set_helpful(conn, spot_id, review_id, user_id, helpful=False)


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

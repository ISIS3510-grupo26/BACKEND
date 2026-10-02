"""Endpoints por usuario: favoritos y BQ5 (favoritos abiertos y cercanos).

El userId de la ruta pasa por resolve_acting_user (app/security.py): con token tiene que ser el del token;
sin token es el override de desarrollo.
"""
import sqlite3
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.config import settings
from app.db import get_conn
from app.repositories.favorites_repository import FavoritesRepository
from app.repositories.spots_repository import SpotsRepository
from app.repositories.users_repository import UsersRepository
from app.schemas import NearbyFavoriteOut, SpotSummaryOut
from app.security import get_users_repo, optional_user_id, resolve_acting_user
from app.services.favorites_service import FavoritesService

router = APIRouter(prefix="/api/v1/users", tags=["favorites"])


def authorized_user_id(
    user_id: Annotated[str, Path(min_length=1, max_length=128)],
    token_user_id: str | None = Depends(optional_user_id),
    users: UsersRepository = Depends(get_users_repo),
) -> str:
    return resolve_acting_user(user_id, token_user_id, users)


AuthorizedUserId = Annotated[str, Depends(authorized_user_id)]


def get_repo(conn: sqlite3.Connection = Depends(get_conn)) -> FavoritesRepository:
    return FavoritesRepository(conn)


def current_time() -> datetime:
    """Reloj inyectable: los tests lo reemplazan para fijar "ahora"."""
    return datetime.now(timezone.utc)


@router.get("/{user_id}/favorites", response_model=list[SpotSummaryOut])
def list_favorites(user_id: AuthorizedUserId, conn: sqlite3.Connection = Depends(get_conn)):
    return SpotsRepository(conn).list_favorite_spots(user_id)


@router.put("/{user_id}/favorites/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(spot_id: str, user_id: AuthorizedUserId, repo: FavoritesRepository = Depends(get_repo)):
    if not repo.add(user_id, spot_id):
        raise HTTPException(status_code=404, detail=f"Spot '{spot_id}' not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{user_id}/favorites/{spot_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(spot_id: str, user_id: AuthorizedUserId, repo: FavoritesRepository = Depends(get_repo)):
    repo.remove(user_id, spot_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{user_id}/favorites/nearby", response_model=list[NearbyFavoriteOut])
def open_nearby_favorites(
    user_id: AuthorizedUserId,
    lat: float = Query(ge=-90, le=90),
    lng: float = Query(ge=-180, le=180),
    max_walk_minutes: int = Query(15, alias="maxWalkMinutes", ge=1, le=120),
    tz_offset_minutes: int = Query(settings.campus_tz_offset_minutes, alias="tzOffsetMinutes", ge=-840, le=840),
    now: datetime = Depends(current_time),
    repo: FavoritesRepository = Depends(get_repo),
):
    """BQ5: restaurantes favoritos del usuario abiertos ahora y a <= maxWalkMinutes caminando desde (lat, lng)."""
    return FavoritesService(repo).open_nearby(user_id, lat, lng, max_walk_minutes, tz_offset_minutes, now=now)

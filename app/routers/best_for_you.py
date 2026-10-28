"""Endpoint de la BQ6: restaurantes con menos espera y mas compatibles con el perfil de gusto."""
import sqlite3
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.db import get_conn
from app.repositories.best_for_you_repository import BestForYouRepository
from app.schemas import BestForYouReport
from app.services.best_for_you_service import BestForYouService

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])


def current_time() -> datetime:
    """Reloj inyectable: los tests lo reemplazan para fijar "ahora"."""
    return datetime.now(timezone.utc)


@router.get("/best-for-you", response_model=BestForYouReport)
def best_for_you(
    fresh_minutes: int = Query(120, alias="freshMinutes", ge=5, le=24 * 60,
                               description="Una espera reportada hace mas que esto no cuenta en el puntaje"),
    budget: str | None = Query(None, max_length=64, description="Presupuesto del perfil, p. ej. Budget-friendly"),
    dietary: list[str] = Query([], description="Preferencias dieteticas del perfil (se puede repetir)"),
    cuisines: list[str] = Query([], description="Cocinas favoritas del perfil (se puede repetir)"),
    limit: int | None = Query(None, ge=1, le=50, description="Sin limit devuelve todo el catalogo ordenado"),
    now: datetime = Depends(current_time),
    conn: sqlite3.Connection = Depends(get_conn),
):
    """BQ6 (tipo 2). Sin perfil ordena solo por espera y la app calcula el gusto en el celular."""
    return BestForYouService(BestForYouRepository(conn)).best_for_you(
        fresh_minutes, budget=budget, dietary=dietary, cuisines=cuisines, limit=limit, now=now,
    )

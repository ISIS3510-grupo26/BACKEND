"""Ingesta de telemetria enviada por los clientes (fuente de datos de las business questions)."""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from app.db import get_conn
from app.repositories.telemetry_repository import FAVORITE_SCREEN, TelemetryRepository
from app.repositories.users_repository import UsersRepository
from app.schemas import IngestResultOut, PageLoadBatchIn
from app.security import optional_user_id, resolve_acting_user

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


@router.post("/page-loads", response_model=IngestResultOut, status_code=status.HTTP_202_ACCEPTED)
def ingest_page_loads(batch: PageLoadBatchIn, conn: sqlite3.Connection = Depends(get_conn),
                      token_user_id: str | None = Depends(optional_user_id)):
    """El userId de cada evento pasa por resolve_acting_user: con token es el del token (puede omitirse);
    sin token es el override de desarrollo. BQ7 necesita userId y spotId en cada favorite_added."""
    users = UsersRepository(conn)
    acting = {claimed: resolve_acting_user(claimed, token_user_id, users) for claimed in {e.user_id for e in batch.events}}
    for e in batch.events:
        e.user_id = acting[e.user_id]
        if e.screen == FAVORITE_SCREEN and not (e.user_id and e.spot_id):
            raise HTTPException(status_code=422, detail="screen=favorite_added requires userId and spotId")
    inserted = TelemetryRepository(conn).insert_events(batch.events)
    return IngestResultOut(accepted=inserted, duplicates=len(batch.events) - inserted)

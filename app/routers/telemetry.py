"""Ingesta de telemetria enviada por los clientes (fuente de datos de las business questions)."""
import sqlite3

from fastapi import APIRouter, Depends, status

from app.db import get_conn
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas import IngestResultOut, PageLoadBatchIn

router = APIRouter(prefix="/api/v1/telemetry", tags=["telemetry"])


@router.post("/page-loads", response_model=IngestResultOut, status_code=status.HTTP_202_ACCEPTED)
def ingest_page_loads(batch: PageLoadBatchIn, conn: sqlite3.Connection = Depends(get_conn)):
    inserted = TelemetryRepository(conn).insert_events(batch.events)
    return IngestResultOut(accepted=inserted, duplicates=len(batch.events) - inserted)

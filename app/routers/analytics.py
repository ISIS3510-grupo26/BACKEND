"""Endpoints que responden las business questions."""
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.config import settings
from app.db import get_conn
from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas import FailedRequestsReport, SlowLoadsReport, SpotViewsByHourReport
from app.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


def get_service(conn: sqlite3.Connection = Depends(get_conn)) -> AnalyticsService:
    return AnalyticsService(TelemetryRepository(conn))


@router.get("/slow-page-loads", response_model=SlowLoadsReport)
def slow_page_loads(
    threshold_ms: int = Query(settings.slow_threshold_ms, alias="thresholdMs", ge=0),
    since: datetime | None = Query(None, description="ISO-8601, inclusive"),
    until: datetime | None = Query(None, description="ISO-8601, exclusive"),
    platform: str | None = Query(None, description="android-kotlin, flutter, ..."),
    service: AnalyticsService = Depends(get_service),
):
    """BQ1: % de cargas de la pagina de restaurante que tardan mas del umbral, por dispositivo y SO."""
    return service.slow_page_loads(threshold_ms, since=since, until=until, platform=platform)


@router.get("/failed-requests", response_model=FailedRequestsReport)
def failed_requests(
    since: datetime | None = Query(None, description="ISO-8601, inclusive"),
    until: datetime | None = Query(None, description="ISO-8601, exclusive"),
    platform: str | None = Query(None),
    service: AnalyticsService = Depends(get_service),
):
    """BQ2: % de requests fallidas al cargar la informacion del restaurante."""
    return service.failed_requests(since=since, until=until, platform=platform)


@router.get("/spot-views-by-hour", response_model=SpotViewsByHourReport)
def spot_views_by_hour(
    days: int = Query(7, ge=1, le=90, description="Ventana de dias hacia atras"),
    hour: int | None = Query(None, ge=0, le=23, description="Solo esa hora local (la app manda la hora del celular)"),
    tz_offset_minutes: int = Query(settings.campus_tz_offset_minutes, alias="tzOffsetMinutes", ge=-840, le=840),
    limit: int = Query(5, ge=1, le=50, description="Restaurantes por hora"),
    platform: str | None = Query(None),
    service: AnalyticsService = Depends(get_service),
):
    """BQ3 (tipo 4): restaurantes con mas vistas de pagina y busquedas en cada hora del dia."""
    return service.spot_views_by_hour(days=days, hour=hour, tz_offset_minutes=tz_offset_minutes,
                                      limit=limit, platform=platform)

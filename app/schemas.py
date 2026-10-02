"""Contratos JSON de la API (DTOs). Se exponen en camelCase para todos los clientes."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------- Catalogo de restaurantes ----------

class MenuItemOut(ApiModel):
    emoji: str
    emoji_background: str
    name: str
    description: str
    price: str
    is_student_pick: bool


class ReviewOut(ApiModel):
    author_name: str
    initials: str
    program: str
    stars: int
    text: str
    dined_ago: str
    helpful_count: int


class SpotSummaryOut(ApiModel):
    id: str
    emoji: str
    emoji_background: str
    emoji_border: str
    name: str
    subtitle: str
    rating: float
    price: str
    distance: str
    walk_minutes: int
    is_budget: bool
    is_vegetarian: bool
    is_high_protein: bool
    affinity_percent: int
    category: Literal["FOOD_TRUCKS", "STUDY_SPOTS"]
    note_label: str
    note: str
    uni_card_perk: str | None = None
    total_reviews: int


class SpotDetailOut(SpotSummaryOut):
    menu: list[MenuItemOut]
    reviews: list[ReviewOut]


# ---------- Favoritos (BQ5) ----------

class NearbyFavoriteOut(ApiModel):
    id: str
    name: str
    emoji: str
    distance_meters: int       # en linea recta (Haversine) desde la ubicacion del usuario
    walk_minutes: float        # distance_meters / velocidad de caminata, 1 decimal (la app redondea hacia arriba)
    closes_at: str             # 'HH:MM' hora local en que cierra la franja abierta actual


# ---------- Telemetria ----------

class PageLoadEventIn(ApiModel):
    event_id: str = Field(min_length=1, max_length=64)
    screen: str = Field(default="restaurant_detail", max_length=64)
    spot_id: str | None = Field(default=None, max_length=128)
    duration_ms: int = Field(ge=0, le=600_000)
    success: bool
    http_status: int | None = None
    error_type: str | None = Field(default=None, max_length=64)
    device_model: str = Field(min_length=1, max_length=128)
    os_name: str = Field(min_length=1, max_length=32)
    os_version: str = Field(min_length=1, max_length=32)
    platform: str = Field(min_length=1, max_length=32)
    app_version: str | None = Field(default=None, max_length=32)
    session_id: str | None = Field(default=None, max_length=64)
    occurred_at: datetime


class PageLoadBatchIn(ApiModel):
    events: list[PageLoadEventIn] = Field(min_length=1, max_length=500)


class IngestResultOut(ApiModel):
    accepted: int
    duplicates: int


# ---------- Analitica (business questions) ----------

class SlowLoadGroup(ApiModel):
    key: str
    total_loads: int
    slow_loads: int
    slow_percentage: float


class SlowLoadsReport(ApiModel):
    question: str
    threshold_ms: int
    total_loads: int
    slow_loads: int
    slow_percentage: float
    by_device: list[SlowLoadGroup]
    by_os: list[SlowLoadGroup]
    by_device_and_os: list[SlowLoadGroup]


class FailureGroup(ApiModel):
    key: str
    total_requests: int
    failed_requests: int
    failure_percentage: float


class FailedRequestsReport(ApiModel):
    question: str
    total_requests: int
    failed_requests: int
    failure_percentage: float
    by_error_type: list[FailureGroup]
    by_spot: list[FailureGroup]
    by_os: list[FailureGroup]
    by_platform: list[FailureGroup]


# ---------- BQ3 (tipo 4): vistas de pagina y busquedas por restaurante en cada hora ----------

class SpotHourlyActivity(ApiModel):
    rank: int
    spot_id: str
    name: str
    emoji: str
    page_views: int    # aperturas de la pagina del restaurante (screen = restaurant_detail)
    searches: int      # veces que el restaurante fue elegido desde el buscador (screen = search)
    total: int         # page_views + searches: criterio del ranking


class HourlyRanking(ApiModel):
    hour: int                  # hora local del campus, 0-23
    total_page_views: int
    total_searches: int
    spots: list[SpotHourlyActivity]


class SpotViewsByHourReport(ApiModel):
    question: str
    days: int
    tz_offset_minutes: int
    hours: list[HourlyRanking]  # una entrada por hora con actividad (o solo la hora pedida)

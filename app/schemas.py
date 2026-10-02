"""Contratos JSON de la API (DTOs). Se exponen en camelCase para todos los clientes."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------- Autenticacion ----------

class CredentialsIn(ApiModel):
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        return v.strip().lower() if isinstance(v, str) else v


class SignupIn(CredentialsIn):
    password: str = Field(min_length=8, max_length=72)

    @field_validator("password")
    @classmethod
    def fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > 72:  # bcrypt ignora lo que pase de 72 bytes: mejor rechazarlo que truncarlo
            raise ValueError("password must be at most 72 bytes")
        return v


class LoginIn(CredentialsIn):
    pass


class AuthTokenOut(ApiModel):
    user_id: str               # el userId de /users/{userId}/... y de la telemetria
    email: str
    access_token: str          # JWT; se manda como "Authorization: Bearer <accessToken>"
    token_type: str = "bearer"
    expires_in: int            # segundos de vigencia
    expires_at: datetime       # UTC


class UserOut(ApiModel):
    user_id: str
    email: str
    

class ChangePasswordIn(ApiModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def fits_bcrypt(cls, v: str) -> str:
        if len(v.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return v


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
    
    @field_validator("rating")
    @classmethod
    def one_decimal(cls, v: float) -> float:
        # En la base el promedio se guarda completo; se muestra con 1 decimal.
        return round(v, 1)


class SpotDetailOut(SpotSummaryOut):
    menu: list[MenuItemOut]
    reviews: list[ReviewOut]


class ReviewIn(ApiModel):
    stars: int = Field(ge=1, le=5)
    text: str = Field(default="", max_length=500)

    @field_validator("text", mode="before")
    @classmethod
    def strip_text(cls, v):
        return v.strip() if isinstance(v, str) else v


class ReviewCreatedOut(ApiModel):
    spot_id: str
    stars: int
    text: str
    rating: float
    total_reviews: int

    @field_validator("rating")
    @classmethod
    def one_decimal(cls, v: float) -> float:
        return round(v, 1)
    

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
    user_id: str | None = Field(default=None, max_length=128)
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


# ---------- BQ7: usuarios activos que agregan favoritos cada mes ----------

class MonthlyFavoriters(ApiModel):
    month: str                 # 'YYYY-MM' en hora local del campus
    active_favoriters: int     # usuarios distintos con >= 1 evento favorite_added en el mes
    favorite_events: int       # total de eventos favorite_added del mes


class MonthlyActiveFavoritersReport(ApiModel):
    question: str
    months: int
    tz_offset_minutes: int
    by_month: list[MonthlyFavoriters]  # un elemento por mes de la ventana, del mas antiguo al actual (0 si no hubo)


# ---------- BQ10: uso de la calificacion desde la pagina del restaurante ----------

class MonthlyRatingUsage(ApiModel):
    month: str                 # 'YYYY-MM' en hora local del campus
    viewers: int               # usuarios distintos que abrieron al menos una pagina de restaurante en el mes
    raters: int                # de esos, cuantos publicaron al menos una calificacion en el mismo mes
    rating_usage_percentage: float


class RatingUsageReport(ApiModel):
    question: str
    months: int
    tz_offset_minutes: int
    by_month: list[MonthlyRatingUsage]  # un elemento por mes de la ventana, del mas antiguo al actual (0 si no hubo)

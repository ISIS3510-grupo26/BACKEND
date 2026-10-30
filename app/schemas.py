"""Contratos JSON de la API (DTOs). Se exponen en camelCase para todos los clientes."""
import unicodedata
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


PASSWORD_MIN_CHARS = 8
PASSWORD_MAX_CHARS = 128


def check_new_password(v: str) -> str:
    """Regla unica para contraseñas nuevas: 8 a 128 caracteres contados despues de normalizar con NFKC, como code
    points (un emoji cuenta como 1 caracter, no como sus 4 bytes). No hay limite en bytes: auth_service hace un
    pre-hash antes de bcrypt. El front Flutter cuenta igual (password_rules.dart)."""
    if not PASSWORD_MIN_CHARS <= len(unicodedata.normalize("NFKC", v)) <= PASSWORD_MAX_CHARS:
        raise ValueError(f"password must have {PASSWORD_MIN_CHARS} to {PASSWORD_MAX_CHARS} characters")
    return v


class SignupIn(CredentialsIn):
    password: str

    @field_validator("password")
    @classmethod
    def password_rule(cls, v: str) -> str:
        return check_new_password(v)


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
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_rule(cls, v: str) -> str:
        return check_new_password(v)


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
    latitude: float | None = None   # WGS84; con esto el mapa del front pone cada pin en su sitio
    longitude: float | None = None
    
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
    

# ---------- Preferencias del usuario (Taste Profile y Dietary Preferences) ----------

class PreferencesIn(ApiModel):
    main_cuisine: str | None = Field(default=None, max_length=64)
    meal_style: str | None = Field(default=None, max_length=64)
    flavors: list[str] = Field(default_factory=list, max_length=20)
    interests: list[str] = Field(default_factory=list, max_length=20)
    diet: str = Field(default="No specific diet", max_length=64)
    avoid: list[str] = Field(default_factory=list, max_length=20)
    allergies: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("flavors", "interests", "avoid", "allergies")
    @classmethod
    def short_unique_items(cls, v: list[str]) -> list[str]:
        if any(len(item) > 64 for item in v):
            raise ValueError("each option must be at most 64 characters")
        return list(dict.fromkeys(v))  # sin repetidos, conservando el orden


class PreferencesOut(PreferencesIn):
    saved: bool  # False = el usuario todavia no ha guardado nada; son los valores por defecto


# ---------- Smart feature G: compatibilidad de cada restaurante para el usuario ----------

class SpotMatchOut(ApiModel):
    spot_id: str
    compatibility: int                   # 0-100, calculado para este usuario
    dietary_conflict: str | None = None  # p. ej. "No vegetarian options": no se le recomienda
    
    
# ---------- Favoritos (BQ5) ----------

class NearbyFavoriteOut(ApiModel):
    id: str
    name: str
    emoji: str
    distance_meters: int       # en linea recta (Haversine) desde la ubicacion del usuario
    walk_minutes: float        # distance_meters / velocidad de caminata, 1 decimal (la app redondea hacia arriba)
    closes_at: str             # 'HH:MM' hora local en que cierra la franja abierta actual


# ---------- Recomendaciones (BQ3) ----------

class NearbyPickOut(ApiModel):
    id: str
    name: str
    emoji: str
    rating: float              # promedio actual, ya con las resenas de los usuarios
    latitude: float            # el front dibuja el pin del mapa aqui
    longitude: float
    distance_meters: int       # en linea recta (Haversine) desde la ubicacion del usuario
    walk_minutes: float        # distance_meters / velocidad de caminata, 1 decimal (la app redondea hacia arriba)

    @field_validator("rating")
    @classmethod
    def one_decimal(cls, v: float) -> float:
        return round(v, 1)


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


# ---------- BQ12: selecciones de restaurantes por dia de la semana ----------

class WeekdaySearchCount(ApiModel):
    day_of_week: int          # 0 = Monday ... 6 = Sunday
    day_name: str
    searches: int

class SearchesByWeekdayReport(ApiModel):
    question: str
    days: int
    tz_offset_minutes: int
    total_searches: int
    by_day: list[WeekdaySearchCount]  # siempre de lunes a domingo

# ---------- BQ4: ultimo tiempo de espera reportado por restaurante ----------

class WaitTimeReportIn(ApiModel):
    report_id: str = Field(min_length=1, max_length=64)   # uuid del cliente: reenviar el mismo reporte no lo duplica
    minutes: int = Field(ge=0, le=180)
    platform: str = Field(min_length=1, max_length=32)
    reported_at: datetime | None = None                    # si el reporte se guardo offline, la hora real del reporte


class WaitTimeReportOut(ApiModel):
    spot_id: str
    minutes: int
    reported_at: datetime
    duplicate: bool            # True si ese report_id ya habia llegado antes (reintento)


class LastWaitTime(ApiModel):
    spot_id: str
    name: str
    emoji: str
    minutes: int | None        # None si nadie ha reportado todavia
    reported_at: datetime | None
    minutes_ago: int | None
    is_recent: bool            # reportado dentro de la ventana freshMinutes; si no, la app lo muestra como viejo
    recent_reports: int        # cuantos reportes hubo en esa ventana (da confianza al dato)


class LastWaitTimesReport(ApiModel):
    question: str
    fresh_minutes: int
    spots: list[LastWaitTime]  # todos los restaurantes, en el orden del catalogo


# ---------- BQ6: menor tiempo de espera y mayor compatibilidad con el perfil de gusto ----------

class BestForYouSpot(ApiModel):
    rank: int
    spot_id: str
    name: str
    emoji: str
    cuisine: str               # primera parte del subtitulo ("Burgers & Fries")
    rating: float
    is_budget: bool
    is_vegetarian: bool
    is_high_protein: bool
    wait_minutes: int | None   # ultimo tiempo reportado (BQ4); None si nadie ha reportado
    minutes_ago: int | None
    is_recent: bool            # dentro de freshMinutes; si no, la espera no cuenta en el puntaje
    recent_reports: int
    wait_score: int            # 0-100: menos espera, mas puntos
    taste_match: int | None    # 0-100 con el perfil que llego en la peticion; None si no llego perfil
    score: float               # criterio del ranking

    @field_validator("rating")
    @classmethod
    def one_decimal(cls, v: float) -> float:
        return round(v, 1)


class BestForYouReport(ApiModel):
    question: str
    fresh_minutes: int
    max_wait_minutes: int      # desde esta espera wait_score ya es 0
    personalized: bool         # True si la peticion traia perfil de gusto
    spots: list[BestForYouSpot]  # del mejor al peor


# ---------- BQ14: problemas al mostrar el mapa de restaurantes ----------

class MapDisplayStats(ApiModel):
    map_loads: int                  # eventos map_display que no son tiles_failed (uno por carga del mapa)
    issues: int                     # eventos map_display con success = false, incluido tiles_failed
    issue_percentage: float         # issues / map_loads * 100, 1 decimal
    issues_by_type: dict[str, int]  # error_type -> problemas, de mayor a menor
    main_issue: str | None          # el error_type con mas problemas (None si no hubo)


class MonthlyMapDisplay(MapDisplayStats):
    month: str                      # 'YYYY-MM' en hora local del campus


class MapDisplayIssuesReport(MapDisplayStats):
    question: str
    months: int
    tz_offset_minutes: int
    max_issue_percentage: float
    recommendation: Literal["improve", "keep"]  # improve si issue_percentage (de toda la ventana) > max_issue_percentage
    by_month: list[MonthlyMapDisplay]  # un elemento por mes de la ventana, del mas antiguo al actual (0 si no hubo)

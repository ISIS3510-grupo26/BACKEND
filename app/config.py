"""Configuracion leida de variables de entorno (una sola fuente de verdad)."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = os.getenv("CAMPUSBITES_DB", "data/campusbites.db")
    # Umbral por defecto de la business question 1 (carga lenta > 3 s).
    slow_threshold_ms: int = int(os.getenv("SLOW_THRESHOLD_MS", "3000"))
    # Inyeccion de fallas para demos: permite generar cargas lentas / fallidas reales.
    chaos_failure_rate: float = float(os.getenv("CHAOS_FAILURE_RATE", "0"))
    chaos_max_delay_ms: int = int(os.getenv("CHAOS_MAX_DELAY_MS", "0"))
    # Zona horaria del campus (Bogota = UTC-5) para calcular la franja horaria de la BQ3.
    campus_tz_offset_minutes: int = int(os.getenv("CAMPUS_TZ_OFFSET_MINUTES", "-300"))
    # Autenticacion (JWT HS256). Sin JWT_SECRET se usa uno aleatorio generado y guardado en la base (tabla app_meta).
    jwt_secret: str | None = os.getenv("JWT_SECRET") or None
    # Vigencia del token: 7 dias. No hay refresh token; al vencer el cliente recibe 401 y debe volver a iniciar sesion.
    jwt_expire_minutes: int = int(os.getenv("JWT_EXPIRE_MINUTES", str(7 * 24 * 60)))


settings = Settings()

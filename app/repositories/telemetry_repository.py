"""Repository de telemetria: escritura de eventos y consultas agregadas en SQL."""
import sqlite3
from datetime import datetime, timezone

from app.schemas import PageLoadEventIn

RESTAURANT_SCREEN = "restaurant_detail"

# Columnas por las que se permite agrupar (lista blanca: nunca se interpola input del usuario).
GROUP_EXPRESSIONS = {
    "device": "device_model",
    "os": "os_name || ' ' || os_version",
    "device_and_os": "device_model || ' / ' || os_name || ' ' || os_version",
    "error_type": "COALESCE(error_type, 'UNKNOWN')",
    "spot": "COALESCE(spot_id, 'UNKNOWN')",
    "platform": "platform",
}


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class TelemetryRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_events(self, events: list[PageLoadEventIn]) -> int:
        """Inserta ignorando event_id repetidos. Devuelve cuantos eran nuevos."""
        with self.conn:
            before = self.conn.total_changes
            self.conn.executemany(
                "INSERT OR IGNORE INTO page_load_events (event_id, screen, spot_id, duration_ms, success, "
                "http_status, error_type, device_model, os_name, os_version, platform, app_version, "
                "session_id, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (e.event_id, e.screen, e.spot_id, e.duration_ms, int(e.success), e.http_status,
                     e.error_type, e.device_model, e.os_name, e.os_version, e.platform, e.app_version,
                     e.session_id, _iso(e.occurred_at))
                    for e in events
                ],
            )
            return self.conn.total_changes - before

    def _where(self, only_success: bool, since: datetime | None, until: datetime | None,
               platform: str | None) -> tuple[str, list]:
        clauses, params = ["screen = ?"], [RESTAURANT_SCREEN]
        if only_success:
            clauses.append("success = 1")
        if since:
            clauses.append("occurred_at >= ?")
            params.append(_iso(since))
        if until:
            clauses.append("occurred_at < ?")
            params.append(_iso(until))
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        return " AND ".join(clauses), params

    def slow_loads(self, group: str | None, threshold_ms: int, **filters) -> list[sqlite3.Row]:
        """Cargas exitosas: total y cuantas superan el umbral (opcionalmente agrupadas)."""
        where, params = self._where(only_success=True, **filters)
        key = GROUP_EXPRESSIONS[group] if group else "'ALL'"
        return self.conn.execute(
            f"SELECT {key} AS key, COUNT(*) AS total, "
            f"SUM(CASE WHEN duration_ms > ? THEN 1 ELSE 0 END) AS hits "
            f"FROM page_load_events WHERE {where} GROUP BY key ORDER BY hits * 1.0 / COUNT(*) DESC, total DESC",
            [threshold_ms, *params],
        ).fetchall()

    def failures(self, group: str | None, **filters) -> list[sqlite3.Row]:
        """Todos los intentos de carga: total y cuantos fallaron."""
        where, params = self._where(only_success=False, **filters)
        key = GROUP_EXPRESSIONS[group] if group else "'ALL'"
        return self.conn.execute(
            f"SELECT {key} AS key, COUNT(*) AS total, "
            f"SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS hits "
            f"FROM page_load_events WHERE {where} GROUP BY key ORDER BY hits DESC, total DESC",
            params,
        ).fetchall()

    def failures_by_error_type(self, **filters) -> list[sqlite3.Row]:
        """Reparte las fallas por tipo de error; el porcentaje es sobre el total de intentos."""
        where, params = self._where(only_success=False, **filters)
        total = self.conn.execute(f"SELECT COUNT(*) FROM page_load_events WHERE {where}", params).fetchone()[0]
        return self.conn.execute(
            f"SELECT {GROUP_EXPRESSIONS['error_type']} AS key, ? AS total, COUNT(*) AS hits "
            f"FROM page_load_events WHERE {where} AND success = 0 GROUP BY key ORDER BY hits DESC",
            [total, *params],
        ).fetchall()

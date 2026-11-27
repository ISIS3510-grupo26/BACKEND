"""Repository de telemetria: escritura de eventos y consultas agregadas en SQL."""
import re
import sqlite3
from datetime import datetime, timezone

from app.schemas import PageLoadEventIn

RESTAURANT_SCREEN = "restaurant_detail"
SEARCH_SCREEN = "search"  # el usuario eligio un restaurante desde el buscador
FAVORITE_SCREEN = "favorite_added"  # el usuario guardo un restaurante (BQ7)
MAP_SCREEN = "map_display"  # BQ14: una carga del mapa (Taste Map) o una falla de sus imagenes
TILES_FAILED = "tiles_failed"  # el unico error_type de map_display que no es una carga nueva
REVIEW_SCREEN = "review_submit"  # BQ13: un intento de publicar una reseña (eventId = id del intento)
CRASH = "crash"  # BQ13: la app se cerro mientras enviaba la reseña
RECOMMENDATION_OPEN = "recommendation_open"  # BQ9: abrio un restaurante desde una recomendacion por compatibilidad
RECOMMENDATION_VISIT = "recommendation_visit"  # BQ9: llego a ese restaurante (la app lo detecta por GPS)
RECOMMENDATION_SCREENS = (RECOMMENDATION_OPEN, RECOMMENDATION_VISIT)
REVIEW_INTERACTION_SCREEN = "review_interaction"  # BQ8: el estudiante uso las reseñas durante una visita
REVIEW_ACTIONS = ("open_all", "sort", "filter", "search", "helpful")
# BQ8: eventId = "rvi-<eventId del restaurant_detail>-<accion>". La visita va dentro del id (sin columnas nuevas) y
# una accion repetida en la misma visita trae el mismo id, asi que INSERT OR IGNORE la cuenta una sola vez.
REVIEW_INTERACTION_ID = re.compile(rf"^rvi-(?P<visit>[A-Za-z0-9-]{{8,51}})-(?P<action>{'|'.join(REVIEW_ACTIONS)})$")

# Visita y accion de un evento review_interaction, sacadas del eventId en SQL. Las acciones no tienen '-', asi que
# cada una se reconoce por su sufijo "-<accion>" (lista fija: no se interpola input del usuario).
_VISIT_OF_INTERACTION = "CASE " + " ".join(
    f"WHEN event_id LIKE '%-{a}' THEN substr(event_id, 5, length(event_id) - {5 + len(a)})" for a in REVIEW_ACTIONS
) + " END"
_ACTION_OF_INTERACTION = "CASE " + " ".join(f"WHEN event_id LIKE '%-{a}' THEN '{a}'" for a in REVIEW_ACTIONS) + " END"

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
                "session_id, user_id, occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (e.event_id, e.screen, e.spot_id, e.duration_ms, int(e.success), e.http_status,
                     e.error_type, e.device_model, e.os_name, e.os_version, e.platform, e.app_version,
                     e.session_id, e.user_id, _iso(e.occurred_at))
                    for e in events
                ],
            )
            return self.conn.total_changes - before

    def _where(self, only_success: bool, since: datetime | None, until: datetime | None,
               platform: str | None) -> tuple[str, list]:
        clauses, params = ["e.screen = ?"], [RESTAURANT_SCREEN]
        if only_success:
            clauses.append("e.success = 1")
        if since:
            clauses.append("e.occurred_at >= ?")
            params.append(_iso(since))
        if until:
            clauses.append("e.occurred_at < ?")
            params.append(_iso(until))
        if platform:
            clauses.append("e.platform = ?")
            params.append(platform)
        return " AND ".join(clauses), params

    def slow_loads(self, group: str | None, threshold_ms: int, **filters) -> list[sqlite3.Row]:
        """Cargas exitosas: total y cuantas superan el umbral (opcionalmente agrupadas)."""
        where, params = self._where(only_success=True, **filters)
        key = GROUP_EXPRESSIONS[group] if group else "'ALL'"
        return self.conn.execute(
            f"SELECT {key} AS key, COUNT(*) AS total, "
            f"SUM(CASE WHEN duration_ms > ? THEN 1 ELSE 0 END) AS hits "
            f"FROM page_load_events e WHERE {where} GROUP BY key ORDER BY hits * 1.0 / COUNT(*) DESC, total DESC",
            [threshold_ms, *params],
        ).fetchall()

    def failures(self, group: str | None, **filters) -> list[sqlite3.Row]:
        """Todos los intentos de carga: total y cuantos fallaron."""
        where, params = self._where(only_success=False, **filters)
        key = GROUP_EXPRESSIONS[group] if group else "'ALL'"
        return self.conn.execute(
            f"SELECT {key} AS key, COUNT(*) AS total, "
            f"SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS hits "
            f"FROM page_load_events e WHERE {where} GROUP BY key ORDER BY hits DESC, total DESC",
            params,
        ).fetchall()

    def spot_activity_by_hour(self, hour: int | None, tz_offset_minutes: int, **filters) -> list[sqlite3.Row]:
        """BQ3: vistas de pagina y busquedas de cada restaurante agrupadas por hora local.

        Una vista = un evento `restaurant_detail` (exitoso o no: cuenta la intencion del estudiante).
        Una busqueda = un evento `search` (el restaurante fue elegido desde el buscador).
        `occurred_at` esta en UTC, asi que la hora se calcula desplazandola a la zona del campus.
        """
        where, params = self._where(only_success=False, **filters)
        where = where.replace("e.screen = ?", "e.screen IN (?, ?)", 1)
        params = [RESTAURANT_SCREEN, SEARCH_SCREEN, *params[1:]]
        local_hour = "CAST(strftime('%H', e.occurred_at, ? || ' minutes') AS INTEGER)"
        params.insert(0, str(tz_offset_minutes))
        clauses = [where, "e.spot_id IS NOT NULL"]
        if hour is not None:
            clauses.append(f"{local_hour} = ?")
            params.extend([str(tz_offset_minutes), hour])
        return self.conn.execute(
            f"SELECT {local_hour} AS hour, e.spot_id AS spot_id, s.name AS name, s.emoji AS emoji, "
            "SUM(CASE WHEN e.screen = 'restaurant_detail' THEN 1 ELSE 0 END) AS page_views, "
            "SUM(CASE WHEN e.screen = 'search' THEN 1 ELSE 0 END) AS searches "
            "FROM page_load_events e LEFT JOIN spots s ON s.id = e.spot_id "
            f"WHERE {' AND '.join(clauses)} "
            "GROUP BY hour, e.spot_id ORDER BY hour, (page_views + searches) DESC, page_views DESC, e.spot_id",
            params,
        ).fetchall()

    def favoriters_by_month(self, tz_offset_minutes: int, first_month: str, last_month: str,
                            platform: str | None = None) -> list[sqlite3.Row]:
        """BQ7: por mes local ('YYYY-MM'), usuarios distintos con eventos favorite_added y total de eventos."""
        local_month = "strftime('%Y-%m', occurred_at, ? || ' minutes')"
        clauses = ["screen = ?", "user_id IS NOT NULL", f"{local_month} BETWEEN ? AND ?"]
        params: list = [str(tz_offset_minutes), FAVORITE_SCREEN, str(tz_offset_minutes), first_month, last_month]
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        return self.conn.execute(
            f"SELECT {local_month} AS month, COUNT(DISTINCT user_id) AS users, COUNT(*) AS events "
            f"FROM page_load_events WHERE {' AND '.join(clauses)} GROUP BY month ORDER BY month",
            params,
        ).fetchall()

    def rating_usage_by_month(self, tz_offset_minutes: int, first_month: str, last_month: str,
                              platform: str | None = None) -> list[sqlite3.Row]:
        """BQ10: por mes local, usuarios que vieron una pagina de restaurante y cuantos de ellos calificaron."""
        view_month = "strftime('%Y-%m', occurred_at, ? || ' minutes')"
        review_month = "strftime('%Y-%m', created_at, ? || ' minutes')"
        view_clauses = ["screen = ?", "user_id IS NOT NULL", f"{view_month} BETWEEN ? AND ?"]
        params: list = [str(tz_offset_minutes), RESTAURANT_SCREEN, str(tz_offset_minutes), first_month, last_month]
        if platform:
            view_clauses.append("platform = ?")
            params.append(platform)
        params.append(str(tz_offset_minutes))
        return self.conn.execute(
            f"WITH viewers AS (SELECT DISTINCT {view_month} AS month, user_id FROM page_load_events "
            f"                 WHERE {' AND '.join(view_clauses)}), "
            f"     raters AS (SELECT DISTINCT {review_month} AS month, user_id FROM reviews WHERE user_id IS NOT NULL) "
            "SELECT v.month AS month, COUNT(*) AS viewers, COUNT(r.user_id) AS raters "
            "FROM viewers v LEFT JOIN raters r ON r.month = v.month AND r.user_id = v.user_id "
            "GROUP BY v.month ORDER BY v.month",
            params,
        ).fetchall()
        
    def map_display_by_month(self, tz_offset_minutes: int, first_month: str, last_month: str) -> list[sqlite3.Row]:
        """BQ14: por mes local y error_type, cargas del mapa y problemas.

        Carga = evento map_display cuyo error_type no es tiles_failed (la app manda uno por carga).
        Problema = evento map_display con success = 0, incluido tiles_failed (las imagenes del mapa fallaron).
        """
        local_month = "strftime('%Y-%m', occurred_at, ? || ' minutes')"
        clauses = ["screen = ?", f"{local_month} BETWEEN ? AND ?"]
        params: list = [str(tz_offset_minutes), TILES_FAILED, MAP_SCREEN, str(tz_offset_minutes), first_month, last_month]
        return self.conn.execute(
            f"SELECT {local_month} AS month, COALESCE(error_type, 'UNKNOWN') AS issue_type, "
            "SUM(CASE WHEN error_type IS NULL OR error_type != ? THEN 1 ELSE 0 END) AS loads, "
            "SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS issues "
            f"FROM page_load_events WHERE {' AND '.join(clauses)} GROUP BY month, issue_type ORDER BY month",
            params,
        ).fetchall()

    def failures_by_error_type(self, **filters) -> list[sqlite3.Row]:
        """Reparte las fallas por tipo de error; el porcentaje es sobre el total de intentos."""
        where, params = self._where(only_success=False, **filters)
        total = self.conn.execute(f"SELECT COUNT(*) FROM page_load_events e WHERE {where}", params).fetchone()[0]
        return self.conn.execute(
            f"SELECT {GROUP_EXPRESSIONS['error_type']} AS key, ? AS total, COUNT(*) AS hits "
            f"FROM page_load_events e WHERE {where} AND e.success = 0 GROUP BY key ORDER BY hits DESC",
            [total, *params],
        ).fetchall()

    def searches_by_weekday(self, tz_offset_minutes: int, since: datetime, until: datetime,
                            platform: str | None = None) -> list[sqlite3.Row]:
        """BQ12: cuenta selecciones desde resultados de busqueda por dia local.

        SQLite devuelve domingo = 0; esta expresion convierte el resultado a lunes = 0.
        """
        local_day = "(CAST(strftime('%w', occurred_at, ? || ' minutes') AS INTEGER) + 6) % 7"
        clauses = [
            "screen = ?",
            "spot_id IS NOT NULL",
            "occurred_at >= ?",
            "occurred_at < ?",
        ]
        params: list = [str(tz_offset_minutes), SEARCH_SCREEN, _iso(since), _iso(until)]
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        return self.conn.execute(
            f"SELECT {local_day} AS day_of_week, COUNT(*) AS searches "
            f"FROM page_load_events WHERE {' AND '.join(clauses)} "
            "GROUP BY day_of_week ORDER BY day_of_week",
            params,
        ).fetchall()
        
        
    def review_submits_by_month(self, tz_offset_minutes: int, first_month: str, last_month: str) -> list[sqlite3.Row]:
        """BQ13: por mes local, resultado y error_type, intentos de publicar una reseña.

        saved_after cuenta los crashes cuya reseña si quedo en la tabla reviews: mismo usuario y restaurante,
        guardada despues de que empezo el intento (con 5 minutos de margen por si el reloj del celular va adelantado).
        """
        local_month = "strftime('%Y-%m', occurred_at, ? || ' minutes')"
        return self.conn.execute(
            f"WITH attempts AS (SELECT {local_month} AS month, success, COALESCE(error_type, 'unknown') AS error_type, "
            "                          user_id, spot_id, occurred_at "
            f"                  FROM page_load_events WHERE screen = ? AND {local_month} BETWEEN ? AND ?) "
            "SELECT month, success, error_type, COUNT(*) AS attempts, "
            "       SUM(CASE WHEN error_type = ? AND EXISTS ("
            "           SELECT 1 FROM reviews r WHERE r.user_id = a.user_id AND r.spot_id = a.spot_id "
            "           AND r.created_at >= strftime('%Y-%m-%dT%H:%M:%S', a.occurred_at, '-5 minutes')"
            "       ) THEN 1 ELSE 0 END) AS saved_after "
            "FROM attempts a GROUP BY month, success, error_type ORDER BY month",
            [str(tz_offset_minutes), REVIEW_SCREEN, str(tz_offset_minutes), first_month, last_month, CRASH],
        ).fetchall()

    def user_reviews_by_month(self, tz_offset_minutes: int, first_month: str, last_month: str) -> list[sqlite3.Row]:
        """BQ13: reseñas que escribieron los usuarios (no las del catalogo), por mes local."""
        local_month = "strftime('%Y-%m', created_at, ? || ' minutes')"
        return self.conn.execute(
            f"SELECT {local_month} AS month, COUNT(*) AS reviews FROM reviews "
            f"WHERE user_id IS NOT NULL AND created_at IS NOT NULL AND {local_month} BETWEEN ? AND ? "
            "GROUP BY month",
            [str(tz_offset_minutes), str(tz_offset_minutes), first_month, last_month],
        ).fetchall()

    def review_interactions_by_month(self, tz_offset_minutes: int, first_month: str, last_month: str,
                                     platform: str | None = None) -> list[sqlite3.Row]:
        """BQ8: por mes local de la visita, visitas a la pagina de un restaurante (restaurant_detail exitoso), cuantas
        tuvieron al menos una interaccion con las reseñas y cuantas tuvieron cada accion.

        Cada review_interaction se liga a su visita por el eventId ("rvi-<visita>-<accion>"); una interaccion cuya
        visita no llego (o fallo) no cuenta. Varias acciones en la misma visita la cuentan una vez.
        """
        local_month = "strftime('%Y-%m', occurred_at, ? || ' minutes')"
        visit_clauses = ["screen = ?", "success = 1", f"{local_month} BETWEEN ? AND ?"]
        params: list = [str(tz_offset_minutes), RESTAURANT_SCREEN, str(tz_offset_minutes), first_month, last_month]
        if platform:
            visit_clauses.append("platform = ?")
            params.append(platform)
        params.append(REVIEW_INTERACTION_SCREEN)
        per_action = ", ".join(f"MAX(CASE WHEN x.action = '{a}' THEN 1 ELSE 0 END) AS {a}" for a in REVIEW_ACTIONS)
        return self.conn.execute(
            f"WITH visits AS (SELECT event_id, {local_month} AS month FROM page_load_events "
            f"                WHERE {' AND '.join(visit_clauses)}), "
            f"     interactions AS (SELECT DISTINCT {_VISIT_OF_INTERACTION} AS visit_id, "
            f"                             {_ACTION_OF_INTERACTION} AS action "
            "                      FROM page_load_events WHERE screen = ?), "
            "     per_visit AS (SELECT v.month, v.event_id, MAX(CASE WHEN x.visit_id IS NULL THEN 0 ELSE 1 END) AS used, "
            f"                         {per_action} "
            "                  FROM visits v LEFT JOIN interactions x ON x.visit_id = v.event_id GROUP BY v.event_id) "
            "SELECT month, COUNT(*) AS visits, SUM(used) AS with_interaction, "
            f"       {', '.join(f'SUM({a}) AS {a}' for a in REVIEW_ACTIONS)} "
            "FROM per_visit GROUP BY month ORDER BY month",
            params,
        ).fetchall()

    def recommendation_visits(self, tz_offset_minutes: int, first_month: str, last_month: str,
                              by_month: bool) -> list[sqlite3.Row]:
        """BQ9: usuarios que abrieron recomendaciones y cuantos de ellos visitaron, por mes local o en toda la ventana.

        Un visitante cuenta en el mes solo si ese mismo mes abrio una recomendacion: asi la tasa nunca pasa de 100.
        Los eventos sin userId (la app sin sesion) no cuentan para usuarios, pero si para aperturas y visitas.
        """
        local_month = "strftime('%Y-%m', occurred_at, ? || ' minutes')"
        bucket = local_month if by_month else "'ALL'"
        events = (f"SELECT {bucket} AS month, screen, user_id FROM page_load_events "
                  f"WHERE screen IN (?, ?) AND {local_month} BETWEEN ? AND ?")
        params: list = ([str(tz_offset_minutes)] if by_month else []) + [
            RECOMMENDATION_OPEN, RECOMMENDATION_VISIT, str(tz_offset_minutes), first_month, last_month]
        return self.conn.execute(
            f"WITH events AS ({events}), "
            "     openers AS (SELECT DISTINCT month, user_id FROM events WHERE screen = ? AND user_id IS NOT NULL), "
            "     visitors AS (SELECT DISTINCT month, user_id FROM events WHERE screen = ? AND user_id IS NOT NULL), "
            "     totals AS (SELECT month, SUM(screen = ?) AS opens, SUM(screen = ?) AS visits FROM events GROUP BY month) "
            "SELECT t.month AS month, t.opens AS opens, t.visits AS visits, "
            "       (SELECT COUNT(*) FROM openers o WHERE o.month = t.month) AS users_recommended, "
            "       (SELECT COUNT(*) FROM openers o JOIN visitors v ON v.month = o.month AND v.user_id = o.user_id "
            "        WHERE o.month = t.month) AS users_visited "
            "FROM totals t ORDER BY t.month",
            [*params, RECOMMENDATION_OPEN, RECOMMENDATION_VISIT, RECOMMENDATION_OPEN, RECOMMENDATION_VISIT],
        ).fetchall()

    def top_recommended_visits(self, tz_offset_minutes: int, first_month: str, last_month: str,
                               limit: int = 5) -> list[sqlite3.Row]:
        """BQ9: restaurantes recomendados a los que mas llegaron los estudiantes en la ventana."""
        local_month = "strftime('%Y-%m', e.occurred_at, ? || ' minutes')"
        return self.conn.execute(
            "SELECT e.spot_id AS spot_id, s.name AS name, s.emoji AS emoji, COUNT(*) AS visits "
            "FROM page_load_events e LEFT JOIN spots s ON s.id = e.spot_id "
            f"WHERE e.screen = ? AND e.spot_id IS NOT NULL AND {local_month} BETWEEN ? AND ? "
            "GROUP BY e.spot_id ORDER BY visits DESC, e.spot_id LIMIT ?",
            [RECOMMENDATION_VISIT, str(tz_offset_minutes), first_month, last_month, limit],
        ).fetchall()

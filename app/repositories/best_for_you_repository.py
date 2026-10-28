"""Repository de la BQ6: junta en una sola consulta lo que la recomendacion necesita de cada restaurante,
sus etiquetas (presupuesto, vegetariano, proteina) y el ultimo tiempo de espera que reportaron (BQ4)."""
import sqlite3
from datetime import datetime

from app.repositories.wait_times_repository import _iso


class BestForYouRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def candidates(self, recent_since: datetime) -> list[dict]:
        """Todos los restaurantes del catalogo con su reporte de espera mas nuevo (o None si nadie ha reportado)
        y cuantos reportes tuvieron desde recent_since. Los tiempos salen de la misma tabla que la BQ4."""
        rows = self.conn.execute(
            "SELECT s.id AS spot_id, s.name, s.emoji, s.subtitle, s.rating, s.is_budget, s.is_vegetarian, "
            "  s.is_high_protein, w.minutes AS wait_minutes, w.reported_at, "
            "  (SELECT COUNT(*) FROM wait_time_reports r WHERE r.spot_id = s.id AND r.reported_at >= ?) AS recent_reports "
            "FROM spots s LEFT JOIN wait_time_reports w ON w.id = ("
            "  SELECT r.id FROM wait_time_reports r WHERE r.spot_id = s.id ORDER BY r.reported_at DESC, r.id DESC LIMIT 1"
            ") ORDER BY s.rowid",
            (_iso(recent_since),),
        ).fetchall()
        return [
            {**dict(r), "is_budget": bool(r["is_budget"]), "is_vegetarian": bool(r["is_vegetarian"]),
             "is_high_protein": bool(r["is_high_protein"])}
            for r in rows
        ]

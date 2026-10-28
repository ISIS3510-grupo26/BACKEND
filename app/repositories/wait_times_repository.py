"""Repository de los tiempos de espera reportados (BQ4)."""
import sqlite3
from datetime import datetime, timezone


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class WaitTimesRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, report_id: str, spot_id: str, minutes: int, user_id: str | None, platform: str,
            reported_at: datetime) -> bool:
        """Guarda el reporte. Devuelve False si ese report_id ya existia (el cliente reintento el envio)."""
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO wait_time_reports (report_id, spot_id, minutes, user_id, platform, reported_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (report_id, spot_id, minutes, user_id, platform, _iso(reported_at)),
            )
        return cur.rowcount == 1

    def get(self, report_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT spot_id, minutes, reported_at FROM wait_time_reports WHERE report_id = ?", (report_id,)
        ).fetchone()

    def latest_by_spot(self, recent_since: datetime) -> list[sqlite3.Row]:
        """Para cada restaurante, su reporte mas reciente (o nada) y cuantos reportes tuvo desde recent_since."""
        return self.conn.execute(
            "SELECT s.id AS spot_id, s.name, s.emoji, w.minutes, w.reported_at, "
            "  (SELECT COUNT(*) FROM wait_time_reports r WHERE r.spot_id = s.id AND r.reported_at >= ?) AS recent_reports "
            "FROM spots s LEFT JOIN wait_time_reports w ON w.id = ("
            "  SELECT r.id FROM wait_time_reports r WHERE r.spot_id = s.id ORDER BY r.reported_at DESC, r.id DESC LIMIT 1"
            ") ORDER BY s.rowid",
            (_iso(recent_since),),
        ).fetchall()

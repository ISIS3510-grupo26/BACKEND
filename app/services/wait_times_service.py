"""Servicio de tiempos de espera (BQ4, tipo 2): recibe los reportes y arma el ultimo tiempo por restaurante."""
import sqlite3
from datetime import datetime, timedelta, timezone

from app.repositories.spots_repository import SpotsRepository
from app.repositories.wait_times_repository import WaitTimesRepository
from app.schemas import LastWaitTime, LastWaitTimesReport, WaitTimeReportIn, WaitTimeReportOut

Q_LAST_WAIT = "What is the last reported waiting time for each restaurant?"

# Un reporte offline puede llegar tarde, pero no puede venir del futuro (reloj del celular mal puesto).
MAX_CLOCK_SKEW = timedelta(minutes=5)


class SpotNotFound(Exception):
    pass


class ReportFromFuture(Exception):
    pass


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class WaitTimesService:
    def __init__(self, conn: sqlite3.Connection):
        self.reports = WaitTimesRepository(conn)
        self.spots = SpotsRepository(conn)

    def report(self, spot_id: str, body: WaitTimeReportIn, user_id: str | None,
               now: datetime | None = None) -> WaitTimeReportOut:
        now = now or datetime.now(timezone.utc)
        if not self.spots.exists(spot_id):
            raise SpotNotFound(spot_id)
        reported_at = body.reported_at or now
        if reported_at.tzinfo is None:
            reported_at = reported_at.replace(tzinfo=timezone.utc)
        if reported_at > now + MAX_CLOCK_SKEW:
            raise ReportFromFuture(spot_id)

        created = self.reports.add(body.report_id, spot_id, body.minutes, user_id, body.platform, reported_at)
        if not created:
            # Reintento: se responde con lo que ya estaba guardado, no con lo que mando esta vez.
            saved = self.reports.get(body.report_id)
            return WaitTimeReportOut(spot_id=saved["spot_id"], minutes=saved["minutes"],
                                     reported_at=_parse(saved["reported_at"]), duplicate=True)
        return WaitTimeReportOut(spot_id=spot_id, minutes=body.minutes, reported_at=reported_at, duplicate=False)

    def last_reported(self, fresh_minutes: int, now: datetime | None = None) -> LastWaitTimesReport:
        now = now or datetime.now(timezone.utc)
        rows = self.reports.latest_by_spot(recent_since=now - timedelta(minutes=fresh_minutes))
        spots = []
        for r in rows:
            reported_at = _parse(r["reported_at"]) if r["reported_at"] else None
            minutes_ago = max(0, int((now - reported_at).total_seconds() // 60)) if reported_at else None
            spots.append(LastWaitTime(
                spot_id=r["spot_id"], name=r["name"], emoji=r["emoji"], minutes=r["minutes"],
                reported_at=reported_at, minutes_ago=minutes_ago,
                is_recent=minutes_ago is not None and minutes_ago <= fresh_minutes,
                recent_reports=r["recent_reports"],
            ))
        return LastWaitTimesReport(question=Q_LAST_WAIT, fresh_minutes=fresh_minutes, spots=spots)

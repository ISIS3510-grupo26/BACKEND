"""Servicio de tiempos de espera (BQ4, tipo 2): recibe los reportes y arma el ultimo tiempo por restaurante."""
import sqlite3
from datetime import datetime, timedelta, timezone

from app.repositories.spots_repository import SpotsRepository
from app.repositories.wait_times_repository import WaitTimesRepository
from app.schemas import (BestTimeSpot, BestTimeToGoReport, HourlyWait, LastWaitTime, LastWaitTimesReport,
                         WaitTimeReportIn, WaitTimeReportOut)

Q_LAST_WAIT = "What is the last reported waiting time for each restaurant?"
Q_BEST_TIME = "At what time of the day is the reported waiting time at each restaurant the shortest?"

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

    def best_time_to_go(self, days: int, tz_offset_minutes: int, min_reports: int = 1,
                        now: datetime | None = None) -> BestTimeToGoReport:
        """BQ15 (tipo 2): para cada restaurante, la hora local con menor espera promedio reportada.

        Usa los mismos reportes de la BQ4. Cada reporte cae en la hora local en que el estudiante lo hizo
        (reported_at + tzOffsetMinutes), no en la hora en que llego al servidor. Una hora con menos de
        `min_reports` reportes no cuenta para elegir la mejor o la peor (un solo dato no es confiable).
        """
        now = now or datetime.now(timezone.utc)
        offset = timedelta(minutes=tz_offset_minutes)
        rows = self.reports.reports_since(now - timedelta(days=days))

        por_spot: dict[str, dict[int, list[int]]] = {}
        general: dict[int, list[int]] = {}
        for r in rows:
            hora = (_parse(r["reported_at"]) + offset).hour
            por_spot.setdefault(r["spot_id"], {}).setdefault(hora, []).append(r["minutes"])
            general.setdefault(hora, []).append(r["minutes"])

        def resumen(horas: dict[int, list[int]]) -> list[HourlyWait]:
            return [HourlyWait(hour=h, avg_minutes=round(sum(m) / len(m), 1), reports=len(m))
                    for h, m in sorted(horas.items())]

        spots = []
        for spot in self.spots.list_spots():
            by_hour = resumen(por_spot.get(spot["id"], {}))
            confiables = [h for h in by_hour if h.reports >= min_reports]
            # Empate en el promedio: gana la hora con mas reportes y despues la mas temprana.
            mejor = min(confiables, key=lambda h: (h.avg_minutes, -h.reports, h.hour), default=None)
            peor = max(confiables, key=lambda h: (h.avg_minutes, h.reports, -h.hour), default=None)
            spots.append(BestTimeSpot(
                spot_id=spot["id"], name=spot["name"], emoji=spot["emoji"],
                reports=sum(h.reports for h in by_hour),
                best_hour=mejor.hour if mejor else None,
                best_hour_avg_minutes=mejor.avg_minutes if mejor else None,
                worst_hour=peor.hour if peor else None,
                worst_hour_avg_minutes=peor.avg_minutes if peor else None,
                by_hour=by_hour,
            ))
        return BestTimeToGoReport(question=Q_BEST_TIME, days=days, tz_offset_minutes=tz_offset_minutes,
                                  min_reports=min_reports, total_reports=len(rows), by_hour=resumen(general),
                                  spots=spots)

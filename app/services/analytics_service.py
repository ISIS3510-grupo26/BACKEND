"""Servicio de analitica: convierte los agregados SQL en respuestas a las business questions."""
from datetime import datetime, timedelta, timezone

from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas import (FailedRequestsReport, FailureGroup, HourlyRanking, SlowLoadGroup, SlowLoadsReport,
                         SpotHourlyActivity, SpotViewsByHourReport)

Q_SLOW = "What is the percentage of restaurant page loads that take more than {s:g} seconds? By device and OS"
Q_FAILED = "What is the percentage of failed requests when loading the restaurant's information?"
Q_VIEWS_BY_HOUR = "Which restaurants receive the highest number of page views and searches during each hour?"


def _pct(part: int, total: int) -> float:
    return round(100.0 * part / total, 2) if total else 0.0


class AnalyticsService:
    def __init__(self, repo: TelemetryRepository):
        self.repo = repo

    def slow_page_loads(self, threshold_ms: int, since: datetime | None = None,
                        until: datetime | None = None, platform: str | None = None) -> SlowLoadsReport:
        filters = dict(since=since, until=until, platform=platform)

        def groups(group: str) -> list[SlowLoadGroup]:
            return [
                SlowLoadGroup(key=r["key"], total_loads=r["total"], slow_loads=r["hits"],
                              slow_percentage=_pct(r["hits"], r["total"]))
                for r in self.repo.slow_loads(group, threshold_ms, **filters)
            ]

        overall = self.repo.slow_loads(None, threshold_ms, **filters)
        total = overall[0]["total"] if overall else 0
        slow = overall[0]["hits"] if overall else 0
        return SlowLoadsReport(
            question=Q_SLOW.format(s=threshold_ms / 1000),
            threshold_ms=threshold_ms,
            total_loads=total,
            slow_loads=slow,
            slow_percentage=_pct(slow, total),
            by_device=groups("device"),
            by_os=groups("os"),
            by_device_and_os=groups("device_and_os"),
        )

    def failed_requests(self, since: datetime | None = None, until: datetime | None = None,
                        platform: str | None = None) -> FailedRequestsReport:
        filters = dict(since=since, until=until, platform=platform)

        def to_groups(rows) -> list[FailureGroup]:
            return [
                FailureGroup(key=r["key"], total_requests=r["total"], failed_requests=r["hits"],
                             failure_percentage=_pct(r["hits"], r["total"]))
                for r in rows
            ]

        overall = self.repo.failures(None, **filters)
        total = overall[0]["total"] if overall else 0
        failed = overall[0]["hits"] if overall else 0
        return FailedRequestsReport(
            question=Q_FAILED,
            total_requests=total,
            failed_requests=failed,
            failure_percentage=_pct(failed, total),
            by_error_type=to_groups(self.repo.failures_by_error_type(**filters)),
            by_spot=to_groups(self.repo.failures("spot", **filters)),
            by_os=to_groups(self.repo.failures("os", **filters)),
            by_platform=to_groups(self.repo.failures("platform", **filters)),
        )

    def spot_views_by_hour(self, days: int, hour: int | None, tz_offset_minutes: int, limit: int,
                           now: datetime | None = None, platform: str | None = None) -> SpotViewsByHourReport:
        """BQ3 (tipo 4): por cada hora del dia, que restaurantes reciben mas vistas de pagina y busquedas.

        Sin `hour` devuelve las 24 horas con actividad (la respuesta analitica completa);
        con `hour` devuelve solo esa hora (lo que la app muestra como "Popular right now").
        """
        now = now or datetime.now(timezone.utc)
        rows = self.repo.spot_activity_by_hour(hour, tz_offset_minutes,
                                               since=now - timedelta(days=days), until=None, platform=platform)
        by_hour: dict[int, list] = {}
        for r in rows:
            by_hour.setdefault(r["hour"], []).append(r)
        hours = []
        for h in sorted(by_hour):
            group = by_hour[h]
            hours.append(HourlyRanking(
                hour=h,
                total_page_views=sum(r["page_views"] for r in group),
                total_searches=sum(r["searches"] for r in group),
                spots=[
                    SpotHourlyActivity(rank=i + 1, spot_id=r["spot_id"], name=r["name"] or r["spot_id"],
                                       emoji=r["emoji"] or "🍽️", page_views=r["page_views"], searches=r["searches"],
                                       total=r["page_views"] + r["searches"])
                    for i, r in enumerate(group[:limit])
                ],
            ))
        if hour is not None and not hours:
            hours.append(HourlyRanking(hour=hour, total_page_views=0, total_searches=0, spots=[]))
        return SpotViewsByHourReport(question=Q_VIEWS_BY_HOUR, days=days, tz_offset_minutes=tz_offset_minutes, hours=hours)

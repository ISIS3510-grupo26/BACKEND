"""Servicio de analitica: convierte los agregados SQL en respuestas a las business questions."""
from datetime import datetime

from app.repositories.telemetry_repository import TelemetryRepository
from app.schemas import FailedRequestsReport, FailureGroup, SlowLoadGroup, SlowLoadsReport

Q_SLOW = "What is the percentage of restaurant page loads that take more than {s:g} seconds? By device and OS"
Q_FAILED = "What is the percentage of failed requests when loading the restaurant's information?"


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

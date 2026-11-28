"""Pruebas de los reportes de espera de ejemplo que se crean al arrancar (DEMO_WAIT_REPORTS)."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import connect, init_db
from app.demo_seed import seed_demo_wait_reports
from app.main import app
from app.repositories.spots_repository import SpotsRepository
from tests.test_wait_times import report

NOW = datetime(2026, 11, 27, 22, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "seed.db"))
    c = connect()
    init_db(c)
    SpotsRepository(c).sync_catalog()
    yield c
    c.close()


def count(conn):
    return conn.execute("SELECT COUNT(*) FROM wait_time_reports").fetchone()[0]


def test_empty_database_gets_the_reports(conn):
    assert seed_demo_wait_reports(conn, 250, now=NOW) == 250
    assert count(conn) == 250
    rows = conn.execute("SELECT DISTINCT platform FROM wait_time_reports").fetchall()
    assert [r[0] for r in rows] == ["seed"]


def test_reports_are_in_the_last_days_and_never_today(conn):
    seed_demo_wait_reports(conn, 250, days=21, now=NOW)
    fechas = [datetime.fromisoformat(r[0].replace("Z", "+00:00"))
              for r in conn.execute("SELECT reported_at FROM wait_time_reports")]
    assert min(fechas) >= NOW - timedelta(days=22)
    hoy_bogota = NOW.astimezone(timezone(timedelta(hours=-5))).date()
    assert all(f.astimezone(timezone(timedelta(hours=-5))).date() < hoy_bogota for f in fechas)


def test_a_database_with_reports_is_not_touched(conn):
    seed_demo_wait_reports(conn, 10, now=NOW)
    assert seed_demo_wait_reports(conn, 250, now=NOW) == 0
    assert count(conn) == 10


def test_zero_means_off(conn):
    assert seed_demo_wait_reports(conn, 0, now=NOW) == 0
    assert count(conn) == 0


def test_on_startup_best_time_has_data_and_new_reports_still_count(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "startup.db"))
    object.__setattr__(settings, "demo_wait_reports", 250)
    try:
        with TestClient(app) as client:
            body = client.get("/api/v1/analytics/best-time-to-go", params={"days": 28}).json()
            assert body["totalReports"] == 250
            assert all(spot["bestHour"] is not None for spot in body["spots"])

            # Un reporte de un estudiante se suma encima de los de ejemplo.
            assert report(client, "nitro-coffee", 9).status_code == 201
            after = client.get("/api/v1/analytics/best-time-to-go", params={"days": 28}).json()
            assert after["totalReports"] == 251
    finally:
        object.__setattr__(settings, "demo_wait_reports", 0)

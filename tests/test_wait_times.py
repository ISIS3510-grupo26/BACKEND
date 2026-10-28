"""Pruebas de la BQ4: reportar tiempos de espera y consultar el ultimo por restaurante."""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import spots


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def at_time():
    """Fija el "ahora" del servidor (UTC)."""
    def set_now(iso_utc: str):
        app.dependency_overrides[spots.current_time] = lambda: datetime.fromisoformat(iso_utc)
    return set_now


def report(client, spot="nitro-coffee", minutes=8, reported_at=None, report_id=None):
    body = {"reportId": report_id or str(uuid.uuid4()), "minutes": minutes, "platform": "android-kotlin"}
    if reported_at:
        body["reportedAt"] = reported_at
    return client.post(f"/api/v1/spots/{spot}/wait-times", json=body)


def latest(client, **params):
    r = client.get("/api/v1/spots/wait-times/latest", params=params)
    assert r.status_code == 200, r.text
    return {s["spotId"]: s for s in r.json()["spots"]}


def test_last_reported_wait_time_per_spot(client, at_time):
    at_time("2026-10-26T17:00:00+00:00")
    report(client, "nitro-coffee", 12, reported_at="2026-10-26T16:10:00Z")
    report(client, "nitro-coffee", 4, reported_at="2026-10-26T16:50:00Z")
    report(client, "conda-de-bons", 20, reported_at="2026-10-26T16:30:00Z")

    spots_by_id = latest(client)
    assert len(spots_by_id) == 7  # todos los restaurantes, aunque no tengan reportes

    nitro = spots_by_id["nitro-coffee"]
    assert nitro["minutes"] == 4 and nitro["minutesAgo"] == 10  # gana el mas reciente, no el ultimo en llegar
    assert nitro["isRecent"] is True and nitro["recentReports"] == 2
    assert spots_by_id["conda-de-bons"]["minutes"] == 20

    sin_reportes = spots_by_id["green-bowl-co"]
    assert sin_reportes["minutes"] is None and sin_reportes["reportedAt"] is None
    assert sin_reportes["isRecent"] is False and sin_reportes["recentReports"] == 0


def test_offline_report_arrives_late_but_keeps_its_time(client, at_time):
    # El estudiante reporto a las 16:00 sin conexion y el celular lo envio a las 16:40.
    at_time("2026-10-26T16:40:00+00:00")
    report(client, "nitro-coffee", 6, reported_at="2026-10-26T16:00:00Z")
    at_time("2026-10-26T16:45:00+00:00")
    report(client, "nitro-coffee", 15)  # sin reportedAt: se toma la hora del servidor

    nitro = latest(client)["nitro-coffee"]
    assert nitro["minutes"] == 15 and nitro["minutesAgo"] == 0


def test_resending_same_report_is_idempotent(client, at_time):
    at_time("2026-10-26T17:00:00+00:00")
    rid = str(uuid.uuid4())
    first = report(client, minutes=9, report_id=rid)
    again = report(client, minutes=30, report_id=rid)  # mismo id: es un reintento, no un reporte nuevo

    assert first.status_code == 201 and first.json()["duplicate"] is False
    assert again.status_code == 201 and again.json()["duplicate"] is True
    assert again.json()["minutes"] == 9
    assert latest(client)["nitro-coffee"]["recentReports"] == 1


def test_old_reports_are_not_recent(client, at_time):
    at_time("2026-10-26T17:00:00+00:00")
    report(client, minutes=10, reported_at="2026-10-26T13:00:00Z")

    nitro = latest(client)["nitro-coffee"]
    assert nitro["minutes"] == 10 and nitro["minutesAgo"] == 240
    assert nitro["isRecent"] is False and nitro["recentReports"] == 0
    assert latest(client, freshMinutes=300)["nitro-coffee"]["isRecent"] is True


def test_report_validation(client, at_time):
    at_time("2026-10-26T17:00:00+00:00")
    assert report(client, spot="nope").status_code == 404
    assert report(client, minutes=-1).status_code == 422
    assert report(client, minutes=181).status_code == 422
    assert report(client, reported_at="2026-10-26T18:00:00Z").status_code == 422  # reloj del celular adelantado
    assert report(client, reported_at="2026-10-26T17:03:00Z").status_code == 201  # tolerancia de 5 min

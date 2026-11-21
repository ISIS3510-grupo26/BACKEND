"""BQ8: % de visitas a la pagina de un restaurante que incluyen una interaccion con las reseñas, por mes."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

URL = "/api/v1/analytics/review-interactions"
INGEST = "/api/v1/telemetry/page-loads"


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def _event(event_id, screen, occurred_at, success=True, platform="flutter", spot="nitro-coffee"):
    return {
        "eventId": event_id, "screen": screen, "spotId": spot, "durationMs": 0 if screen != "restaurant_detail" else 800,
        "success": success, "deviceModel": "Pixel 7", "osName": "Android", "osVersion": "14", "platform": platform,
        "occurredAt": occurred_at,
    }


def visit(occurred_at, success=True, platform="flutter"):
    """Una visita a la pagina de un restaurante; devuelve (visitId, evento)."""
    visit_id = uuid.uuid4().hex
    return visit_id, _event(visit_id, "restaurant_detail", occurred_at, success, platform)


def interaction(visit_id, action, occurred_at):
    return _event(f"rvi-{visit_id}-{action}", "review_interaction", occurred_at)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def month(dt):
    return (dt + timedelta(minutes=-300)).strftime("%Y-%m")  # mes local en Bogota


def by_month(client, **params):
    return {m["month"]: m for m in client.get(URL, params=params).json()["byMonth"]}


def test_percentage_counts_each_visit_once_whatever_it_did(client):
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    a, va = visit(iso(now))
    b, vb = visit(iso(now))
    _, vc = visit(iso(now))  # visita sin interaccion
    client.post(INGEST, json={"events": [
        va, vb, vc,
        interaction(a, "open_all", iso(now)), interaction(a, "sort", iso(now)), interaction(a, "search", iso(now)),
        interaction(b, "helpful", iso(now)),
    ]})

    r = client.get(URL, params={"months": 1}).json()
    assert r["question"] == "What percentage of restaurant page visits include an interaction with the comments each month?"
    assert (r["months"], r["tzOffsetMinutes"]) == (1, -300)
    m = r["byMonth"][0]
    assert m["month"] == month(now)
    assert (m["pageVisits"], m["visitsWithInteraction"], m["interactionPercentage"]) == (3, 2, 66.67)
    assert m["byAction"] == {"open_all": 1, "sort": 1, "filter": 0, "search": 1, "helpful": 1}


def test_the_same_action_twice_in_a_visit_is_one_event(client):
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    a, va = visit(iso(now))
    first = client.post(INGEST, json={"events": [va, interaction(a, "filter", iso(now))]}).json()
    again = client.post(INGEST, json={"events": [interaction(a, "filter", iso(now + timedelta(seconds=30)))]}).json()

    assert first == {"accepted": 2, "duplicates": 0}
    assert again == {"accepted": 0, "duplicates": 1}  # mismo eventId: INSERT OR IGNORE
    assert by_month(client, months=1)[month(now)]["byAction"]["filter"] == 1


def test_only_successful_visits_count_and_orphan_interactions_are_ignored(client):
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    failed, vf = visit(iso(now), success=False)
    client.post(INGEST, json={"events": [
        vf, interaction(failed, "open_all", iso(now)),
        interaction(uuid.uuid4().hex, "sort", iso(now)),  # su visita nunca llego
    ]})

    m = by_month(client, months=1)[month(now)]
    assert (m["pageVisits"], m["visitsWithInteraction"], m["interactionPercentage"]) == (0, 0, 0.0)


def test_months_without_visits_are_zero_and_platform_filters_visits(client):
    now = datetime.now(timezone.utc) - timedelta(minutes=5)
    k, vk = visit(iso(now), platform="android-kotlin")
    _, vf = visit(iso(now), platform="flutter")
    client.post(INGEST, json={"events": [vk, vf, interaction(k, "open_all", iso(now))]})

    r = client.get(URL, params={"months": 3}).json()
    assert len(r["byMonth"]) == 3 and [m["pageVisits"] for m in r["byMonth"][:2]] == [0, 0]
    kotlin = by_month(client, months=1, platform="android-kotlin")[month(now)]
    flutter = by_month(client, months=1, platform="flutter")[month(now)]
    assert (kotlin["pageVisits"], kotlin["interactionPercentage"]) == (1, 100.0)
    assert (flutter["pageVisits"], flutter["interactionPercentage"]) == (1, 0.0)


def test_visits_go_to_their_local_calendar_month(client):
    from app.db import connect
    from app.repositories.telemetry_repository import TelemetryRepository
    from app.services.analytics_service import AnalyticsService

    # 1 nov 03:00 UTC = 31 oct 22:00 en Bogota: es una visita de octubre, aunque la interaccion llegue en noviembre.
    a, va = visit("2026-11-01T03:00:00Z")
    _, vb = visit("2026-11-01T06:00:00Z")
    client.post(INGEST, json={"events": [va, vb, interaction(a, "sort", "2026-11-01T05:30:00Z")]})
    conn = connect()
    try:
        service = AnalyticsService(TelemetryRepository(conn))
        report = service.review_interactions(months=2, tz_offset_minutes=-300, now=datetime(2026, 11, 15, tzinfo=timezone.utc))
        assert [(m.month, m.page_visits, m.visits_with_interaction) for m in report.by_month] == [
            ("2026-10", 1, 1), ("2026-11", 1, 0)]
        utc = service.review_interactions(months=2, tz_offset_minutes=0, now=datetime(2026, 11, 15, tzinfo=timezone.utc))
        assert [(m.month, m.page_visits) for m in utc.by_month] == [("2026-10", 0), ("2026-11", 2)]
    finally:
        conn.close()


@pytest.mark.parametrize("event_id, spot", [
    ("rvi-abcdef12-dance", "nitro-coffee"),       # accion que no existe
    ("abcdef1234-sort", "nitro-coffee"),          # sin el prefijo rvi-
    ("rvi--sort", "nitro-coffee"),                # sin visita
    ("rvi-abcdef1234-sort", None),                # sin spotId
])
def test_ingest_rejects_malformed_review_interactions(client, event_id, spot):
    e = _event(event_id, "review_interaction", "2026-11-10T15:00:00Z", spot=spot)
    assert client.post(INGEST, json={"events": [e]}).status_code == 422


def test_review_interactions_validation(client):
    for params in ({"months": 0}, {"months": 37}, {"tzOffsetMinutes": 841}):
        assert client.get(URL, params=params).status_code == 422, params

"""BQ9: tasa de usuarios que visitan los restaurantes que la app les recomienda por compatibilidad, por mes."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

URL = "/api/v1/analytics/recommendation-visits"


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def rec_event(screen, user, spot="nitro-coffee", occurred_at=None, event_id=None):
    return {
        "eventId": event_id or str(uuid.uuid4()),
        "screen": screen,
        "spotId": spot,
        "userId": user,
        "durationMs": 0,
        "success": True,
        "deviceModel": "Pixel 7",
        "osName": "android",
        "osVersion": "14",
        "platform": "flutter",
        "occurredAt": occurred_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def opened(user, spot="nitro-coffee", **kw):
    return rec_event("recommendation_open", user, spot, **kw)


def visited(user, spot="nitro-coffee", **kw):
    return rec_event("recommendation_visit", user, spot, **kw)


def test_recommendation_events_require_spot_id(client):
    for screen in ("recommendation_open", "recommendation_visit"):
        e = rec_event(screen, "ana")
        e["spotId"] = None
        r = client.post("/api/v1/telemetry/page-loads", json={"events": [e]})
        assert r.status_code == 422 and screen in r.text

    r = client.post("/api/v1/telemetry/page-loads", json={"events": [opened("ana"), visited("ana")]})
    assert r.status_code == 202 and r.json() == {"accepted": 2, "duplicates": 0}


def test_recommendation_events_are_idempotent(client):
    # La app reenvia la visita con el mismo eventId si no le llego el 202: no cuenta dos veces.
    visit = visited("ana", event_id="visit-abc")
    client.post("/api/v1/telemetry/page-loads", json={"events": [opened("ana"), visit]})
    r = client.post("/api/v1/telemetry/page-loads", json={"events": [visit]})
    assert r.json() == {"accepted": 0, "duplicates": 1}


def post(client, events):
    r = client.post("/api/v1/telemetry/page-loads", json={"events": events})
    assert r.status_code == 202, r.text


def test_recommendation_visits_by_month(client):
    now = datetime.now(timezone.utc)
    month = lambda dt: (dt + timedelta(minutes=-300)).strftime("%Y-%m")
    before = now - timedelta(days=35)
    last_month = before.strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - timedelta(days=300)).strftime("%Y-%m-%dT%H:%M:%SZ")

    post(client, [
        # Este mes: 4 usuarios abren recomendaciones (ana dos veces), 2 de ellos llegan.
        opened("ana", "nitro-coffee"), opened("ana", "green-bowl-co"), visited("ana", "nitro-coffee"),
        opened("beto", "conda-de-bons"), visited("beto", "conda-de-bons"),
        opened("caro", "nitro-coffee"),
        opened("dani", "green-bowl-co"),
        # El mes pasado: 2 usuarios abren, 1 llega dos veces a sitios distintos.
        opened("ana", "nitro-coffee", occurred_at=last_month), visited("ana", "nitro-coffee", occurred_at=last_month),
        opened("eva", "conda-de-bons", occurred_at=last_month),
        visited("ana", "conda-de-bons", occurred_at=last_month),
        # Fuera de la ventana de 6 meses y otras pantallas: no cuentan.
        opened("fede", occurred_at=old), visited("fede", occurred_at=old),
        {**opened("gabi"), "screen": "restaurant_detail", "eventId": str(uuid.uuid4())},
    ])

    r = client.get(URL).json()
    assert r["question"] == ("What is the rate of users that visit restaurants based on the app's compatibility "
                             "recommendations each month?")
    assert (r["months"], r["tzOffsetMinutes"]) == (6, -300)
    # Toda la ventana: ana, beto, caro, dani y eva abrieron (5); ana y beto llegaron (2).
    assert (r["usersRecommended"], r["usersVisited"], r["visitRatePercentage"]) == (5, 2, 40.0)
    assert (r["recommendationOpens"], r["visits"], r["opensToVisitsPercentage"]) == (7, 4, 57.1)

    assert len(r["byMonth"]) == 6 and r["byMonth"][-1]["month"] == month(now)
    by_month = {m["month"]: m for m in r["byMonth"]}
    current, previous = by_month[month(now)], by_month[month(before)]
    assert (current["usersRecommended"], current["usersVisited"], current["visitRatePercentage"]) == (4, 2, 50.0)
    assert (current["recommendationOpens"], current["visits"], current["opensToVisitsPercentage"]) == (5, 2, 40.0)
    assert (previous["usersRecommended"], previous["usersVisited"], previous["visitRatePercentage"]) == (2, 1, 50.0)
    assert (previous["recommendationOpens"], previous["visits"]) == (2, 2)
    empty = next(m for m in r["byMonth"] if m["month"] not in (month(now), month(before)))
    assert empty == {"usersRecommended": 0, "usersVisited": 0, "visitRatePercentage": 0.0, "recommendationOpens": 0,
                     "visits": 0, "opensToVisitsPercentage": 0.0, "month": empty["month"]}

    top = r["topVisitedSpots"]
    assert [(s["spotId"], s["visits"]) for s in top] == [("conda-de-bons", 2), ("nitro-coffee", 2)]
    assert top[0]["name"] == "Conda de Bons" and top[0]["emoji"]


def test_visitor_without_open_that_month_is_not_counted(client):
    # Abrió el 31 a las 23:50 y llegó el 1 a las 00:10: la visita cuenta como visita, pero el usuario no
    # cuenta como visitante del mes nuevo porque ese mes no abrió nada. Asi la tasa nunca pasa de 100.
    now = datetime.now(timezone.utc)
    prev = (now - timedelta(days=35)).strftime("%Y-%m-%dT%H:%M:%SZ")
    post(client, [opened("ana", occurred_at=prev), visited("ana")])
    current = client.get(URL, params={"months": 2}).json()["byMonth"][-1]
    assert (current["usersRecommended"], current["usersVisited"], current["visits"]) == (0, 0, 1)
    assert current["visitRatePercentage"] == 0.0


def test_events_without_user_count_as_events_only(client):
    e_open, e_visit = opened(None), visited(None)
    post(client, [e_open, e_visit])
    r = client.get(URL, params={"months": 1}).json()
    assert (r["usersRecommended"], r["usersVisited"], r["recommendationOpens"], r["visits"]) == (0, 0, 1, 1)


def test_empty_and_validation(client):
    r = client.get(URL, params={"months": 1, "tzOffsetMinutes": 840})
    assert r.status_code == 200
    body = r.json()
    assert (body["usersRecommended"], body["visitRatePercentage"], body["topVisitedSpots"]) == (0, 0.0, [])
    for params in ({"months": 0}, {"months": 37}, {"tzOffsetMinutes": -841}, {"months": "seis"}):
        assert client.get(URL, params=params).status_code == 422, params

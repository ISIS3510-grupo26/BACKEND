"""Pruebas de la BQ13: crashes al publicar una reseña y su efecto en las reseñas publicadas."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

URL = "/api/v1/analytics/review-crashes"


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def signup(client, email="gaby@uniandes.edu.co"):
    s = client.post("/api/v1/auth/signup", json={"email": email, "password": "segura123"}).json()
    return s["userId"], {"Authorization": f"Bearer {s['accessToken']}"}


def attempt(user_id, spot, success, error_type=None, status=None, event_id=None, minutes_ago=1):
    """Un intento de publicar como lo manda la app de Flutter (el eventId es el id del intento)."""
    started = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return {
        "eventId": event_id or str(uuid.uuid4()), "screen": "review_submit", "spotId": spot, "userId": user_id,
        "durationMs": 0 if error_type == "crash" else 1200, "success": success, "httpStatus": status,
        "errorType": error_type, "deviceModel": "Galaxy A54", "osName": "android", "osVersion": "14",
        "platform": "flutter", "occurredAt": started.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


def send(client, events, headers):
    # Los eventos con userId de una cuenta registrada llevan su token (AuthClient lo pone en la app).
    r = client.post("/api/v1/telemetry/page-loads", json={"events": events}, headers=headers)
    assert r.status_code == 202, r.text
    return r.json()


def review(client, headers, spot):
    r = client.post(f"/api/v1/spots/{spot}/reviews", json={"stars": 4, "text": "rico"}, headers=headers)
    assert r.status_code == 201, r.text


def test_review_crashes(client):
    me, h = signup(client)
    # 1. Publicada normal.
    review(client, h, "nitro-coffee")
    # 2. Crash, pero el servidor alcanzo a guardar la reseña antes de que la app se cerrara.
    review(client, h, "taqueria-la-esquina")
    crash_id = str(uuid.uuid4())
    send(client, [
        attempt(me, "nitro-coffee", True, status=201),
        attempt(me, "taqueria-la-esquina", False, "crash", event_id=crash_id),
        # 3. Crash sin reseña guardada: esta se perdio.
        attempt(me, "poodle-pizza-slices", False, "crash"),
        attempt(me, "poodle-pizza-slices", False, "network"),
        attempt(me, "nitro-coffee", False, "rejected", status=409),
    ], h)
    # El mismo intento llega dos veces (la app lo reenvio): no se cuenta de nuevo.
    assert send(client, [attempt(me, "taqueria-la-esquina", False, "crash", event_id=crash_id)], h)["duplicates"] == 1

    r = client.get(URL).json()
    assert r["question"].startswith("How does the number of app crashes")
    assert (r["attempts"], r["published"], r["crashes"]) == (5, 1, 2)
    assert r["crashPercentage"] == 40.0
    assert (r["savedDespiteCrash"], r["lostToCrashes"]) == (1, 1)
    assert r["failuresByType"] == {"crash": 2, "network": 1, "rejected": 1}
    assert list(r["failuresByType"]) == ["crash", "network", "rejected"]  # de mayor a menor, empate alfabetico
    assert r["reviewsPublished"] == 2
    assert r["crashImpactPercentage"] == 33.3  # 1 perdida de 3 que se quisieron publicar
    assert r["recommendation"] == "fix_crashes"
    assert [(p["issue"], p["sharePercentage"]) for p in r["priorities"]] == [
        ("crash", 50.0), ("network", 25.0), ("rejected", 25.0)]
    assert r["priorities"][0]["change"]

    assert len(r["byMonth"]) == 3
    current = r["byMonth"][-1]
    assert current["attempts"] == 5 and current["reviewsPublished"] == 2 and current["lostToCrashes"] == 1
    assert r["byMonth"][0]["attempts"] == 0 and r["byMonth"][0]["failuresByType"] == {}


def test_crash_before_the_attempt_is_not_saved(client):
    """Una reseña que ya existia antes del intento no cuenta como guardada por ese intento."""
    me, h = signup(client)
    review(client, h, "nitro-coffee")
    send(client, [attempt(me, "nitro-coffee", False, "crash", minutes_ago=-30)], h)  # empezo despues de la reseña
    r = client.get(URL, params={"months": 1}).json()
    assert (r["crashes"], r["savedDespiteCrash"], r["lostToCrashes"]) == (1, 0, 1)


def test_review_crashes_keep_and_empty(client):
    empty = client.get(URL, params={"months": 1}).json()
    assert empty["attempts"] == 0 and empty["crashPercentage"] == 0.0 and empty["crashImpactPercentage"] == 0.0
    assert empty["recommendation"] == "keep" and empty["priorities"] == []

    me, h = signup(client)
    send(client, [attempt(me, "nitro-coffee", True, status=201) for _ in range(19)]
         + [attempt(me, "nitro-coffee", False, "crash")], h)
    r = client.get(URL, params={"months": 1}).json()
    assert r["crashPercentage"] == 5.0 and r["recommendation"] == "keep"  # exactamente el limite no es "mas de"
    assert client.get(URL, params={"months": 1, "maxCrashPercentage": 4}).json()["recommendation"] == "fix_crashes"


def test_review_crashes_validation(client):
    assert client.get(URL, params={"months": 0}).status_code == 422
    assert client.get(URL, params={"months": 37}).status_code == 422
    assert client.get(URL, params={"maxCrashPercentage": 101}).status_code == 422
    assert client.get(URL, params={"tzOffsetMinutes": 900}).status_code == 422
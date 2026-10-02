"""Pruebas de cambio de contraseña, publicacion de reseñas (Unit of Work) y BQ10."""
import sqlite3
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def signup(client, email="maria@uniandes.edu.co", password="segura123"):
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def view_event(spot="nitro-coffee", platform="flutter"):
    return {
        "eventId": str(uuid.uuid4()), "screen": "restaurant_detail", "spotId": spot,
        "durationMs": 900, "success": True, "httpStatus": 200, "deviceModel": "Pixel 7",
        "osName": "Android", "osVersion": "14", "platform": platform,
        "occurredAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------- Cambiar contraseña ----------

def test_change_password(client):
    s = signup(client)
    old = bearer(s["accessToken"])
    url = "/api/v1/auth/change-password"

    assert client.post(url, json={"currentPassword": "segura123", "newPassword": "nueva12345"}).status_code == 401
    wrong = client.post(url, json={"currentPassword": "incorrecta", "newPassword": "nueva12345"}, headers=old)
    assert wrong.status_code == 400
    same = client.post(url, json={"currentPassword": "segura123", "newPassword": "segura123"}, headers=old)
    assert same.status_code == 400
    assert client.post(url, json={"currentPassword": "segura123", "newPassword": "corta"}, headers=old).status_code == 422

    ok = client.post(url, json={"currentPassword": "segura123", "newPassword": "nueva12345"}, headers=old)
    assert ok.status_code == 200 and ok.json()["userId"] == s["userId"]
    new = bearer(ok.json()["accessToken"])

    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    assert client.get("/api/v1/auth/me", headers=new).status_code == 200

    login = lambda pw: client.post("/api/v1/auth/login", json={"email": s["email"], "password": pw}).status_code
    assert login("segura123") == 401
    assert login("nueva12345") == 200


# ---------- Reseñas ----------

def test_review_updates_rating_and_shows_first(client):
    s = signup(client)
    token = bearer(s["accessToken"])
    before = client.get("/api/v1/spots/conda-de-bons").json()

    r = client.post("/api/v1/spots/conda-de-bons/reviews", json={"stars": 3, "text": "  Rico pero lento  "},
                    headers=token)
    assert r.status_code == 201, r.text
    expected = (before["rating"] * before["totalReviews"] + 3) / (before["totalReviews"] + 1)
    assert r.json() == {"spotId": "conda-de-bons", "stars": 3, "text": "Rico pero lento",
                        "rating": round(expected, 1), "totalReviews": before["totalReviews"] + 1}

    after = client.get("/api/v1/spots/conda-de-bons").json()
    assert after["totalReviews"] == before["totalReviews"] + 1
    first = after["reviews"][0]
    assert (first["authorName"], first["initials"], first["stars"], first["dinedAgo"]) == ("maria", "MA", 3, "Dined today")
    assert len(after["reviews"]) == len(before["reviews"]) + 1


def test_review_errors(client):
    token = bearer(signup(client)["accessToken"])
    url = "/api/v1/spots/nitro-coffee/reviews"
    assert client.post(url, json={"stars": 4}).status_code == 401
    assert client.post(url, json={"stars": 6}, headers=token).status_code == 422
    assert client.post(url, json={"stars": 0}, headers=token).status_code == 422
    assert client.post("/api/v1/spots/nope/reviews", json={"stars": 4}, headers=token).status_code == 404

    assert client.post(url, json={"stars": 4}, headers=token).status_code == 201
    total = client.get("/api/v1/spots/nitro-coffee").json()["totalReviews"]
    assert client.post(url, json={"stars": 1}, headers=token).status_code == 409
    assert client.get("/api/v1/spots/nitro-coffee").json()["totalReviews"] == total


def test_unit_of_work_rolls_back(client, monkeypatch):
    """Si actualizar el promedio falla, la reseña tampoco queda guardada."""
    from app.repositories.spots_repository import SpotsRepository
    token = bearer(signup(client)["accessToken"])
    before = client.get("/api/v1/spots/nitro-coffee").json()

    def boom(self, spot_id, stars):
        raise RuntimeError("fallo a mitad de la transaccion")

    monkeypatch.setattr(SpotsRepository, "apply_new_rating", boom)
    with pytest.raises(RuntimeError):
        client.post("/api/v1/spots/nitro-coffee/reviews", json={"stars": 1}, headers=token)
    monkeypatch.undo()

    conn = sqlite3.connect(settings.db_path)
    saved = conn.execute("SELECT COUNT(*) FROM reviews WHERE user_id IS NOT NULL").fetchone()[0]
    conn.close()
    assert saved == 0
    after = client.get("/api/v1/spots/nitro-coffee").json()
    assert (after["rating"], after["totalReviews"]) == (before["rating"], before["totalReviews"])


def test_user_reviews_survive_restart(client):
    # El catalogo se resincroniza en cada arranque.
    token = bearer(signup(client)["accessToken"])
    created = client.post("/api/v1/spots/nitro-coffee/reviews", json={"stars": 2, "text": "Frio"}, headers=token).json()
    with TestClient(app) as restarted:
        spot = restarted.get("/api/v1/spots/nitro-coffee").json()
    assert spot["reviews"][0]["text"] == "Frio"
    assert (spot["rating"], spot["totalReviews"]) == (created["rating"], created["totalReviews"])


# ---------- BQ10 ----------

def test_rating_usage_bq10(client):
    ana, luis = signup(client, "ana@uniandes.edu.co"), signup(client, "luis@uniandes.edu.co")
    for user in (ana, luis):
        r = client.post("/api/v1/telemetry/page-loads", json={"events": [view_event(), view_event("green-bowl-co")]},
                        headers=bearer(user["accessToken"]))
        assert r.status_code == 202
    # Vista sin sesion (sin userId): no cuenta, la pregunta es sobre usuarios.
    client.post("/api/v1/telemetry/page-loads", json={"events": [view_event()]})

    # Solo Ana califica (dos veces, en dos restaurantes): sigue siendo 1 usuario.
    for spot in ("nitro-coffee", "green-bowl-co"):
        client.post(f"/api/v1/spots/{spot}/reviews", json={"stars": 5}, headers=bearer(ana["accessToken"]))

    r = client.get("/api/v1/analytics/rating-usage", params={"months": 2}).json()
    assert r["question"].startswith("What percentage of users use the restaurant rating feature")
    assert len(r["byMonth"]) == 2 and r["byMonth"][0]["viewers"] == 0
    current = r["byMonth"][-1]
    assert (current["viewers"], current["raters"], current["ratingUsagePercentage"]) == (2, 1, 50.0)

    kotlin = client.get("/api/v1/analytics/rating-usage", params={"months": 1, "platform": "android-kotlin"}).json()
    assert kotlin["byMonth"][0]["viewers"] == 0

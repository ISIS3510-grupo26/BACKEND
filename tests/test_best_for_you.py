"""Pruebas de la BQ6: menor tiempo de espera y mayor compatibilidad con el perfil de gusto."""
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import best_for_you, spots
from app.services.best_for_you_service import taste_match, wait_score

NOW = "2026-10-26T17:00:00+00:00"


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    fixed = lambda: datetime.fromisoformat(NOW)
    app.dependency_overrides[spots.current_time] = fixed
    app.dependency_overrides[best_for_you.current_time] = fixed
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def report(client, spot, minutes, reported_at):
    body = {"reportId": str(uuid.uuid4()), "minutes": minutes, "platform": "android-kotlin", "reportedAt": reported_at}
    assert client.post(f"/api/v1/spots/{spot}/wait-times", json=body).status_code == 201


def ranking(client, **params):
    r = client.get("/api/v1/recommendations/best-for-you", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_without_profile_ranks_by_wait_time(client):
    report(client, "conda-de-bons", 30, "2026-10-26T16:50:00Z")
    report(client, "nitro-coffee", 2, "2026-10-26T16:40:00Z")
    report(client, "green-bowl-co", 10, "2026-10-26T16:55:00Z")

    body = ranking(client)
    assert body["personalized"] is False
    assert len(body["spots"]) == 7  # sin limit vuelve todo el catalogo: la app hace su propio ranking
    ids = [s["spotId"] for s in body["spots"]]
    assert ids[:2] == ["nitro-coffee", "green-bowl-co"]
    assert ids[-1] == "conda-de-bons"  # 30 min: peor que los que no tienen reporte (neutros)

    nitro = body["spots"][0]
    assert nitro["rank"] == 1 and nitro["waitMinutes"] == 2 and nitro["minutesAgo"] == 20
    assert nitro["tasteMatch"] is None and nitro["score"] == nitro["waitScore"] == 95
    assert nitro["cuisine"] == "Café & Bakery"


def test_old_reports_do_not_count(client):
    report(client, "nitro-coffee", 1, "2026-10-26T10:00:00Z")  # 7 horas antes: ya no dice nada de la fila

    nitro = next(s for s in ranking(client)["spots"] if s["spotId"] == "nitro-coffee")
    assert nitro["waitMinutes"] == 1 and nitro["isRecent"] is False
    assert nitro["waitScore"] == 50

    nitro = next(s for s in ranking(client, freshMinutes=480)["spots"] if s["spotId"] == "nitro-coffee")
    assert nitro["isRecent"] is True and nitro["waitScore"] == 98


def test_profile_mixes_wait_and_taste(client):
    report(client, "la-esquina-burger-lab", 4, "2026-10-26T16:50:00Z")
    report(client, "green-bowl-co", 36, "2026-10-26T16:50:00Z")

    body = ranking(client, budget="Budget-friendly", dietary=["Vegetarian"], cuisines=["Crepas & Bowls"], limit=3)
    assert body["personalized"] is True
    assert len(body["spots"]) == 3

    by_id = {s["spotId"]: s for s in ranking(client, budget="Budget-friendly", dietary=["Vegetarian"],
                                            cuisines=["Crepas & Bowls"])["spots"]}
    bowl = by_id["green-bowl-co"]
    assert bowl["tasteMatch"] == 100 and bowl["waitScore"] == 10 and bowl["score"] == 55.0
    burger = by_id["la-esquina-burger-lab"]
    assert burger["tasteMatch"] == 0 and burger["waitScore"] == 90 and burger["score"] == 45.0
    # Poodle Pizza no tiene reporte (50) pero es barato y vegetariano (50 de 100): 50.
    assert by_id["poodle-pizza-slices"]["score"] == 50.0
    assert [s["rank"] for s in body["spots"]] == [1, 2, 3]


def test_validation(client):
    assert client.get("/api/v1/recommendations/best-for-you", params={"freshMinutes": 1}).status_code == 422
    assert client.get("/api/v1/recommendations/best-for-you", params={"limit": 0}).status_code == 422


def test_catalog_exposes_coordinates_for_the_map(client):
    spots_list = client.get("/api/v1/spots").json()
    assert all(s["latitude"] is not None and s["longitude"] is not None for s in spots_list)
    assert client.get("/api/v1/spots/nitro-coffee").json()["latitude"] == pytest.approx(4.6019)


def test_wait_score_scale():
    assert wait_score(0, True) == 100
    assert wait_score(20, True) == 50
    assert wait_score(60, True) == 0
    assert wait_score(None, False) == 50 and wait_score(5, False) == 50


def test_taste_match_only_counts_filled_preferences():
    spot = {"name": "Conda de Bons", "subtitle": "Burgers & Fries • North Quad Plaza",
            "is_vegetarian": False, "is_budget": False}
    assert taste_match(spot, None, [], ["Artisan Burgers"]) == 100
    assert taste_match(spot, "Budget-friendly", [], ["Artisan Burgers"]) == 71   # 50 de 70
    assert taste_match(spot, "Treat yourself", ["Vegan"], []) == 40             # 20 de 50
    assert taste_match(spot, None, ["Halal"], []) == 50                         # nada que medir: neutro
    assert taste_match(spot, None, [], ["Burgers"]) == 100                      # cocina fuera del mapa


def test_rounding_matches_the_kotlin_client():
    # 92.5 y 62.5: round() de Python daria 92 y 62; la app (roundToInt) da 93 y 63.
    assert wait_score(3, True) == 93
    spot = {"name": "X", "subtitle": "Pizza • Gate", "is_vegetarian": False, "is_budget": False}
    assert taste_match(spot, None, ["Vegan"], ["Wood-Fired Pizza"]) == 63   # 50 de 80 = 62.5

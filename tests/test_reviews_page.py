"""Reseñas paginadas (vista "All reviews") y votos Helpful."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

SPOT = "poodle-pizza-slices"  # el catalogo trae 1 reseña; los tests agregan 5 de usuarios
REVIEWS = f"/api/v1/spots/{SPOT}/reviews"
USER_REVIEWS = [  # (estrellas, texto), en el orden en que se publican
    (5, "Los ÑOQUIS de la casa, deliciosos"),
    (1, "Cold pizza and a long line"),
    (4, "Good crust, fair price"),
    (2, "Too salty for me"),
    (3, "Día normal, nada especial"),
]


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def reviewed(client):
    """Publica las 5 reseñas de usuarios y devuelve los tokens de sus autores."""
    tokens = []
    for i, (stars, text) in enumerate(USER_REVIEWS):
        token = client.post("/api/v1/auth/signup", json={"email": f"u{i}@uniandes.edu.co", "password": "segura123"}
                            ).json()["accessToken"]
        assert client.post(REVIEWS, json={"stars": stars, "text": text}, headers=bearer(token)).status_code == 201
        tokens.append(token)
    return tokens


def page(client, **params):
    r = client.get(REVIEWS, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def texts(body):
    return [item["text"] for item in body["items"]]


def test_pages_cover_every_review_once(client, reviewed):
    pages = [page(client, pageSize=4, page=n) for n in (1, 2, 3)]

    assert [(p["page"], p["pageSize"], p["total"]) for p in pages] == [(1, 4, 6), (2, 4, 6), (3, 4, 6)]
    seen = [item["id"] for p in pages for item in p["items"]]
    assert len(seen) == 6 and len(set(seen)) == 6
    assert pages[2]["items"] == []
    assert all("helpfulCount" in item and "id" in item for item in pages[0]["items"])


def test_sort_orders(client, reviewed):
    newest = page(client, sort="newest")
    assert texts(newest)[:5] == [text for _, text in reversed(USER_REVIEWS)]  # las de usuarios, la ultima primero
    assert newest["items"][5]["createdAt"] is None                           # despues la del catalogo

    assert [i["stars"] for i in page(client, sort="highest")["items"]][:2] == [5, 5]
    assert [i["stars"] for i in page(client, sort="lowest")["items"]][0] == 1
    helpful = [i["helpfulCount"] for i in page(client, sort="helpful")["items"]]
    assert helpful == sorted(helpful, reverse=True)


def test_star_filter_and_search_ignore_case(client, reviewed):
    assert texts(page(client, stars=1)) == ["Cold pizza and a long line"]
    assert page(client, stars=2)["total"] == 1

    assert texts(page(client, q="ñoquis")) == ["Los ÑOQUIS de la casa, deliciosos"]  # mayusculas con tilde/ñ
    assert texts(page(client, q="DÍA")) == ["Día normal, nada especial"]
    assert page(client, q="PIZZA", stars=1)["total"] == 1
    assert page(client, q="no existe")["total"] == 0


def test_unknown_spot_is_404_and_bad_params_422(client):
    assert client.get("/api/v1/spots/nope/reviews").status_code == 404
    for params in ({"sort": "random"}, {"stars": 6}, {"page": 0}, {"pageSize": 51}):
        assert client.get(REVIEWS, params=params).status_code == 422, params


def _helpful_count(client, review_id):
    return next(i["helpfulCount"] for i in page(client, pageSize=50)["items"] if i["id"] == review_id)


def test_helpful_is_idempotent_and_counts_each_user_once(client, reviewed):
    review_id = page(client, stars=4)["items"][0]["id"]
    url = f"{REVIEWS}/{review_id}/helpful"

    assert client.put(url, headers=bearer(reviewed[0])).status_code == 204
    assert client.put(url, headers=bearer(reviewed[0])).status_code == 204   # repetido: sin cambios
    assert client.put(url, params={"userId": "dev-ana"}).status_code == 204  # sin token, id de desarrollo
    assert _helpful_count(client, review_id) == 2

    assert client.delete(url, headers=bearer(reviewed[0])).status_code == 204
    assert client.delete(url, headers=bearer(reviewed[0])).status_code == 204  # repetido: sin cambios
    assert _helpful_count(client, review_id) == 1


def test_helpful_needs_a_user_and_a_review_of_that_spot(client, reviewed):
    review_id = page(client, stars=4)["items"][0]["id"]

    assert client.put(f"{REVIEWS}/{review_id}/helpful").status_code == 401
    assert client.put(f"/api/v1/spots/nitro-coffee/reviews/{review_id}/helpful", params={"userId": "dev"}).status_code == 404
    assert client.put(f"{REVIEWS}/999999/helpful", params={"userId": "dev"}).status_code == 404
    assert client.delete(f"{REVIEWS}/999999/helpful", params={"userId": "dev"}).status_code == 404


def test_votes_on_catalog_reviews_survive_a_restart(client):
    from app.db import connect
    from app.repositories.spots_repository import SpotsRepository

    catalog = page(client)["items"][0]
    client.put(f"{REVIEWS}/{catalog['id']}/helpful", params={"userId": "dev-ana"})

    conn = connect()
    try:
        SpotsRepository(conn).sync_catalog()  # lo que corre en cada arranque del servidor
    finally:
        conn.close()

    after = page(client)["items"][0]
    assert (after["id"], after["helpfulCount"]) == (catalog["id"], catalog["helpfulCount"] + 1)

# Pruebas de preferencias, compatibilidad (smart feature) y cambio de contraseña de punta a punta.
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

MEXICAN = {"mainCuisine": "Mexican", "mealStyle": "Quick & casual", "flavors": ["Spicy", "Savory"],
           "interests": ["Something new", "Good value"], "diet": "No specific diet", "avoid": [], "allergies": []}


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def account(client, email, password="segura123"):
    s = client.post("/api/v1/auth/signup", json={"email": email, "password": password}).json()
    return s["userId"], {"Authorization": f"Bearer {s['accessToken']}"}


def save_prefs(client, user_id, headers, **changes):
    r = client.put(f"/api/v1/users/{user_id}/preferences", json={**MEXICAN, **changes}, headers=headers)
    assert r.status_code == 200, r.text


def matches(client, user_id, headers):
    return {m["spotId"]: m for m in client.get(f"/api/v1/users/{user_id}/matches", headers=headers).json()}


# ---------- Preferencias ----------

def test_preferences_round_trip(client):
    me, h = account(client, "vale@uniandes.edu.co")
    url = f"/api/v1/users/{me}/preferences"
    empty = client.get(url, headers=h).json()
    assert empty["saved"] is False and empty["diet"] == "No specific diet" and empty["flavors"] == []

    assert client.put(url, json={**MEXICAN, "flavors": ["Spicy", "Spicy", "Savory"]}, headers=h).status_code == 200
    saved = client.get(url, headers=h).json()
    assert saved["saved"] is True and saved["flavors"] == ["Spicy", "Savory"]  # sin repetidos
    assert saved["mainCuisine"] == "Mexican"

    # Solo el dueño, con token de otra cuenta 403, sin token sobre una cuenta registrada 401.
    _, other = account(client, "otro@uniandes.edu.co")
    assert client.get(url, headers=other).status_code == 403
    assert client.get(url).status_code == 401


# ---------- Smart feature: compatibilidad ----------

def test_compatibility_follows_the_profile(client):
    me, h = account(client, "vale@uniandes.edu.co")
    save_prefs(client, me, h)
    scores = matches(client, me, h)
    assert len(scores) == 7
    best_spot = max(scores.values(), key=lambda m: m["compatibility"])
    assert best_spot["spotId"] == "taqueria-la-esquina"  # su cocina, sus sabores, su estilo y es economica
    assert all(0 <= m["compatibility"] <= 100 for m in scores.values())

    # Cambiar el perfil cambia el resultado.
    save_prefs(client, me, h, mainCuisine="Bakery & desserts", flavors=["Sweet"])
    assert matches(client, me, h)["nitro-coffee"]["compatibility"] > scores["nitro-coffee"]["compatibility"]


def test_dietary_restrictions_are_hard_filters(client):
    me, h = account(client, "vale@uniandes.edu.co")
    save_prefs(client, me, h, diet="Vegetarian", allergies=["Dairy"])
    scores = matches(client, me, h)
    assert scores["taqueria-la-esquina"]["dietaryConflict"] == "No vegetarian options"
    assert scores["nitro-coffee"]["dietaryConflict"] == "Most dishes contain dairy"
    assert scores["green-bowl-co"]["dietaryConflict"] is None


def test_avoided_items_lower_the_score(client):
    me, h = account(client, "vale@uniandes.edu.co")
    save_prefs(client, me, h)
    before = matches(client, me, h)["taqueria-la-esquina"]["compatibility"]
    save_prefs(client, me, h, avoid=["Very spicy food"])
    assert matches(client, me, h)["taqueria-la-esquina"]["compatibility"] == before - 10


def test_students_with_similar_taste_change_the_score(client):
    me, h = account(client, "vale@uniandes.edu.co")
    twin, th = account(client, "gemela@uniandes.edu.co")
    opposite, oh = account(client, "opuesto@uniandes.edu.co")
    save_prefs(client, me, h)
    save_prefs(client, twin, th)
    save_prefs(client, opposite, oh, mainCuisine="Italian", mealStyle="Comfort food", flavors=["Sweet"],
               interests=["Something familiar"], diet="Pescatarian")
    before = matches(client, me, h)["poodle-pizza-slices"]["compatibility"]

    # Alguien con gustos opuestos (similitud 0) no cambia nada...
    client.post("/api/v1/spots/poodle-pizza-slices/reviews", json={"stars": 5}, headers=oh)
    assert matches(client, me, h)["poodle-pizza-slices"]["compatibility"] == before
    client.post("/api/v1/spots/poodle-pizza-slices/reviews", json={"stars": 1}, headers=th)
    assert matches(client, me, h)["poodle-pizza-slices"]["compatibility"] < before


def test_without_profile_uses_general_rating(client):
    me, h = account(client, "vale@uniandes.edu.co")
    scores = matches(client, me, h)
    assert scores["nitro-coffee"]["compatibility"] == 100  # rating 5.0 del catalogo
    assert all(m["dietaryConflict"] is None for m in scores.values())


# ---------- Cambiar contraseña, de punta a punta (como lo usa la app) ----------

def test_change_password_end_to_end(client):
    me, old = account(client, "vale@uniandes.edu.co")
    url = "/api/v1/auth/change-password"

    wrong = client.post(url, json={"currentPassword": "incorrecta", "newPassword": "nueva12345"}, headers=old)
    assert wrong.status_code == 400 and wrong.json()["detail"] == "Current password is incorrect"
    assert client.get("/api/v1/auth/me", headers=old).status_code == 200  # un 400 no cierra la sesion

    # Regla nueva de Esteban, tildes y emojis valen, de 8 a 128 caracteres.
    new_password = "contraseña🌮nueva"
    ok = client.post(url, json={"currentPassword": "segura123", "newPassword": new_password}, headers=old)
    assert ok.status_code == 200, ok.text
    new = {"Authorization": f"Bearer {ok.json()['accessToken']}"}

    assert client.get("/api/v1/auth/me", headers=old).status_code == 401   # la sesion vieja se cerro
    assert client.get("/api/v1/auth/me", headers=new).status_code == 200   # la de la app sigue

    login = lambda pw: client.post("/api/v1/auth/login", json={"email": "vale@uniandes.edu.co", "password": pw})
    assert login("segura123").status_code == 401
    relogin = login(new_password)
    assert relogin.status_code == 200
    # El token del login despues del cambio sirve (antes daba un token con la version vieja).
    again = {"Authorization": f"Bearer {relogin.json()['accessToken']}"}
    assert client.get("/api/v1/auth/me", headers=again).status_code == 200
    assert client.get(f"/api/v1/users/{me}/preferences", headers=again).status_code == 200
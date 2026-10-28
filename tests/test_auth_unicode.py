"""Pruebas de contraseñas con emojis y tildes: regla de 8 a 128 caracteres, NFKC y migracion de hashes legacy."""
import sqlite3
import unicodedata
import uuid

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

EMAIL = "ana@uniandes.edu.co"
HEART = "❤️"  # ❤️: 2 code points, 6 bytes en UTF-8


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def signup(client, password, email=EMAIL):
    return client.post("/api/v1/auth/signup", json={"email": email, "password": password})


def login(client, password, email=EMAIL):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def stored_user(email=EMAIL):
    conn = sqlite3.connect(settings.db_path)
    row = conn.execute("SELECT password_hash, token_version FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row


# ---------- Emojis: ya no hay limite de 72 bytes ----------

@pytest.mark.parametrize("password", ["😀" * 19, HEART * 18])  # 76 y 108 bytes: antes se rechazaban
def test_emoji_passwords_signup_and_login(client, password):
    assert len(password.encode()) > 72
    assert signup(client, password).status_code == 201
    assert login(client, password).status_code == 200
    assert login(client, "😀" * 18).status_code == 401  # bcrypt no trunco: un emoji menos no entra


def test_two_emojis_are_too_short(client):
    r = signup(client, "😀😀")  # 8 bytes pero 2 caracteres
    assert r.status_code == 422
    assert "8 to 128 characters" in r.text


@pytest.mark.parametrize("length, status", [(128, 201), (129, 422)])
def test_length_limit_in_characters(client, length, status):
    assert signup(client, "a" * length).status_code == status


# ---------- NFKC: la misma contraseña desde teclados distintos ----------

@pytest.mark.parametrize("signup_form, login_form", [("NFC", "NFD"), ("NFD", "NFC")])
def test_nfc_and_nfd_are_the_same_password(client, signup_form, login_form):
    typed_at_signup = unicodedata.normalize(signup_form, "contraseña1")
    typed_at_login = unicodedata.normalize(login_form, "contraseña1")
    assert typed_at_signup != typed_at_login
    assert signup(client, typed_at_signup).status_code == 201
    assert login(client, typed_at_login).status_code == 200


# ---------- Migracion de hashes legacy ----------

def test_legacy_hash_logs_in_and_is_upgraded(client):
    # Usuario creado antes del esquema v2: bcrypt directo sobre la contraseña en NFC.
    legacy = bcrypt.hashpw("contraseña1".encode(), bcrypt.gensalt()).decode()
    conn = sqlite3.connect(settings.db_path)
    conn.execute("INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)", (str(uuid.uuid4()), EMAIL, legacy))
    conn.commit()
    conn.close()

    assert login(client, "otra12345").status_code == 401
    assert stored_user() == (legacy, 0)

    first = login(client, unicodedata.normalize("NFD", "contraseña1"))  # legacy tambien acepta la forma normalizada
    assert first.status_code == 200
    password_hash, token_version = stored_user()
    assert password_hash.startswith("v2$") and token_version == 0  # rehash silencioso, sin cerrar sesiones
    assert client.get("/api/v1/auth/me", headers=bearer(first.json()["accessToken"])).status_code == 200
    assert login(client, "contraseña1").status_code == 200


# ---------- Cambiar contraseña ----------

def test_change_password_with_emojis(client):
    s = signup(client, "segura123").json()
    old = bearer(s["accessToken"])
    url = "/api/v1/auth/change-password"
    new_password = "🍕🌮🍣🍜" * 5  # 20 emojis, 80 bytes

    assert client.post(url, json={"currentPassword": "segura123", "newPassword": "😀😀"}, headers=old).status_code == 422

    ok = client.post(url, json={"currentPassword": "segura123", "newPassword": new_password}, headers=old)
    assert ok.status_code == 200, ok.text
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    assert client.get("/api/v1/auth/me", headers=bearer(ok.json()["accessToken"])).status_code == 200

    assert login(client, "segura123").status_code == 401
    relogin = login(client, new_password)
    assert relogin.status_code == 200
    assert client.get("/api/v1/auth/me", headers=bearer(relogin.json()["accessToken"])).status_code == 200


def test_same_password_compares_normalized(client):
    s = signup(client, "contraseña1").json()
    r = client.post("/api/v1/auth/change-password", headers=bearer(s["accessToken"]),
                    json={"currentPassword": "contraseña1", "newPassword": unicodedata.normalize("NFD", "contraseña1")})
    assert r.status_code == 400
    assert r.json()["detail"] == "New password must be different from the current one"

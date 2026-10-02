import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


@pytest.fixture
def client(tmp_path):
    object.__setattr__(settings, "db_path", str(tmp_path / "test.db"))
    with TestClient(app) as c:
        yield c


def event(duration_ms, success=True, device="Pixel 7", os_version="14", error=None, spot="nitro-coffee"):
    return {
        "eventId": str(uuid.uuid4()),
        "screen": "restaurant_detail",
        "spotId": spot,
        "durationMs": duration_ms,
        "success": success,
        "httpStatus": 200 if success else None,
        "errorType": error,
        "deviceModel": device,
        "osName": "Android",
        "osVersion": os_version,
        "platform": "android-kotlin",
        "occurredAt": "2026-10-01T12:00:00Z",
    }


def test_list_and_detail_spots(client):
    spots = client.get("/api/v1/spots").json()
    assert len(spots) == 7
    assert spots[0]["id"] == "conda-de-bons"
    assert "menu" not in spots[0]
    assert spots[0]["emojiBackground"] == "#FFFBEB"

    detail = client.get("/api/v1/spots/la-esquina-burger-lab").json()
    assert len(detail["menu"]) == 4
    assert detail["menu"][1]["isStudentPick"] is True
    assert len(detail["reviews"]) == 3

    assert client.get("/api/v1/spots/nope").status_code == 404


def test_ingest_is_idempotent(client):
    e = event(1000)
    r1 = client.post("/api/v1/telemetry/page-loads", json={"events": [e]})
    r2 = client.post("/api/v1/telemetry/page-loads", json={"events": [e]})
    assert r1.status_code == 202 and r1.json() == {"accepted": 1, "duplicates": 0}
    assert r2.json() == {"accepted": 0, "duplicates": 1}


def test_slow_page_loads_by_device_and_os(client):
    events = [
        event(1200, device="Pixel 7", os_version="14"),
        event(3500, device="Pixel 7", os_version="14"),
        event(4100, device="Galaxy A14", os_version="13"),
        event(3000, device="Galaxy A14", os_version="13"),  # exactamente 3 s no es "mas de 3 s"
        event(9000, success=False, error="TIMEOUT"),         # fallidas no cuentan para BQ1
    ]
    client.post("/api/v1/telemetry/page-loads", json={"events": events})

    report = client.get("/api/v1/analytics/slow-page-loads").json()
    assert report["thresholdMs"] == 3000
    assert (report["totalLoads"], report["slowLoads"], report["slowPercentage"]) == (4, 2, 50.0)
    by_device = {g["key"]: g["slowPercentage"] for g in report["byDevice"]}
    assert by_device == {"Pixel 7": 50.0, "Galaxy A14": 50.0}
    assert {g["key"] for g in report["byOs"]} == {"Android 14", "Android 13"}
    assert {g["key"] for g in report["byDeviceAndOs"]} == {"Pixel 7 / Android 14", "Galaxy A14 / Android 13"}


def test_failed_requests(client):
    events = [event(800), event(900), event(10000, success=False, error="TIMEOUT"),
              event(50, success=False, error="HTTP_503", spot="green-bowl-co")]
    client.post("/api/v1/telemetry/page-loads", json={"events": events})

    report = client.get("/api/v1/analytics/failed-requests").json()
    assert (report["totalRequests"], report["failedRequests"], report["failurePercentage"]) == (4, 2, 50.0)
    by_error = {g["key"]: g["failurePercentage"] for g in report["byErrorType"]}
    assert by_error == {"TIMEOUT": 25.0, "HTTP_503": 25.0}
    by_spot = {g["key"]: g["failurePercentage"] for g in report["bySpot"]}
    assert by_spot == {"green-bowl-co": 100.0, "nitro-coffee": pytest.approx(33.33)}


def test_empty_reports(client):
    assert client.get("/api/v1/analytics/slow-page-loads").json()["slowPercentage"] == 0.0
    assert client.get("/api/v1/analytics/failed-requests").json()["failurePercentage"] == 0.0


def test_spot_views_and_searches_by_hour(client):
    # occurredAt es UTC; Bogota = UTC-5 -> 17:xxZ es la hora local 12, 13:xxZ es la hora local 8.
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date().isoformat()

    def ev(spot, utc_time, screen="restaurant_detail", success=True):
        e = event(500 if screen == "restaurant_detail" else 0, success=success, spot=spot,
                  error=None if success else "TIMEOUT")
        e["occurredAt"], e["screen"] = f"{today}T{utc_time}Z", screen
        return e

    client.post("/api/v1/telemetry/page-loads", json={"events": [
        ev("conda-de-bons", "17:05:00"), ev("conda-de-bons", "17:40:00"),
        ev("conda-de-bons", "17:50:00", screen="search"),            # busqueda que termino en este restaurante
        ev("green-bowl-co", "17:10:00", success=False),              # una vista fallida sigue siendo interes
        ev("green-bowl-co", "17:20:00", screen="search"), ev("green-bowl-co", "17:30:00", screen="search"),
        ev("nitro-coffee", "13:15:00"),
    ]})

    r = client.get("/api/v1/analytics/spot-views-by-hour").json()
    assert r["question"].startswith("Which restaurants receive the highest number of page views and searches")
    assert [h["hour"] for h in r["hours"]] == [8, 12]
    noon = r["hours"][1]
    assert (noon["totalPageViews"], noon["totalSearches"]) == (3, 3)
    assert [(s["rank"], s["spotId"], s["pageViews"], s["searches"], s["total"]) for s in noon["spots"]] == [
        (1, "conda-de-bons", 2, 1, 3), (2, "green-bowl-co", 1, 2, 3)]  # empate: gana el de mas vistas
    assert noon["spots"][0]["name"] == "Conda de Bons"

    # La app pide solo la hora actual del celular.
    r = client.get("/api/v1/analytics/spot-views-by-hour", params={"hour": 8, "limit": 1}).json()
    assert len(r["hours"]) == 1 and r["hours"][0]["hour"] == 8
    assert [s["spotId"] for s in r["hours"][0]["spots"]] == ["nitro-coffee"]

    # Una hora sin actividad devuelve la hora con ranking vacio (la UI no tiene que adivinar).
    r = client.get("/api/v1/analytics/spot-views-by-hour", params={"hour": 3}).json()
    assert r["hours"] == [{"hour": 3, "totalPageViews": 0, "totalSearches": 0, "spots": []}]

    # Fuera de la ventana de dias no cuenta; dentro de una ventana mayor si.
    old = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT17:00:00Z")
    e = event(300, spot="poodle-pizza-slices"); e["occurredAt"] = old
    client.post("/api/v1/telemetry/page-loads", json={"events": [e]})
    r = client.get("/api/v1/analytics/spot-views-by-hour", params={"hour": 12}).json()
    assert all(s["spotId"] != "poodle-pizza-slices" for s in r["hours"][0]["spots"])
    r = client.get("/api/v1/analytics/spot-views-by-hour", params={"hour": 12, "days": 60}).json()
    assert any(s["spotId"] == "poodle-pizza-slices" for s in r["hours"][0]["spots"])


def test_search_events_do_not_affect_bq1_bq2(client):
    e = event(0, spot="conda-de-bons"); e["screen"] = "search"
    client.post("/api/v1/telemetry/page-loads", json={"events": [e, event(4000)]})
    slow = client.get("/api/v1/analytics/slow-page-loads").json()
    failed = client.get("/api/v1/analytics/failed-requests").json()
    assert (slow["totalLoads"], slow["slowLoads"]) == (1, 1)
    assert failed["totalRequests"] == 1


def test_existing_db_gets_location_and_opening_hours(tmp_path):
    # Simula una base creada antes de la BQ5: sin coordenadas ni horarios.
    import sqlite3
    db = str(tmp_path / "old.db")
    object.__setattr__(settings, "db_path", db)
    with TestClient(app):
        pass
    conn = sqlite3.connect(db)
    conn.executescript("DELETE FROM spot_opening_hours; "
                       "ALTER TABLE spots DROP COLUMN latitude; ALTER TABLE spots DROP COLUMN longitude;")
    conn.close()

    with TestClient(app) as c:
        assert len(c.get("/api/v1/spots").json()) == 7
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM spots WHERE latitude IS NULL OR longitude IS NULL").fetchone()[0] == 0
    vagon = conn.execute("SELECT day_of_week, opens_at, closes_at FROM spot_opening_hours "
                         "WHERE spot_id = 'el-vagon-street-food' ORDER BY day_of_week").fetchall()
    conn.close()
    assert vagon == [(d, "17:00", "02:00") for d in range(6)]


# ---------- BQ5: favoritos abiertos y a <= 15 min caminando ----------

NITRO = {"lat": 4.6019, "lng": -74.0658}  # parado en Nitro Coffee (coordenadas del seed)


@pytest.fixture
def at_time():
    """Fija el "ahora" del servidor (UTC). Bogota = UTC-5."""
    from datetime import datetime
    from app.routers import users

    def set_now(iso_utc: str):
        app.dependency_overrides[users.current_time] = lambda: datetime.fromisoformat(iso_utc)
    yield set_now
    app.dependency_overrides.clear()


def save(client, user, *spots):
    for s in spots:
        assert client.put(f"/api/v1/users/{user}/favorites/{s}").status_code == 204


def test_favorites_crud(client):
    save(client, "ana", "nitro-coffee", "green-bowl-co")
    save(client, "ana", "nitro-coffee")                                     # idempotente
    assert client.put("/api/v1/users/ana/favorites/nope").status_code == 404
    assert [s["id"] for s in client.get("/api/v1/users/ana/favorites").json()] == ["nitro-coffee", "green-bowl-co"]

    assert client.delete("/api/v1/users/ana/favorites/nitro-coffee").status_code == 204
    assert client.delete("/api/v1/users/ana/favorites/nitro-coffee").status_code == 204  # idempotente
    assert [s["id"] for s in client.get("/api/v1/users/ana/favorites").json()] == ["green-bowl-co"]
    assert client.get("/api/v1/users/otro/favorites").json() == []


def test_nearby_favorites_open_now_sorted_by_walk(client, at_time):
    save(client, "ana", "taqueria-la-esquina", "conda-de-bons", "nitro-coffee", "green-bowl-co", "el-vagon-street-food")
    save(client, "beto", "la-esquina-burger-lab")
    at_time("2026-09-30T17:00:00+00:00")  # miercoles 12:00 en Bogota: El Vagon (17:00-02:00) esta cerrado

    r = client.get("/api/v1/users/ana/favorites/nearby", params={**NITRO, "maxWalkMinutes": 15})
    assert r.status_code == 200
    body = r.json()
    assert [f["id"] for f in body] == ["nitro-coffee", "green-bowl-co", "conda-de-bons", "taqueria-la-esquina"]
    assert set(body[0]) == {"id", "name", "emoji", "distanceMeters", "walkMinutes", "closesAt"}
    assert body[0]["distanceMeters"] == 0 and body[0]["walkMinutes"] == 0.0
    assert [f["walkMinutes"] for f in body] == sorted(f["walkMinutes"] for f in body)
    green = body[1]  # ~95 m en linea recta -> ~1.2 min a 80 m/min
    assert 85 <= green["distanceMeters"] <= 105 and green["walkMinutes"] == round(green["distanceMeters"] / 80, 1)
    assert body[3]["closesAt"] == "22:00"  # la taqueria abre justo a las 12:00

    near = client.get("/api/v1/users/ana/favorites/nearby", params={**NITRO, "maxWalkMinutes": 1}).json()
    assert [f["id"] for f in near] == ["nitro-coffee"]


def test_nearby_favorites_overnight_hours(client, at_time):
    save(client, "ana", "el-vagon-street-food", "nitro-coffee")
    at_time("2026-10-03T06:30:00+00:00")  # sabado 01:30 en Bogota: sigue abierta la franja del viernes 17:00-02:00
    r = client.get("/api/v1/users/ana/favorites/nearby", params=NITRO).json()
    assert [(f["id"], f["closesAt"]) for f in r] == [("el-vagon-street-food", "02:00")]

    at_time("2026-10-05T06:30:00+00:00")  # lunes 01:30: el domingo no abre, nada abierto
    assert client.get("/api/v1/users/ana/favorites/nearby", params=NITRO).json() == []

    # La zona horaria es configurable como en la BQ3: 06:30 UTC es sabado 06:30 en UTC+0 -> todo cerrado.
    at_time("2026-10-03T06:30:00+00:00")
    assert client.get("/api/v1/users/ana/favorites/nearby", params={**NITRO, "tzOffsetMinutes": 0}).json() == []


def test_nearby_favorites_validation(client):
    assert client.get("/api/v1/users/ana/favorites/nearby", params={"lat": 4.6}).status_code == 422
    assert client.get("/api/v1/users/ana/favorites/nearby", params={"lat": 91, "lng": 0}).status_code == 422
    assert client.get("/api/v1/users/sin-favoritos/favorites/nearby", params=NITRO).json() == []


def test_haversine_and_walking_speed():
    from app.services.favorites_service import WALKING_SPEED_M_PER_MIN, haversine_m
    assert haversine_m(0, 0, 1, 0) == pytest.approx(111_195, rel=1e-3)  # 1 grado de latitud
    assert WALKING_SPEED_M_PER_MIN * 15 == 1200                          # 15 min ~ 1,2 km


# ---------- BQ7: usuarios que agregan favoritos cada mes ----------

def favorite_event(user, spot, occurred_at):
    e = event(0, spot=spot)
    e.update(screen="favorite_added", userId=user, occurredAt=occurred_at)
    return e


def test_favorite_added_requires_user_and_spot(client):
    e = favorite_event("ana", "nitro-coffee", "2026-10-01T12:00:00Z")
    del e["userId"]
    assert client.post("/api/v1/telemetry/page-loads", json={"events": [e]}).status_code == 422
    e = favorite_event("ana", None, "2026-10-01T12:00:00Z")
    assert client.post("/api/v1/telemetry/page-loads", json={"events": [e]}).status_code == 422
    ok = favorite_event("ana", "nitro-coffee", "2026-10-01T12:00:00Z")
    assert client.post("/api/v1/telemetry/page-loads", json={"events": [ok]}).json() == {"accepted": 1, "duplicates": 0}


def test_monthly_active_favoriters(client):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    iso = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    month = lambda dt: (dt + timedelta(minutes=-300)).strftime("%Y-%m")  # mes local en Bogota
    last_month, old = now - timedelta(days=35), now - timedelta(days=120)

    client.post("/api/v1/telemetry/page-loads", json={"events": [
        favorite_event("ana", "nitro-coffee", iso(now)),
        favorite_event("ana", "green-bowl-co", iso(now)),     # mismo usuario, mismo mes: cuenta una vez
        favorite_event("beto", "nitro-coffee", iso(now)),
        favorite_event("ana", "conda-de-bons", iso(last_month)),
        favorite_event("caro", "conda-de-bons", iso(old)),    # fuera de la ventana de 3 meses
        event(500, spot="nitro-coffee"),                      # otras pantallas no cuentan
    ]})

    r = client.get("/api/v1/analytics/monthly-active-favoriters", params={"months": 3}).json()
    assert r["question"] == "How many active users add one or more restaurants to their favorites each month?"
    assert (r["months"], r["tzOffsetMinutes"]) == (3, -300)
    assert len(r["byMonth"]) == 3 and r["byMonth"][-1]["month"] == month(now)
    by_month = {m["month"]: (m["activeFavoriters"], m["favoriteEvents"]) for m in r["byMonth"]}
    assert by_month[month(now)] == (2, 3)
    assert by_month[month(last_month)] == (1, 1)
    assert month(old) not in by_month

    r = client.get("/api/v1/analytics/monthly-active-favoriters", params={"months": 1, "platform": "flutter"}).json()
    assert r["byMonth"] == [{"month": month(now), "activeFavoriters": 0, "favoriteEvents": 0}]


def test_monthly_active_favoriters_uses_local_calendar_month(client):
    from datetime import datetime, timezone
    from app.db import connect
    from app.repositories.telemetry_repository import TelemetryRepository
    from app.services.analytics_service import AnalyticsService

    # 1 oct 03:00 UTC = 30 sep 22:00 en Bogota: es un favorito de septiembre.
    client.post("/api/v1/telemetry/page-loads", json={"events": [
        favorite_event("ana", "nitro-coffee", "2026-10-01T03:00:00Z"),
        favorite_event("beto", "nitro-coffee", "2026-10-01T06:00:00Z"),
    ]})
    conn = connect()
    try:
        service = AnalyticsService(TelemetryRepository(conn))
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        bogota = service.monthly_active_favoriters(months=2, tz_offset_minutes=-300, now=now)
        assert [(m.month, m.active_favoriters) for m in bogota.by_month] == [("2026-09", 1), ("2026-10", 1)]
        utc = service.monthly_active_favoriters(months=2, tz_offset_minutes=0, now=now)
        assert [(m.month, m.active_favoriters) for m in utc.by_month] == [("2026-09", 0), ("2026-10", 2)]
        # La ventana cruza el cambio de anio.
        jan = service.monthly_active_favoriters(months=3, tz_offset_minutes=-300, now=datetime(2027, 1, 5, tzinfo=timezone.utc))
        assert [m.month for m in jan.by_month] == ["2026-11", "2026-12", "2027-01"]
    finally:
        conn.close()


def test_favorite_events_do_not_affect_other_bqs(client):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    view = event(4000); view["occurredAt"] = now
    client.post("/api/v1/telemetry/page-loads", json={"events": [favorite_event("ana", "nitro-coffee", now), view]})
    assert client.get("/api/v1/analytics/slow-page-loads").json()["totalLoads"] == 1
    assert client.get("/api/v1/analytics/failed-requests").json()["totalRequests"] == 1
    r = client.get("/api/v1/analytics/spot-views-by-hour").json()
    totals = (sum(h["totalPageViews"] for h in r["hours"]), sum(h["totalSearches"] for h in r["hours"]))
    assert totals == (1, 0)  # solo la carga del restaurante; el favorito no es vista ni busqueda


# ---------- Autenticacion ----------

def signup(client, email="ana@uniandes.edu.co", password="segura123"):
    r = client.post("/api/v1/auth/signup", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_signup_and_login(client):
    from datetime import datetime
    s = signup(client, email="  Ana@Uniandes.edu.co ")
    assert set(s) == {"userId", "email", "accessToken", "tokenType", "expiresIn", "expiresAt"}
    assert (s["email"], s["tokenType"], s["expiresIn"]) == ("ana@uniandes.edu.co", "bearer", 7 * 24 * 3600)
    assert datetime.fromisoformat(s["expiresAt"]).tzinfo is not None

    # Email repetido (sin importar mayusculas) -> 409; datos invalidos -> 422.
    dup = client.post("/api/v1/auth/signup", json={"email": "ANA@uniandes.edu.co", "password": "otra12345"})
    assert dup.status_code == 409
    assert client.post("/api/v1/auth/signup", json={"email": "no-es-email", "password": "segura123"}).status_code == 422
    assert client.post("/api/v1/auth/signup", json={"email": "b@x.co", "password": "corta"}).status_code == 422
    assert client.post("/api/v1/auth/signup", json={"email": "b@x.co", "password": "ñ" * 37}).status_code == 422  # 74 bytes

    ok = client.post("/api/v1/auth/login", json={"email": "ana@uniandes.edu.co", "password": "segura123"})
    assert ok.status_code == 200 and ok.json()["userId"] == s["userId"]
    for wrong in ({"email": "ana@uniandes.edu.co", "password": "incorrecta"},
                  {"email": "nadie@uniandes.edu.co", "password": "segura123"}):
        r = client.post("/api/v1/auth/login", json=wrong)
        assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
        assert r.json()["detail"] == "Invalid email or password"  # no revela si el email existe

    me = client.get("/api/v1/auth/me", headers=bearer(ok.json()["accessToken"]))
    assert me.json() == {"userId": s["userId"], "email": "ana@uniandes.edu.co"}
    assert client.get("/api/v1/auth/me").status_code == 401


def test_password_is_hashed(client):
    import sqlite3
    signup(client)
    conn = sqlite3.connect(settings.db_path)
    stored = conn.execute("SELECT password_hash FROM users").fetchone()[0]
    conn.close()
    assert stored.startswith("$2") and "segura123" not in stored


def test_token_validation(client):
    from datetime import datetime, timedelta, timezone
    import jwt
    from app.db import connect
    from app.repositories.users_repository import UsersRepository
    from app.services.auth_service import AuthService
    s = signup(client)
    user = {"id": s["userId"], "email": s["email"]}

    assert client.get("/api/v1/auth/me", headers=bearer(s["accessToken"])).status_code == 200
    conn = connect()
    service = AuthService(UsersRepository(conn))
    expired = service.issue_token(user, now=datetime.now(timezone.utc) - timedelta(days=8)).access_token
    conn.close()
    forged = jwt.encode({"sub": s["userId"], "exp": datetime.now(timezone.utc) + timedelta(days=1)}, "otro-secreto-de-al-menos-32-bytes!!",
                        algorithm="HS256")
    for headers in (bearer(expired), bearer(forged), bearer("no.es.jwt"), {"Authorization": "Bearer "},
                    {"Authorization": f"Basic {s['accessToken']}"}, {"Authorization": s["accessToken"]}):
        r = client.get("/api/v1/auth/me", headers=headers)
        assert r.status_code == 401, headers

    # Un header invalido nunca cae al override de desarrollo, ni siquiera con un userId que no es una cuenta.
    assert client.get("/api/v1/users/dev-user/favorites", headers=bearer(expired)).status_code == 401

    # Token valido de una cuenta que ya no existe.
    import sqlite3
    conn = sqlite3.connect(settings.db_path)
    conn.execute("DELETE FROM users"); conn.commit(); conn.close()
    assert client.get("/api/v1/auth/me", headers=bearer(s["accessToken"])).status_code == 401


def test_token_survives_restart(client):
    # Sin JWT_SECRET el secreto se genera una vez y queda en la base: reiniciar el servidor no invalida sesiones.
    s = signup(client)
    with TestClient(app) as restarted:
        assert restarted.get("/api/v1/auth/me", headers=bearer(s["accessToken"])).status_code == 200

def test_favorites_with_token_and_dev_override(client, at_time):
    s = signup(client)
    me, token = s["userId"], bearer(s["accessToken"])

    # Con token: solo sobre su propio userId.
    assert client.put(f"/api/v1/users/{me}/favorites/nitro-coffee", headers=token).status_code == 204
    assert [f["id"] for f in client.get(f"/api/v1/users/{me}/favorites", headers=token).json()] == ["nitro-coffee"]
    assert client.put("/api/v1/users/otro/favorites/nitro-coffee", headers=token).status_code == 403
    at_time("2026-09-30T17:00:00+00:00")  # miercoles 12:00 en Bogota
    nearby = client.get(f"/api/v1/users/{me}/favorites/nearby", params=NITRO, headers=token)
    assert [f["id"] for f in nearby.json()] == ["nitro-coffee"]

    # Sin token no se puede usar el id de una cuenta registrada...
    assert client.get(f"/api/v1/users/{me}/favorites").status_code == 401
    assert client.delete(f"/api/v1/users/{me}/favorites/nitro-coffee").status_code == 401
    assert client.get(f"/api/v1/users/{me}/favorites/nearby", params=NITRO).status_code == 401
    # ...pero el override de desarrollo (DEV_USER_ID) sigue funcionando igual que antes.
    save(client, "dev-camilo", "green-bowl-co")
    assert [f["id"] for f in client.get("/api/v1/users/dev-camilo/favorites/nearby", params=NITRO).json()] == ["green-bowl-co"]


def test_telemetry_with_token_and_dev_override(client):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = signup(client)
    token = bearer(s["accessToken"])

    # Con token el userId puede omitirse: se toma del token (y se asigna a todos los eventos del lote).
    fav = favorite_event("x", "nitro-coffee", now); del fav["userId"]
    r = client.post("/api/v1/telemetry/page-loads", json={"events": [fav, event(800)]}, headers=token)
    assert r.json() == {"accepted": 2, "duplicates": 0}
    same = favorite_event(s["userId"], "green-bowl-co", now)
    assert client.post("/api/v1/telemetry/page-loads", json={"events": [same]}, headers=token).status_code == 202
    other = favorite_event("otro", "green-bowl-co", now)
    assert client.post("/api/v1/telemetry/page-loads", json={"events": [other]}, headers=token).status_code == 403

    # Sin token: override de desarrollo, pero no a nombre de una cuenta registrada.
    assert client.post("/api/v1/telemetry/page-loads",
                       json={"events": [favorite_event("dev-camilo", "nitro-coffee", now)]}).status_code == 202
    spoof = favorite_event(s["userId"], "conda-de-bons", now)
    assert client.post("/api/v1/telemetry/page-loads", json={"events": [spoof]}).status_code == 401

    # BQ7 cuenta al usuario autenticado y al de desarrollo: mismas formas de respuesta que antes.
    r = client.get("/api/v1/analytics/monthly-active-favoriters", params={"months": 1}).json()
    assert (r["byMonth"][0]["activeFavoriters"], r["byMonth"][0]["favoriteEvents"]) == (2, 3)
    assert client.get("/api/v1/analytics/failed-requests").json()["totalRequests"] == 1

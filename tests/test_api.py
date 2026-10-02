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

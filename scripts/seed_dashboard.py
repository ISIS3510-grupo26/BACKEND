"""Llena con datos SINTETICOS todas las tarjetas del dashboard (/dashboard), para la demo.

Uso:  python scripts/seed_dashboard.py [--url http://127.0.0.1:8000]

Todo entra por la API, como lo mandaria la app, con platform="simulator":
- BQ1, BQ2, BQ3 y BQ12: cargas y busquedas de restaurantes (las de simulate_telemetry.py).
- BQ4 y BQ6: tiempos de espera reportados en la ultima hora.
- BQ7: favorite_added de 12 meses (usuarios de desarrollo sim-user-NN, sin cuenta).
- BQ8: visitas a restaurantes de 6 meses; en una parte el estudiante usa las reseñas (eventos review_interaction
  "rvi-<visita>-<accion>") y algunas reseñas reciben votos Helpful.
- BQ10 y BQ13: cuentas sim-reviewer-N@campusbites.dev que ven restaurantes, intentan publicar reseñas
  (algunas fallan o la app se cierra) y publican. El servidor fecha las reseñas con la hora actual, asi que
  solo el mes actual tiene calificaciones; los meses anteriores tienen vistas.
- BQ14: cargas del mapa de 3 meses con algunos problemas.
La BQ11 no tiene endpoint todavia, asi que su tarjeta sigue vacia.
Correrlo otra vez agrega mas eventos (las cuentas y reseñas ya creadas se reutilizan).
"""
import argparse
import json
import random
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from simulate_telemetry import BOGOTA, DEVICES, SPOTS, make_event

PASSWORD = "simulador123"
REVIEW_FAILURES = ["network", "network", "server_error", "crash", "crash", "rejected"]
MAP_ISSUES = ["location_fallback", "location_fallback", "invalid_coordinates", "load_failed"]
REVIEW_ACTIONS = ["open_all", "open_all", "sort", "filter", "search", "helpful"]  # abrir "All reviews" es lo mas comun


def call(url: str, method: str = "GET", body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode()
            return resp.status, json.loads(text) if text else {}
    except urllib.error.HTTPError as e:
        return e.code, {}


def in_month(now: datetime, months_ago: int) -> datetime:
    """Un momento al azar (7:00-22:59 en Bogota) del mes local `months_ago` meses atras, nunca despues de `now`."""
    local = now.astimezone(BOGOTA)
    index = local.year * 12 + local.month - 1 - months_ago
    start = local.replace(year=index // 12, month=index % 12 + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    day = random.randint(1, local.day if months_ago == 0 else last_day.day)
    moment = start.replace(day=day, hour=random.randint(7, 22), minute=random.randint(0, 59))
    return min(moment, now - timedelta(minutes=random.randint(1, 30)))


def event(screen: str, occurred: datetime, spot: str | None = None, user: str | None = None,
          success: bool = True, error: str | None = None, duration: int = 0) -> dict:
    model, os_name, os_version, _, _ = random.choice(DEVICES)
    return {
        "eventId": str(uuid.uuid4()), "screen": screen, "spotId": spot, "userId": user,
        "durationMs": duration, "success": success, "httpStatus": None, "errorType": error,
        "deviceModel": model, "osName": os_name, "osVersion": os_version, "platform": "simulator",
        "appVersion": "1.0", "sessionId": str(uuid.uuid4())[:8],
        "occurredAt": occurred.astimezone(timezone.utc).isoformat(),
    }


def send(base: str, events: list[dict], token: str | None = None) -> int:
    accepted = 0
    for i in range(0, len(events), 500):
        status, body = call(f"{base}/api/v1/telemetry/page-loads", "POST", {"events": events[i:i + 500]}, token)
        if status != 202:
            raise SystemExit(f"La telemetria respondio {status}")
        accepted += body["accepted"]
    return accepted


def account(base: str, n: int) -> tuple[str, str]:
    """Crea (o reutiliza) la cuenta sim-reviewer-n y devuelve (userId, token)."""
    creds = {"email": f"sim-reviewer-{n}@campusbites.dev", "password": PASSWORD}
    status, body = call(f"{base}/api/v1/auth/signup", "POST", creds)
    if status == 409:
        status, body = call(f"{base}/api/v1/auth/login", "POST", creds)
    if status not in (200, 201):
        raise SystemExit(f"No se pudo crear ni entrar a {creds['email']} ({status})")
    return body["userId"], body["accessToken"]


def seed_page_loads(base: str, now: datetime) -> str:
    return f"BQ1/BQ2/BQ3/BQ12: {send(base, [make_event(now) for _ in range(300)])} cargas y busquedas"


def seed_wait_times(base: str, now: datetime) -> str:
    created = 0
    for spot in SPOTS:
        for _ in range(random.randint(1, 3)):
            reported = now - timedelta(minutes=random.randint(1, 60))
            status, _ = call(f"{base}/api/v1/spots/{spot}/wait-times", "POST", {
                "reportId": str(uuid.uuid4()), "minutes": random.randint(2, 30), "platform": "simulator",
                "reportedAt": reported.isoformat(),
            })
            created += status == 201
    return f"BQ4/BQ6: {created} tiempos de espera"


def seed_favorites(base: str, now: datetime) -> str:
    events = []
    for months_ago in range(12):
        active = max(2, 14 - months_ago + random.randint(-2, 2))  # crece hacia el mes actual
        for u in random.sample(range(1, 31), active):
            for spot in random.sample(SPOTS, random.randint(1, 3)):
                events.append(event("favorite_added", in_month(now, months_ago), spot, f"sim-user-{u:02d}"))
    return f"BQ7: {send(base, events)} favoritos"


def seed_reviews(base: str, now: datetime, reviewers: int = 10) -> str:
    published = attempts = views = 0
    for n in range(1, reviewers + 1):
        user_id, token = account(base, n)
        seen = random.sample(SPOTS, 3)
        page_views = [event("restaurant_detail", in_month(now, m), random.choice(SPOTS), user_id,
                            duration=random.randint(400, 2500))
                      for m in range(1, 6) if random.random() < 0.7]
        page_views += [event("restaurant_detail", now - timedelta(minutes=random.randint(30, 600)), spot, user_id,
                             duration=random.randint(400, 2500)) for spot in seen]
        views += send(base, page_views, token)
        if n > 7:
            continue  # 7 de cada 10 usuarios que vieron restaurantes este mes califican (BQ10)
        submits = []
        for spot in seen[:random.randint(1, 3)]:
            tried_at = now - timedelta(minutes=random.randint(10, 300))
            if random.random() < 0.4:  # un intento que fallo antes del que funciono
                failure = random.choice(REVIEW_FAILURES)
                submits.append(event("review_submit", tried_at - timedelta(minutes=2), spot, user_id,
                                     success=False, error=failure, duration=random.randint(200, 9000)))
            status, _ = call(f"{base}/api/v1/spots/{spot}/reviews", "POST",
                             {"stars": random.randint(3, 5), "text": "Simulated review"}, token)
            if status in (201, 409):  # 409: ya la habia publicado en una corrida anterior
                published += status == 201
                submits.append(event("review_submit", tried_at, spot, user_id, duration=random.randint(300, 2000)))
        # Crashes cuya reseña nunca se publico: reseñas perdidas (BQ13).
        lost_spot = next(s for s in SPOTS if s not in seen)
        if random.random() < 0.5:
            submits.append(event("review_submit", now - timedelta(minutes=random.randint(10, 300)), lost_spot,
                                 user_id, success=False, error="crash"))
        attempts += send(base, submits, token)
    return f"BQ10/BQ13: {views} vistas, {attempts} intentos de reseña, {published} reseñas nuevas"


def seed_review_interactions(base: str, now: datetime) -> str:
    events = []
    for months_ago in range(6):
        share = 0.2 + 0.04 * (5 - months_ago)  # cada mes un poco mas de visitas usan las reseñas
        for _ in range(random.randint(30, 50)):
            occurred = in_month(now, months_ago)
            visit = event("restaurant_detail", occurred, random.choice(SPOTS), duration=random.randint(400, 2500))
            events.append(visit)
            if random.random() < share:
                for action in set(random.sample(REVIEW_ACTIONS, random.randint(1, 3))):
                    events.append({**event("review_interaction", occurred + timedelta(seconds=20), visit["spotId"]),
                                   "eventId": f"rvi-{visit['eventId']}-{action}"})
    sent = send(base, events)
    votes = 0
    for spot in SPOTS:
        _, page = call(f"{base}/api/v1/spots/{spot}/reviews?pageSize=50")
        for review in page.get("items", []):
            for voter in random.sample(range(1, 31), random.randint(0, 4)):
                status, _ = call(f"{base}/api/v1/spots/{spot}/reviews/{review['id']}/helpful?userId=sim-user-{voter:02d}",
                                 "PUT")
                votes += status == 204
    return f"BQ8: {sent} visitas e interacciones con reseñas, {votes} votos Helpful"


def seed_map(base: str, now: datetime) -> str:
    events = []
    for months_ago in range(3):
        for _ in range(random.randint(25, 45)):
            occurred = in_month(now, months_ago)
            if random.random() < 0.12:
                events.append(event("map_display", occurred, success=False, error=random.choice(MAP_ISSUES)))
            else:
                events.append(event("map_display", occurred, duration=random.randint(300, 1500)))
            if random.random() < 0.05:  # las imagenes del mapa fallaron en esa carga
                events.append(event("map_display", occurred, success=False, error="tiles_failed"))
    return f"BQ14: {send(base, events)} eventos del mapa"


def main():
    parser = argparse.ArgumentParser()
    # 127.0.0.1 y no localhost: en Windows localhost prueba primero IPv6 (::1), donde uvicorn no escucha, y cada
    # peticion espera ~2 s antes de caer a IPv4.
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    base = parser.parse_args().url.rstrip("/")
    now = datetime.now(timezone.utc)
    for seed in (seed_page_loads, seed_wait_times, seed_favorites, seed_reviews, seed_review_interactions, seed_map):
        print(seed(base, now))
    print(f"Listo: abre {base}/dashboard")


if __name__ == "__main__":
    main()

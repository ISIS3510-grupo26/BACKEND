"""Envia eventos SINTETICOS de carga de restaurante al backend, para probar los reportes en una demo.

Uso:  python scripts/simulate_telemetry.py [--url http://localhost:8000] [--n 300]
Los eventos llevan platform="simulator" para poder filtrarlos/excluirlos (?platform=...).
Mezcla vistas de pagina y busquedas repartidas por hora para que BQ3 (vistas + busquedas por hora) tenga un ranking distinto segun la hora.
"""
import argparse
import json
import random
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

DEVICES = [  # (modelo, so, version, latencia media ms, prob. de falla)
    ("Samsung Galaxy A14", "Android", "13", 2600, 0.08),
    ("Google Pixel 7", "Android", "14", 1300, 0.03),
    ("Xiaomi Redmi Note 12", "Android", "13", 2200, 0.06),
    ("Motorola Moto G32", "Android", "12", 3100, 0.10),
    ("iPhone 13", "iOS", "17.5", 1100, 0.02),
    ("iPhone 11", "iOS", "16.7", 1800, 0.04),
]
SPOTS = ["conda-de-bons", "green-bowl-co", "nitro-coffee", "taqueria-la-esquina",
         "la-esquina-burger-lab", "poodle-pizza-slices", "el-vagon-street-food"]
ERRORS = [("TIMEOUT", None), ("NO_CONNECTION", None), ("HTTP_503", 503), ("HTTP_500", 500)]


BOGOTA = timezone(timedelta(hours=-5))

# Pesos de interes por hora local (BQ3): cafe por la manana, almuerzo al mediodia, street food de noche.
# Hace que el ranking "vistas + busquedas por hora" cambie a lo largo del dia, como con estudiantes reales.
POPULARITY_BY_SLOT = {
    "morning": {"nitro-coffee": 6, "green-bowl-co": 2, "conda-de-bons": 1, "la-esquina-burger-lab": 1,
                "taqueria-la-esquina": 1, "poodle-pizza-slices": 1, "el-vagon-street-food": 1},
    "lunch": {"conda-de-bons": 5, "la-esquina-burger-lab": 5, "green-bowl-co": 4, "taqueria-la-esquina": 3,
              "poodle-pizza-slices": 2, "el-vagon-street-food": 2, "nitro-coffee": 1},
    "afternoon": {"nitro-coffee": 4, "poodle-pizza-slices": 3, "green-bowl-co": 2, "conda-de-bons": 2,
                  "la-esquina-burger-lab": 2, "taqueria-la-esquina": 1, "el-vagon-street-food": 1},
    "night": {"el-vagon-street-food": 5, "taqueria-la-esquina": 4, "poodle-pizza-slices": 4, "conda-de-bons": 2,
              "la-esquina-burger-lab": 2, "green-bowl-co": 1, "nitro-coffee": 1},
}
SEARCH_RATE = 0.3  # 3 de cada 10 eventos son busquedas (el usuario eligio el restaurante desde el buscador)


def pick_spot(local_hour: int) -> str:
    slot = "morning" if local_hour < 11 else "lunch" if local_hour < 15 else "afternoon" if local_hour < 18 else "night"
    weights = POPULARITY_BY_SLOT[slot]
    return random.choices(list(weights), weights=list(weights.values()))[0]


def make_event(now: datetime) -> dict:
    model, os_name, os_version, mean, fail_rate = random.choice(DEVICES)
    # Los estudiantes usan la app sobre todo entre 7:00 y 23:00 hora de Bogota.
    occurred = now - timedelta(days=random.randint(0, 6))
    occurred = occurred.astimezone(BOGOTA).replace(hour=random.choice(range(7, 23)), minute=random.randint(0, 59))
    base = {
        "eventId": str(uuid.uuid4()), "spotId": pick_spot(occurred.hour),
        "deviceModel": model, "osName": os_name, "osVersion": os_version, "platform": "simulator",
        "appVersion": "1.0", "sessionId": str(uuid.uuid4())[:8],
        "occurredAt": occurred.astimezone(timezone.utc).isoformat(),
    }
    if random.random() < SEARCH_RATE:
        return {**base, "screen": "search", "durationMs": 0, "success": True, "httpStatus": None, "errorType": None}
    failed = random.random() < fail_rate
    error, status = random.choice(ERRORS) if failed else (None, 200)
    duration = 10_000 if error == "TIMEOUT" else max(80, int(random.lognormvariate(0, 0.45) * mean))
    return {**base, "screen": "restaurant_detail", "durationMs": duration, "success": not failed,
            "httpStatus": status, "errorType": error}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=300)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    events = [make_event(now) for _ in range(args.n)]
    for i in range(0, len(events), 500):
        req = urllib.request.Request(
            f"{args.url}/api/v1/telemetry/page-loads",
            data=json.dumps({"events": events[i:i + 500]}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()

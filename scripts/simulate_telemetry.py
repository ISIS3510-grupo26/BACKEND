"""Envia eventos SINTETICOS de carga de restaurante al backend, para probar los reportes en una demo.

Uso:  python scripts/simulate_telemetry.py [--url http://localhost:8000] [--n 300]
Los eventos llevan platform="simulator" para poder filtrarlos/excluirlos (?platform=...).
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


def make_event(now: datetime) -> dict:
    model, os_name, os_version, mean, fail_rate = random.choice(DEVICES)
    failed = random.random() < fail_rate
    error, status = random.choice(ERRORS) if failed else (None, 200)
    duration = 10_000 if error == "TIMEOUT" else max(80, int(random.lognormvariate(0, 0.45) * mean))
    return {
        "eventId": str(uuid.uuid4()), "screen": "restaurant_detail", "spotId": random.choice(SPOTS),
        "durationMs": duration, "success": not failed, "httpStatus": status, "errorType": error,
        "deviceModel": model, "osName": os_name, "osVersion": os_version, "platform": "simulator",
        "appVersion": "1.0", "sessionId": str(uuid.uuid4())[:8],
        "occurredAt": (now - timedelta(minutes=random.randint(0, 7 * 24 * 60))).isoformat(),
    }


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

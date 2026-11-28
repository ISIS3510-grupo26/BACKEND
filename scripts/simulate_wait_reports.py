"""Genera reportes de tiempo de espera de prueba (BQ4) repartidos en los ultimos dias, para la demo de la BQ8.

Uso:  python scripts/simulate_wait_reports.py [--url http://localhost:8000] [--n 250] [--days 21]

Los reportes se mandan por la misma API que usa la app (POST /spots/{id}/wait-times) con un reportedAt en el
pasado, y quedan con platform=simulator. Cada restaurante tiene su patron: el cafe se llena temprano, las
hamburguesas al mediodia y el street food en la tarde, asi la mejor hora cambia de un restaurante a otro.
"""
import argparse
import json
import random
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

BOGOTA = timezone(timedelta(hours=-5))

# Hora local de mas fila para cada restaurante y la espera tipica en ese pico.
PICOS = {
    "nitro-coffee": (8, 18),
    "green-bowl-co": (12, 22),
    "conda-de-bons": (13, 28),
    "taqueria-la-esquina": (13, 24),
    "la-esquina-burger-lab": (12, 30),
    "poodle-pizza-slices": (14, 20),
    "el-vagon-street-food": (17, 25),
}


def espera(spot: str, hora: int) -> int:
    pico, maximo = PICOS[spot]
    lejania = min(abs(hora - pico), 5)
    base = maximo * (1 - lejania / 6)
    return max(2, round(random.gauss(base, 3)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--n", type=int, default=250)
    parser.add_argument("--days", type=int, default=21)
    args = parser.parse_args()

    ahora = datetime.now(BOGOTA)
    enviados = 0
    for _ in range(args.n):
        spot = random.choice(list(PICOS))
        dia = ahora - timedelta(days=random.randint(1, args.days))
        hora = random.randint(7, 19)  # horario de clases
        momento = dia.replace(hour=hora, minute=random.randint(0, 59), second=0, microsecond=0)
        cuerpo = {
            "reportId": str(uuid.uuid4()),
            "minutes": espera(spot, hora),
            "platform": "simulator",
            "reportedAt": momento.astimezone(timezone.utc).isoformat(),
        }
        pedido = urllib.request.Request(
            f"{args.url}/api/v1/spots/{spot}/wait-times",
            data=json.dumps(cuerpo).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(pedido, timeout=10) as respuesta:
            if respuesta.status == 201:
                enviados += 1
    print(f"{enviados} reportes de espera enviados a {args.url}")


if __name__ == "__main__":
    main()

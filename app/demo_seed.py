"""Reportes de espera de ejemplo para la demo (Best time to go / BQ4).

En Render (plan gratis) el disco se borra cada vez que el servidor se reinicia o se duerme, y con la base vacia
"Best time to go" no tiene nada que mostrar. Si DEMO_WAIT_REPORTS > 0, al arrancar y SOLO si no hay ningun
reporte, se crean esa cantidad de reportes repartidos en los ultimos dias (platform=seed). Los reportes que
mandan los estudiantes desde la app se suman encima y cambian los promedios como siempre.

Cada restaurante tiene su patron (el mismo de scripts/simulate_wait_reports.py): el cafe se llena temprano, las
hamburguesas al mediodia y el street food en la tarde, asi la mejor hora cambia de un restaurante a otro.
"""
import random
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from app.repositories.wait_times_repository import WaitTimesRepository

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


def _espera(rng: random.Random, spot: str, hora: int) -> int:
    pico, maximo = PICOS[spot]
    lejania = min(abs(hora - pico), 5)
    base = maximo * (1 - lejania / 6)
    return max(2, round(rng.gauss(base, 3)))


def seed_demo_wait_reports(conn: sqlite3.Connection, n: int, days: int = 21, now: datetime | None = None) -> int:
    """Crea n reportes de ejemplo si la tabla esta vacia. Devuelve cuantos creo (0 si ya habia reportes)."""
    if n <= 0 or conn.execute("SELECT 1 FROM wait_time_reports LIMIT 1").fetchone():
        return 0
    known = {row["id"] for row in conn.execute("SELECT id FROM spots")}
    spots = [spot for spot in PICOS if spot in known]
    if not spots:
        return 0

    # Semilla fija: despues de cada reinicio salen los mismos patrones, solo corridos a las fechas de ahora.
    rng = random.Random(26)
    ahora = (now or datetime.now(timezone.utc)).astimezone(BOGOTA)
    repo = WaitTimesRepository(conn)
    creados = 0
    for _ in range(n):
        spot = rng.choice(spots)
        # Desde ayer hacia atras: el "Wait times now" (BQ4) sigue mostrando primero lo que reportan los estudiantes hoy.
        dia = ahora - timedelta(days=rng.randint(1, days))
        hora = rng.randint(7, 19)  # horario de clases
        momento = dia.replace(hour=hora, minute=rng.randint(0, 59), second=0, microsecond=0)
        report_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        if repo.add(report_id, spot, _espera(rng, spot, hora), None, "seed", momento):
            creados += 1
    return creados

"""Servicio de favoritos cercanos (BQ5): abiertos ahora y a una caminata corta del usuario."""
import math
from datetime import datetime, timedelta, timezone

from app.repositories.favorites_repository import FavoritesRepository, OpeningSlot
from app.schemas import NearbyFavoriteOut

EARTH_RADIUS_M = 6_371_000
# Velocidad de caminata: 80 m/min = 4,8 km/h, el promedio de un adulto en terreno plano.
# La distancia es en linea recta (Haversine), asi que la caminata real por senderos y escaleras puede ser algo mayor.
WALKING_SPEED_M_PER_MIN = 80.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distancia en metros sobre la superficie terrestre entre dos puntos (grados)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def closing_time(hours: tuple[OpeningSlot, ...], local: datetime) -> str | None:
    """Si alguna franja cubre `local` devuelve su hora de cierre ('HH:MM'); si esta cerrado, None.

    Una franja con closes_at <= opens_at cruza la medianoche: la del viernes 17:00-02:00 sigue abierta
    el sabado a la 01:00.
    """
    day, minute = local.weekday(), local.hour * 60 + local.minute
    for slot in hours:
        opens, closes = _minutes(slot.opens_at), _minutes(slot.closes_at)
        if opens < closes:
            is_open = slot.day_of_week == day and opens <= minute < closes
        else:
            is_open = ((slot.day_of_week == day and minute >= opens)
                       or (slot.day_of_week == (day - 1) % 7 and minute < closes))
        if is_open:
            return slot.closes_at
    return None


class FavoritesService:
    def __init__(self, repo: FavoritesRepository):
        self.repo = repo

    def open_nearby(self, user_id: str, lat: float, lng: float, max_walk_minutes: int, tz_offset_minutes: int,
                    now: datetime | None = None) -> list[NearbyFavoriteOut]:
        """BQ5: favoritos del usuario abiertos ahora y a <= max_walk_minutes caminando, del mas cercano al mas lejano."""
        now = now or datetime.now(timezone.utc)
        local = now.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=tz_offset_minutes)
        results = []
        for spot in self.repo.favorite_locations(user_id):
            closes_at = closing_time(spot.hours, local)
            if closes_at is None:
                continue
            meters = haversine_m(lat, lng, spot.latitude, spot.longitude)
            walk = meters / WALKING_SPEED_M_PER_MIN
            if walk > max_walk_minutes:
                continue
            results.append(NearbyFavoriteOut(id=spot.id, name=spot.name, emoji=spot.emoji,
                                             distance_meters=round(meters), walk_minutes=round(walk, 1),
                                             closes_at=closes_at))
        return sorted(results, key=lambda r: (r.walk_minutes, r.id))

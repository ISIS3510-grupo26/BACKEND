"""Pipeline de la BQ3 (pipes and filters): del catalogo completo a los mejor calificados que estan
cerca del usuario y que todavia no ha probado.

Cada paso es una funcion que recibe una lista y devuelve otra, asi que se pueden leer y probar por separado;
nearby_untried solo los encadena en orden.
"""
from app.repositories.spots_repository import SpotsRepository
from app.schemas import NearbyPickOut
from app.services.favorites_service import WALKING_SPEED_M_PER_MIN, haversine_m


def exclude_tried(spots: list[dict], reviewed_ids: set[str]) -> list[dict]:
    """Filtro: saca los que el usuario ya probo (dejo una resena suya)."""
    return [s for s in spots if s["id"] not in reviewed_ids]


def add_distance(spots: list[dict], lat: float, lng: float) -> list[dict]:
    """Transformacion: agrega distancia en linea recta y minutos de caminata desde (lat, lng)."""
    picks = []
    for spot in spots:
        meters = haversine_m(lat, lng, spot["latitude"], spot["longitude"])
        picks.append({**spot, "distance_meters": round(meters),
                      "walk_minutes": round(meters / WALKING_SPEED_M_PER_MIN, 1)})
    return picks


def within_walk(spots: list[dict], max_walk_minutes: int) -> list[dict]:
    """Filtro: deja los que quedan a <= max_walk_minutes caminando."""
    return [s for s in spots if s["walk_minutes"] <= max_walk_minutes]


def rank(spots: list[dict]) -> list[dict]:
    """Orden: mejor calificados primero y, entre los que empatan, el mas cerca."""
    return sorted(spots, key=lambda s: (-s["rating"], s["walk_minutes"], s["id"]))


class RecommendationsService:
    def __init__(self, repo: SpotsRepository):
        self.repo = repo

    def nearby_untried(self, user_id: str, lat: float, lng: float, max_walk_minutes: int,
                       limit: int) -> list[NearbyPickOut]:
        """BQ3: los restaurantes mejor calificados a <= max_walk_minutes de (lat, lng) que el usuario no ha probado."""
        spots = self.repo.spots_with_location()
        spots = exclude_tried(spots, self.repo.reviewed_spot_ids(user_id))
        spots = add_distance(spots, lat, lng)
        spots = within_walk(spots, max_walk_minutes)
        spots = rank(spots)
        return [NearbyPickOut(**s) for s in spots[:limit]]

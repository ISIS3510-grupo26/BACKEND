"""BQ6 (tipo 2): "Which restaurants have the shortest waiting time and the best match with my taste profile?".

Parte de los tiempos de espera de la BQ4 y del perfil de gusto del estudiante. Igual que la BQ3 esta armado como
pipes and filters: cada paso recibe la lista de restaurantes y devuelve otra, y best_for_you solo los encadena.

El perfil es opcional. La app Kotlin no lo manda: lo guarda en el celular (DataStore), pide esta lista sin perfil y
calcula la compatibilidad ella misma, con la misma formula, para que el perfil funcione sin red y no salga del
telefono. Con perfil, el backend devuelve el ranking ya personalizado (lo usan el dashboard y otros clientes).
"""
import math
from datetime import datetime, timedelta, timezone

from app.repositories.best_for_you_repository import BestForYouRepository
from app.schemas import BestForYouReport, BestForYouSpot

Q_BEST_FOR_YOU = "Which restaurants have the shortest waiting time and the best match with my taste profile?"

# Una espera de 40 min o mas ya no suma puntos: a esa altura al estudiante le da igual si son 40 o 60.
MAX_WAIT_MINUTES = 40
# Puntaje neutro: sin un reporte reciente no sabemos como esta la fila, y un perfil sin preferencias que
# apliquen no dice nada del restaurante. En los dos casos ni gana ni pierde.
NEUTRAL_SCORE = 50
# Peso de la espera en el puntaje final; el resto es la compatibilidad con el perfil.
WAIT_WEIGHT = 0.5

# Las cocinas del perfil (pantalla Taste Profile) no se llaman igual que las del catalogo:
# "Artisan Burgers" tiene que encontrar "Burgers & Fries" y "Specialty Coffee" a "Café & Bakery".
CUISINE_KEYWORDS = {
    "Artisan Burgers": ("burger",),
    "Crepas & Bowls": ("bowl", "crepa", "crepe"),
    "Specialty Coffee": ("coffee", "café", "cafe"),
    "Asian Wok": ("wok", "asian", "ramen", "sushi"),
}
VEGGIE_DIETS = {"Vegetarian", "Vegan"}
BUDGET_FRIENDLY = "Budget-friendly"

# Cuanto vale cada parte del perfil. Solo cuentan las que el estudiante lleno.
CUISINE_POINTS, DIET_POINTS, BUDGET_POINTS = 50, 30, 20


def _round_half_up(value: float) -> int:
    """round() de Python redondea 62.5 a 62 (al par); Kotlin (roundToInt) da 63. Asi los dos lados coinciden."""
    return math.floor(value + 0.5)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _keywords(cuisine: str) -> tuple[str, ...]:
    # Una cocina que no esta en el mapa se busca por su ultima palabra ("Mexican Tacos" -> "taco").
    return CUISINE_KEYWORDS.get(cuisine, (cuisine.split()[-1].lower().rstrip("s"),) if cuisine.strip() else ())


def wait_score(minutes: int | None, is_recent: bool) -> int:
    """0 a 100: 0 min de espera vale 100 y MAX_WAIT_MINUTES o mas vale 0."""
    if minutes is None or not is_recent:
        return NEUTRAL_SCORE
    return max(0, _round_half_up(100 * (1 - minutes / MAX_WAIT_MINUTES)))


def taste_match(spot: dict, budget: str | None, dietary: list[str], cuisines: list[str]) -> int:
    """0 a 100: que tanto encaja el restaurante con las partes del perfil que el estudiante lleno."""
    points = max_points = 0
    if cuisines:
        max_points += CUISINE_POINTS
        text = f"{spot['subtitle'].split(' • ')[0]} {spot['name']}".lower()
        if any(k in text for c in cuisines for k in _keywords(c)):
            points += CUISINE_POINTS
    if VEGGIE_DIETS & set(dietary):
        max_points += DIET_POINTS
        if spot["is_vegetarian"]:
            points += DIET_POINTS
    if budget:
        max_points += BUDGET_POINTS
        # Solo "Budget-friendly" restringe; con "Moderate" o "Treat yourself" cualquier precio sirve.
        if budget != BUDGET_FRIENDLY or spot["is_budget"]:
            points += BUDGET_POINTS
    return _round_half_up(points * 100 / max_points) if max_points else NEUTRAL_SCORE


def add_wait(spots: list[dict], now: datetime, fresh_minutes: int) -> list[dict]:
    """Transformacion: que tan vieja es la ultima espera reportada y cuantos puntos da."""
    result = []
    for spot in spots:
        reported_at = _parse(spot["reported_at"]) if spot["reported_at"] else None
        minutes_ago = max(0, int((now - reported_at).total_seconds() // 60)) if reported_at else None
        is_recent = minutes_ago is not None and minutes_ago <= fresh_minutes
        result.append({**spot, "minutes_ago": minutes_ago, "is_recent": is_recent,
                       "wait_score": wait_score(spot["wait_minutes"], is_recent)})
    return result


def add_taste(spots: list[dict], budget: str | None, dietary: list[str], cuisines: list[str]) -> list[dict]:
    """Transformacion: compatibilidad con el perfil. Sin perfil queda en None y el puntaje es solo la espera."""
    personalized = bool(budget or dietary or cuisines)
    return [{**s, "taste_match": taste_match(s, budget, dietary, cuisines) if personalized else None} for s in spots]


def add_score(spots: list[dict]) -> list[dict]:
    """Transformacion: mezcla espera y gusto en un solo puntaje de 0 a 100."""
    result = []
    for s in spots:
        if s["taste_match"] is None:
            score = float(s["wait_score"])
        else:
            score = round(WAIT_WEIGHT * s["wait_score"] + (1 - WAIT_WEIGHT) * s["taste_match"], 1)
        result.append({**s, "score": score})
    return result


def rank(spots: list[dict]) -> list[dict]:
    """Orden: mayor puntaje primero; si empatan, el de menos espera conocida y despues el mejor calificado."""
    def known_wait(s: dict) -> float:
        return s["wait_minutes"] if s["is_recent"] and s["wait_minutes"] is not None else float("inf")

    ordered = sorted(spots, key=lambda s: (-s["score"], known_wait(s), -s["rating"], s["spot_id"]))
    return [{**s, "rank": i} for i, s in enumerate(ordered, start=1)]


class BestForYouService:
    def __init__(self, repo: BestForYouRepository):
        self.repo = repo

    def best_for_you(self, fresh_minutes: int, budget: str | None = None, dietary: list[str] | None = None,
                     cuisines: list[str] | None = None, limit: int | None = None,
                     now: datetime | None = None) -> BestForYouReport:
        now = now or datetime.now(timezone.utc)
        dietary, cuisines = dietary or [], cuisines or []
        spots = self.repo.candidates(recent_since=now - timedelta(minutes=fresh_minutes))
        spots = add_wait(spots, now, fresh_minutes)
        spots = add_taste(spots, budget, dietary, cuisines)
        spots = add_score(spots)
        spots = rank(spots)
        if limit:
            spots = spots[:limit]
        return BestForYouReport(
            question=Q_BEST_FOR_YOU, fresh_minutes=fresh_minutes, max_wait_minutes=MAX_WAIT_MINUTES,
            personalized=bool(budget or dietary or cuisines),
            spots=[BestForYouSpot(cuisine=s["subtitle"].split(" • ")[0], **s) for s in spots],
        )

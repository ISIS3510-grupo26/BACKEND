#Smart feature: compatibilidad de cada restaurante para cada usuario (el "% match" del feed de Flutter).
from app.repositories.match_repository import MatchCandidate, MatchRepository
from app.repositories.preferences_repository import PreferencesRepository
from app.schemas import SpotMatchOut

# Puntos maximos de cada parte (suman 100).
WEIGHTS = {"cuisine": 30, "flavors": 15, "style": 15, "interests": 15, "students": 25}
AVOID_PENALTY = 10
SHRINKAGE = 1.0

VEGETARIAN_DIETS = {"Vegetarian", "Vegan", "Pescatarian"}
ALLERGY_TAGS = {"Dairy": {"dairy"}, "Eggs": {"eggs"}, "Gluten": {"gluten"}, "Peanuts": {"peanuts"},
                "Tree nuts": {"tree_nuts"}, "Seafood": {"seafood"}}
AVOID_TAGS = {"Meat": {"meat"}, "Dairy": {"dairy"}, "Gluten": {"gluten"}, "Seafood": {"seafood"},
              "Nuts": {"peanuts", "tree_nuts"}}


def taste_tokens(prefs: dict) -> set[str]:
    tokens = {f"flavor:{f}" for f in prefs["flavors"]} | {f"interest:{i}" for i in prefs["interests"]}
    if prefs["main_cuisine"]:
        tokens.add(f"cuisine:{prefs['main_cuisine']}")
    if prefs["meal_style"]:
        tokens.add(f"style:{prefs['meal_style']}")
    tokens.add(f"diet:{prefs['diet']}")
    return tokens


def jaccard(a: set[str], b: set[str]) -> float:
    #Similitud entre 0 (nada en comun) y 1 (iguales), elementos compartidos / elementos en total.
    return len(a & b) / len(a | b) if a | b else 0.0


def dietary_conflict(prefs: dict, spot: MatchCandidate) -> str | None:
    #Restriccion, si la dieta o una alergia no se puede cumplir alli, no se recomienda.
    if prefs["diet"] in VEGETARIAN_DIETS and not spot.is_vegetarian:
        return f"No {prefs['diet'].lower()} options"
    for allergy in prefs["allergies"]:
        if ALLERGY_TAGS.get(allergy, set()) & set(spot.contains):
            return f"Most dishes contain {allergy.lower()}"
    return None


def students_score(user_id: str, spot: MatchCandidate, my_tokens: set[str], everyone: dict[str, dict],
                   ratings: dict[str, dict[str, int]]) -> tuple[float, str]:
    #Filtrado colaborativo: que tan bien calificaron este lugar los estudiantes con gustos parecidos.
    weighted, total_sim = 0.0, 0.0
    for other_id, other_prefs in everyone.items():
        stars = ratings.get(other_id, {}).get(spot.id)
        if other_id == user_id or stars is None:
            continue
        sim = jaccard(my_tokens, taste_tokens(other_prefs))
        if sim > 0:
            weighted += sim * (stars - 1) / 4
            total_sim += sim
    prior = (spot.rating - 1) / 4
    value = (weighted + SHRINKAGE * prior) / (total_sim + SHRINKAGE)
    if total_sim > 0:
        return value, f"Students with your taste rated it {1 + 4 * weighted / total_sim:.1f}/5"
    return value, f"Rated {spot.rating:.1f}/5 by students"


def interest_hits(prefs: dict, spot: MatchCandidate, my_ratings: dict[str, int]) -> list[str]:
    hits = []
    for interest in prefs["interests"]:
        if ((interest == "Something new" and spot.id not in my_ratings)
                or (interest == "Something familiar" and my_ratings.get(spot.id, 0) >= 4)
                or (interest in ("Healthy options", "Comfort food") and interest in spot.meal_styles)
                or (interest == "Good value" and spot.is_budget)):
            hits.append(interest)
    return hits


def compatibility(user_id: str, prefs: dict | None, spot: MatchCandidate, everyone: dict[str, dict],
                  ratings: dict[str, dict[str, int]]) -> tuple[int, list[str]]:
    #Puntaje 0-100 del restaurante para el usuario, con las razones.
    # sin perfil solo se puede usar la opinion general.
    if prefs is None:  
        value, reason = students_score(user_id, spot, set(), {}, ratings)
        return round(100 * value), [reason, "Set up your taste profile for a personal match"]

    reasons, points = [], 0.0
    if prefs["main_cuisine"] in spot.cuisines:
        points += WEIGHTS["cuisine"]
        reasons.append(f"Your favorite cuisine: {prefs['main_cuisine']}")
    if prefs["flavors"]:
        shared = [f for f in prefs["flavors"] if f in spot.flavors]
        points += WEIGHTS["flavors"] * len(shared) / len(prefs["flavors"])
        if shared:
            reasons.append(f"{', '.join(shared)} flavors you like")
    if prefs["meal_style"] in spot.meal_styles:
        points += WEIGHTS["style"]
        reasons.append(prefs["meal_style"])
    my_ratings = ratings.get(user_id, {})
    if prefs["interests"]:
        hits = interest_hits(prefs, spot, my_ratings)
        points += WEIGHTS["interests"] * len(hits) / len(prefs["interests"])
        reasons.extend(hits)
    value, reason = students_score(user_id, spot, taste_tokens(prefs), everyone, ratings)
    points += WEIGHTS["students"] * value
    reasons.append(reason)

    for item in prefs["avoid"]:
        spicy = item == "Very spicy food" and "Spicy" in spot.flavors
        if spicy or AVOID_TAGS.get(item, set()) & set(spot.contains):
            points -= AVOID_PENALTY
            reasons.append(f"Has {item.lower()} (you avoid it)")
    if prefs["diet"] in VEGETARIAN_DIETS and spot.is_vegetarian:
        reasons.append(f"{prefs['diet']} options")
    return max(0, min(100, round(points))), reasons


class MatchService:
    def __init__(self, matches: MatchRepository, preferences: PreferencesRepository):
        self.matches = matches
        self.preferences = preferences

    def _inputs(self, user_id: str):
        everyone = self.preferences.all_preferences()
        return everyone.get(user_id), everyone, self.matches.ratings_by_user(), self.matches.candidates()

    def all_matches(self, user_id: str) -> list[SpotMatchOut]:
        #SF, compatibilidad de todos los restaurantes para el usuario (el "% match" del feed).
        prefs, everyone, ratings, spots = self._inputs(user_id)
        result = []
        for spot in spots:
            score, _ = compatibility(user_id, prefs, spot, everyone, ratings)
            conflict = dietary_conflict(prefs, spot) if prefs else None
            result.append(SpotMatchOut(spot_id=spot.id, compatibility=score, dietary_conflict=conflict))
        return sorted(result, key=lambda m: (-m.compatibility, m.spot_id))
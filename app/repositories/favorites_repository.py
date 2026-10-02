"""Repository de favoritos: que restaurantes guardo cada usuario."""
import sqlite3
from dataclasses import dataclass
from itertools import groupby


@dataclass(frozen=True)
class OpeningSlot:
    day_of_week: int  # 0 = lunes ... 6 = domingo
    opens_at: str     # 'HH:MM' hora local; si closes_at <= opens_at la franja cruza la medianoche
    closes_at: str


@dataclass(frozen=True)
class FavoriteLocation:
    id: str
    name: str
    emoji: str
    latitude: float
    longitude: float
    hours: tuple[OpeningSlot, ...]


class FavoritesRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, user_id: str, spot_id: str) -> bool:
        """Guarda el restaurante (idempotente). Devuelve False si el restaurante no existe."""
        try:
            with self.conn:  # OR IGNORE absorbe el favorito repetido; la llave foranea igual rechaza el spot inexistente
                self.conn.execute("INSERT OR IGNORE INTO favorites (user_id, spot_id) VALUES (?, ?)", (user_id, spot_id))
        except sqlite3.IntegrityError:
            return False
        return True

    def remove(self, user_id: str, spot_id: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM favorites WHERE user_id = ? AND spot_id = ?", (user_id, spot_id))

    def favorite_locations(self, user_id: str) -> list[FavoriteLocation]:
        """BQ5: favoritos del usuario con coordenadas y horario. Los que no tienen coordenadas u horario se omiten
        (sin horario nunca estan abiertos)."""
        rows = self.conn.execute(
            "SELECT s.id, s.name, s.emoji, s.latitude, s.longitude, h.day_of_week, h.opens_at, h.closes_at "
            "FROM favorites f JOIN spots s ON s.id = f.spot_id JOIN spot_opening_hours h ON h.spot_id = s.id "
            "WHERE f.user_id = ? AND s.latitude IS NOT NULL AND s.longitude IS NOT NULL ORDER BY s.id, h.id",
            (user_id,),
        ).fetchall()
        locations = []
        for _, group in groupby(rows, key=lambda r: r["id"]):
            slots = list(group)
            spot = slots[0]
            locations.append(FavoriteLocation(
                id=spot["id"], name=spot["name"], emoji=spot["emoji"],
                latitude=spot["latitude"], longitude=spot["longitude"],
                hours=tuple(OpeningSlot(r["day_of_week"], r["opens_at"], r["closes_at"]) for r in slots),
            ))
        return locations

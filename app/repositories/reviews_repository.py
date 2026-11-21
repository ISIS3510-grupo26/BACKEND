"""Repository de reseñas escritas por usuarios."""
import sqlite3
from datetime import datetime, timezone


class ReviewsRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, spot_id: str, user_id: str, author_name: str, initials: str, stars: int, text: str,
            created_at: datetime) -> None:

        self.conn.execute(
            "INSERT INTO reviews (spot_id, position, author_name, initials, program, stars, text, dined_ago, "
            "helpful_count, user_id, created_at) VALUES (?, 0, ?, ?, 'Student', ?, ?, '', 0, ?, ?)",
            (spot_id, author_name, initials, stars, text, user_id,
             created_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")),
        )

    # ---------- Todas las reseñas de un restaurante (paginadas) ----------

    # Lista blanca de ordenes. "newest": primero las de usuarios (las mas nuevas arriba), despues las del catalogo
    # en su orden; cada orden desempata con "newest" para que una pagina nunca cambie entre dos peticiones.
    _NEWEST = "created_at IS NULL, created_at DESC, position, id"
    SORTS = {
        "newest": _NEWEST,
        "highest": f"stars DESC, {_NEWEST}",
        "lowest": f"stars ASC, {_NEWEST}",
        "helpful": f"helpful_count DESC, {_NEWEST}",
    }

    def page(self, spot_id: str, sort: str, stars: int | None, q: str | None, page: int,
             page_size: int) -> tuple[list[sqlite3.Row], int]:
        """Una pagina de reseñas y cuantas cumplen el filtro en total. [q] busca en el texto y el autor sin
        distinguir mayusculas (casefold, registrada en db.connect)."""
        clauses, params = ["spot_id = ?"], [spot_id]
        if stars is not None:
            clauses.append("stars = ?")
            params.append(stars)
        if q:
            clauses.append("instr(casefold(text || ' ' || author_name), casefold(?)) > 0")
            params.append(q)
        where = " AND ".join(clauses)
        total = self.conn.execute(f"SELECT COUNT(*) FROM reviews WHERE {where}", params).fetchone()[0]
        rows = self.conn.execute(
            "SELECT id, author_name, initials, program, stars, text, dined_ago, helpful_count, created_at "
            f"FROM reviews WHERE {where} ORDER BY {self.SORTS[sort]} LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        return rows, total

    # ---------- Votos Helpful ----------

    def belongs_to(self, review_id: int, spot_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM reviews WHERE id = ? AND spot_id = ?",
                                 (review_id, spot_id)).fetchone() is not None

    def add_helpful(self, user_id: str, review_id: int) -> bool:
        """Vota la reseña. Devuelve False si ese usuario ya la habia votado (no cambia nada)."""
        cursor = self.conn.execute("INSERT OR IGNORE INTO review_helpful_votes (user_id, review_id) VALUES (?, ?)",
                                   (user_id, review_id))
        if cursor.rowcount == 0:
            return False
        self.conn.execute("UPDATE reviews SET helpful_count = helpful_count + 1 WHERE id = ?", (review_id,))
        return True

    def remove_helpful(self, user_id: str, review_id: int) -> bool:
        """Quita el voto. Devuelve False si no existia (no cambia nada)."""
        cursor = self.conn.execute("DELETE FROM review_helpful_votes WHERE user_id = ? AND review_id = ?",
                                   (user_id, review_id))
        if cursor.rowcount == 0:
            return False
        self.conn.execute("UPDATE reviews SET helpful_count = MAX(helpful_count - 1, 0) WHERE id = ?", (review_id,))
        return True

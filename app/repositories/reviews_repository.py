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

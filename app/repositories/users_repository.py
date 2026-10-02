"""Repository de usuarios: cuentas y credenciales (el hash, nunca la contraseña)."""
import sqlite3
import uuid


class UsersRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, email: str, password_hash: str) -> dict | None:
        """Crea la cuenta. Devuelve None si el email ya esta registrado."""
        user_id = str(uuid.uuid4())
        try:
            with self.conn:
                self.conn.execute("INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)",
                                  (user_id, email, password_hash))
        except sqlite3.IntegrityError:
            return None
        return {"id": user_id, "email": email, "token_version": 0}

    def get_by_email(self, email: str) -> dict | None:
        row = self.conn.execute("SELECT id, email, password_hash FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None

    def get_credentials(self, user_id: str) -> dict | None:
        row = self.conn.execute("SELECT id, email, password_hash, token_version FROM users WHERE id = ?",
                                (user_id,)).fetchone()
        return dict(row) if row else None

    def update_password(self, user_id: str, password_hash: str) -> int:
        with self.conn:
            self.conn.execute("UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
                              (password_hash, user_id))
        return self.token_version(user_id)

    def token_version(self, user_id: str) -> int | None:
        row = self.conn.execute("SELECT token_version FROM users WHERE id = ?", (user_id,)).fetchone()
        return row[0] if row else None
    
    def get_by_id(self, user_id: str) -> dict | None:
        row = self.conn.execute("SELECT id, email FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def stored_jwt_secret(self) -> str:
        return self.conn.execute("SELECT value FROM app_meta WHERE key = 'jwt_secret'").fetchone()[0]

    def exists(self, user_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone() is not None

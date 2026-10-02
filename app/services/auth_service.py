"""Servicio de autenticacion: hash de contrasenas (bcrypt) y tokens de acceso (JWT HS256)."""
from datetime import datetime, timedelta, timezone
from functools import cache, cached_property

import bcrypt
import jwt

from app.config import settings
from app.repositories.users_repository import UsersRepository
from app.schemas import AuthTokenOut

ALGORITHM = "HS256"
# bcrypt solo usa los primeros 72 bytes; contrasenas mas largas se rechazan en el registro.
MAX_PASSWORD_BYTES = 72


class EmailTaken(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class InvalidToken(Exception):
    pass


@cache
def _dummy_hash() -> str:
    """Hash de referencia para que un email inexistente tarde lo mismo que una contrasena incorrecta."""
    return bcrypt.hashpw(b"campusbites-dummy", bcrypt.gensalt()).decode()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode()
    if len(raw) > MAX_PASSWORD_BYTES:
        return False
    return bcrypt.checkpw(raw, password_hash.encode())


class AuthService:
    def __init__(self, repo: UsersRepository):
        self.repo = repo

    @cached_property
    def _secret(self) -> str:
        return settings.jwt_secret or self.repo.stored_jwt_secret()

    def signup(self, email: str, password: str) -> AuthTokenOut:
        user = self.repo.create(email, hash_password(password))
        if user is None:
            raise EmailTaken(email)
        return self.issue_token(user)

    def login(self, email: str, password: str) -> AuthTokenOut:
        user = self.repo.get_by_email(email)
        if user is None:
            verify_password(password, _dummy_hash())
            raise InvalidCredentials()
        if not verify_password(password, user["password_hash"]):
            raise InvalidCredentials()
        return self.issue_token(user)

    def issue_token(self, user: dict, now: datetime | None = None) -> AuthTokenOut:
        now = now or datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=settings.jwt_expire_minutes)
        token = jwt.encode({"sub": user["id"], "iat": now, "exp": expires_at}, self._secret, algorithm=ALGORITHM)
        return AuthTokenOut(user_id=user["id"], email=user["email"], access_token=token,
                            expires_in=settings.jwt_expire_minutes * 60, expires_at=expires_at)

    def user_id_from_token(self, token: str) -> str:
        """User id del token. InvalidToken si esta vencido, mal formado, mal firmado o la cuenta ya no existe."""
        try:
            claims = jwt.decode(token, self._secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as e:
            raise InvalidToken(str(e)) from e
        if not self.repo.exists(claims["sub"]):
            raise InvalidToken("user no longer exists")
        return claims["sub"]

"""Servicio de autenticacion: hash de contraseñas (bcrypt) y tokens de acceso (JWT HS256)."""
from datetime import datetime, timedelta, timezone
from functools import cache, cached_property

import bcrypt
import jwt

from app.config import settings
from app.repositories.users_repository import UsersRepository
from app.schemas import AuthTokenOut

ALGORITHM = "HS256"
# bcrypt solo usa los primeros 72 bytes; contraseñas mas largas se rechazan en el registro.
MAX_PASSWORD_BYTES = 72


class EmailTaken(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class InvalidToken(Exception):
    pass


class WrongCurrentPassword(Exception):
    pass


class SamePassword(Exception):
    pass


@cache
def _dummy_hash() -> str:
    """Hash de referencia para que un email inexistente tarde lo mismo que una contraseña incorrecta."""
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
        claims = {"sub": user["id"], "ver": user.get("token_version", 0), "iat": now, "exp": expires_at}
        token = jwt.encode(claims, self._secret, algorithm=ALGORITHM)
        return AuthTokenOut(user_id=user["id"], email=user["email"], access_token=token,
                            expires_in=settings.jwt_expire_minutes * 60, expires_at=expires_at)

    def user_id_from_token(self, token: str) -> str:
        """User id del token. InvalidToken si esta vencido, mal formado, mal firmado o la cuenta ya no existe."""
        try:
            claims = jwt.decode(token, self._secret, algorithms=[ALGORITHM], options={"require": ["sub", "exp"]})
        except jwt.PyJWTError as e:
            raise InvalidToken(str(e)) from e
        current = self.repo.token_version(claims["sub"])
        if current is None:
            raise InvalidToken("user no longer exists")
        # Los tokens emitidos antes de que existiera "ver" cuentan como version 0.
        if claims.get("ver", 0) != current:
            raise InvalidToken("password was changed")
        return claims["sub"]
    
    def change_password(self, user_id: str, current_password: str, new_password: str) -> AuthTokenOut:
        """Cambia la contrasena de un usuario autenticado y devuelve un token nuevo."""
        user = self.repo.get_credentials(user_id)
        if user is None or not verify_password(current_password, user["password_hash"]):
            raise WrongCurrentPassword()
        if current_password == new_password:
            raise SamePassword()
        user["token_version"] = self.repo.update_password(user_id, hash_password(new_password))
        return self.issue_token(user)

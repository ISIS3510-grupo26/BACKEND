"""Servicio de autenticacion: hash de contraseñas (bcrypt) y tokens de acceso (JWT HS256).

Contraseñas (esquema "v2"):
- Normalizacion NFKC: la misma contraseña puede llegar con bytes distintos segun el teclado. "ñ" puede venir como un
  solo caracter (NFC) o como "n" + tilde combinable (NFD); NFKC deja ambas iguales antes de hashear o comparar.
- Pre-hash: bcrypt solo usa los primeros 72 bytes, y un emoji ocupa 4 a 6. Por eso se hashea con bcrypt el
  base64(sha256(contraseña normalizada)): siempre 44 bytes ASCII, sin bytes NUL, asi bcrypt nunca trunca y el largo
  de la contraseña lo decide solo la regla de 8 a 128 caracteres (app/schemas.py).
- Migracion: los hashes nuevos se guardan como "v2$" + hash bcrypt. Los anteriores (bcrypt directo sobre la
  contraseña) se siguen aceptando y, al primer login correcto, se rehashean con el esquema nuevo sin que el usuario
  haga nada y sin cerrar sus sesiones.
"""
import base64
import hashlib
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import cache, cached_property

import bcrypt
import jwt

from app.config import settings
from app.repositories.users_repository import UsersRepository
from app.schemas import AuthTokenOut

ALGORITHM = "HS256"
# Prefijo de los hashes del esquema actual. Un hash sin prefijo es legacy (bcrypt directo sobre la contraseña).
HASH_PREFIX = "v2$"
# Solo aplica a los hashes legacy: bcrypt rechaza mas de 72 bytes, y antes esas contraseñas no se aceptaban.
LEGACY_MAX_PASSWORD_BYTES = 72


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
    return hash_password("campusbites-dummy")


def normalize_password(password: str) -> str:
    """NFKC: la forma compuesta y la descompuesta de un mismo texto ("ñ" vs "n" + tilde) quedan iguales."""
    return unicodedata.normalize("NFKC", password)


def _prehash(password: str) -> bytes:
    """base64(sha256(contraseña normalizada)): 44 bytes sin NUL, cabe entero en los 72 bytes de bcrypt."""
    digest = hashlib.sha256(normalize_password(password).encode()).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return HASH_PREFIX + bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode()


def is_legacy_hash(password_hash: str) -> bool:
    return not password_hash.startswith(HASH_PREFIX)


def verify_password(password: str, password_hash: str) -> bool:
    if not is_legacy_hash(password_hash):
        return bcrypt.checkpw(_prehash(password), password_hash.removeprefix(HASH_PREFIX).encode())
    # Legacy: se prueba la contraseña tal como llega (igual que antes) y tambien normalizada, por si se registro
    # desde un teclado y ahora se escribe desde otro.
    for candidate in dict.fromkeys([password, normalize_password(password)]):
        raw = candidate.encode()
        if len(raw) <= LEGACY_MAX_PASSWORD_BYTES and bcrypt.checkpw(raw, password_hash.encode()):
            return True
    return False


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
        if is_legacy_hash(user["password_hash"]):
            # Migracion silenciosa al esquema v2. No cambia token_version: las sesiones abiertas siguen validas.
            self.repo.replace_password_hash(user["id"], hash_password(password))
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
        # Se comparan normalizadas: la misma contraseña escrita desde otro teclado sigue siendo la misma.
        if normalize_password(current_password) == normalize_password(new_password):
            raise SamePassword()
        user["token_version"] = self.repo.update_password(user_id, hash_password(new_password))
        return self.issue_token(user)

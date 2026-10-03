"""
Z-TRACS Road Intelligence - Authentication & RBAC Layer
JWT token generation, bcrypt password hashing, and role enforcement.
"""
import hashlib
import hmac as hmac_lib
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Callable

import bcrypt
import jwt
from fastapi import HTTPException, Security, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_ATTEMPTS = 5

security_bearer = HTTPBearer(auto_error=False)
RATE_LIMIT_BUCKETS = defaultdict(list)


def require_env() -> str:
    missing = []
    if not os.getenv("JWT_SECRET"):
        missing.append("JWT_SECRET")
    if not os.getenv("ADMIN_USERNAME"):
        missing.append("ADMIN_USERNAME")
    if not os.getenv("ADMIN_PASSWORD"):
        missing.append("ADMIN_PASSWORD")
    if missing:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing) + ". "
            "Set them in a local .env file before starting the server."
        )
    jwt_secret = os.environ["JWT_SECRET"]
    if len(jwt_secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters long.")
    return jwt_secret


JWT_SECRET = os.getenv("JWT_SECRET", "")
if JWT_SECRET and len(JWT_SECRET) < 32:
    raise RuntimeError("JWT_SECRET must be at least 32 characters long.")


def get_media_signing_key() -> bytes:
    """Return the HMAC key used to sign media URLs.

    Priority:
      1. MEDIA_SIGNING_SECRET env var (min 32 chars)  — A5 fix
      2. Derived from JWT_SECRET via HMAC with a fixed label.
         This means the media key is NEVER the raw JWT secret.
    """
    explicit = os.getenv("MEDIA_SIGNING_SECRET", "")
    if explicit:
        if len(explicit) < 32:
            raise RuntimeError("MEDIA_SIGNING_SECRET must be at least 32 characters long.")
        return explicit.encode("utf-8")
    # Derive a separate key with a fixed context label.
    jwt_secret = os.getenv("JWT_SECRET", "")
    if not jwt_secret:
        raise RuntimeError("JWT_SECRET is not configured.")
    return hmac_lib.new(
        jwt_secret.encode("utf-8"),
        b"ztracs-media-signing-v1",
        hashlib.sha256,
    ).digest()


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is missing. Set it in the environment before starting the server.")
    if len(secret) < 32:
        raise RuntimeError("JWT_SECRET must be at least 32 characters long.")
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=JWT_EXPIRATION_HOURS))
    to_encode.update({"exp": expire, "iat": datetime.utcnow()})
    return jwt.encode(to_encode, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="JWT_SECRET is not configured.")
    try:
        payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again."
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed."
        )


def rate_limit_key(ip: str, endpoint: str) -> str:
    return f"{endpoint}:{ip}"


def check_rate_limit(ip: str, endpoint: str, limit: int = RATE_LIMIT_MAX_ATTEMPTS, window_seconds: int = RATE_LIMIT_WINDOW_SECONDS) -> None:
    now = time.time()
    key = rate_limit_key(ip, endpoint)
    attempts = [ts for ts in RATE_LIMIT_BUCKETS[key] if now - ts < window_seconds]
    attempts.append(now)
    RATE_LIMIT_BUCKETS[key] = attempts
    if len(attempts) > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please wait a minute and try again."
        )


def authenticate_token_with_db(token: str) -> Dict[str, Any]:
    """Validate JWT token and re-verify user existence and current role in DB (B7e)."""
    payload = decode_access_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed."
        )
    try:
        from backend.database import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT username, role FROM users WHERE LOWER(username) = %s",
            (username.lower(),),
        )
        row = cur.fetchone()
        conn.close()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable."
        )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found."
        )
    return {"username": row["username"], "role": str(row["role"]).lower()}


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)) -> Dict[str, Any]:
    """Validate the JWT token and re-read role from the database on every request.

    Re-reading the DB means a demoted or deleted user is refused immediately
    rather than waiting for the 8-hour token expiry (fix for audit finding B7e).
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required."
        )
    return authenticate_token_with_db(credentials.credentials)


def require_role(allowed_roles: List[str]) -> Callable:
    normalized_allowed = [r.lower() for r in allowed_roles]

    def role_checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        user_role = current_user.get("role", "").lower()
        if user_role not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied."
            )
        return current_user

    return role_checker

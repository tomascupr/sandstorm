import logging
import os
import secrets

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

MIN_KEY_LENGTH = 32

# Cached keys, populated at startup via load_api_keys()
_valid_keys: list[str] = []
_auth_enabled: bool = False


def load_api_keys() -> None:
    """Load and validate API keys at startup. Call once during lifespan."""
    global _valid_keys, _auth_enabled

    api_key = os.environ.get("SANDSTORM_API_KEY")
    if not api_key:
        _valid_keys = []
        _auth_enabled = False
        logging.info("SANDSTORM_API_KEY not set — authentication disabled")
        return

    if len(api_key) < MIN_KEY_LENGTH:
        raise ValueError(f"SANDSTORM_API_KEY must be at least {MIN_KEY_LENGTH} characters long.")

    keys = [api_key]
    previous = os.environ.get("SANDSTORM_API_KEY_PREVIOUS")
    if previous and len(previous) >= MIN_KEY_LENGTH:
        keys.append(previous)

    _valid_keys = keys
    _auth_enabled = True
    logging.info("Authentication enabled (key length: %d)", len(api_key))


def is_auth_enabled() -> bool:
    return _auth_enabled


bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> str | None:
    """Dependency for FastAPI routes - validates Bearer token if auth is enabled."""
    if not _auth_enabled:
        return None

    if not credentials:
        logging.warning("Missing authentication from IP: %s", request.client.host)
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    is_valid = any(secrets.compare_digest(credentials.credentials, key) for key in _valid_keys)

    if not is_valid:
        token_prefix = credentials.credentials[:8] if len(credentials.credentials) >= 8 else "***"
        logging.warning(
            "Invalid token attempt from IP: %s (token prefix: %s...)",
            request.client.host,
            token_prefix,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials

"""
X-API-Key authentication dependency.

Security requirements (ASVS L1 / T-1-01, T-1-02):
- secrets.compare_digest() for timing-safe comparison (prevents brute-force enumeration)
- api_key is None check before compare_digest to avoid TypeError on missing header
- Raw api_key value is NEVER logged (T-1-02)
- SecretStr on settings prevents repr/str exposure of the expected key
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.core.config import Settings, get_settings

api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(
    api_key: Annotated[str | None, Security(api_key_scheme)] = None,
    settings: Annotated[Settings, Depends(get_settings)] = None,
) -> str:
    """
    FastAPI Security dependency that validates the X-API-Key header.

    Returns the API key string on success.
    Raises 401 HTTPException on missing or wrong key.

    NOTE: Do not log the raw api_key value anywhere in this function (T-1-02).
    """
    if api_key is None or not secrets.compare_digest(
        api_key, settings.api_key.get_secret_value()
    ):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


# Type alias for use in route signatures
APIKey = Annotated[str, Security(verify_api_key)]

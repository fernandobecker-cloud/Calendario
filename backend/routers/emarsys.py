"""Emarsys utility endpoints."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import APIRouter

from backend.emarsys_client import get_access_token

router = APIRouter(prefix="/api/emarsys", tags=["emarsys"])


@router.get("/token-info")
def token_info() -> dict[str, Any]:
    access_token = get_access_token()

    try:
        payload = jwt.decode(access_token, options={"verify_signature": False})
    except Exception:
        return {"message": "Token is not JWT, cannot decode scopes"}

    return {
        "client_id": payload.get("client_id"),
        "scope": payload.get("scope"),
        "issuer": payload.get("iss"),
        "audience": payload.get("aud"),
        "expires_at": payload.get("exp"),
    }

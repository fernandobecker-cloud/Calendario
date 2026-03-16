"""Emarsys utility endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.emarsys_client import emarsys_health_check, get_access_token_info

router = APIRouter(prefix="/api/emarsys", tags=["emarsys"])


@router.get("/token-info")
def token_info() -> dict[str, Any]:
    token_data = get_access_token_info(force_refresh=True)
    return {
        "client_id": token_data.get("client_id"),
        "scope": token_data.get("scope"),
        "issuer": token_data.get("issuer"),
        "audience": token_data.get("audience"),
        "expires_at": token_data.get("expires_at"),
        "roles": token_data.get("roles"),
        "payload": token_data.get("payload"),
    }


@router.get("/health")
def health() -> dict[str, Any]:
    return emarsys_health_check()

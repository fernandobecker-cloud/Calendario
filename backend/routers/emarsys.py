"""Emarsys utility endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from backend.emarsys_client import (
    emarsys_health_check,
    emarsys_route_check,
    get_access_token_info,
    get_delivery_results,
)

router = APIRouter(prefix="/api/emarsys", tags=["emarsys"])


@router.get("/token-info")
def token_info() -> dict[str, Any]:
    try:
        token_data = get_access_token_info(force_refresh=True)
    except RuntimeError as exc:
        return {
            "token_generated": False,
            "error": str(exc),
        }
    return {
        "token_generated": True,
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


@router.get("/route-check")
def route_check() -> dict[str, Any]:
    try:
        return emarsys_route_check()
    except RuntimeError as exc:
        return {
            "token_generated": False,
            "error": str(exc),
        }


@router.get("/reporting/delivery-results-test")
def delivery_results_test(
    contact_id: int = Query(..., ge=1),
    start_date: str = Query(default="2026-01-01T00:00:00Z"),
    end_date: str = Query(default="2026-01-31T23:59:59Z"),
) -> dict[str, Any]:
    try:
        return get_delivery_results(contact_id, start_date, end_date)
    except RuntimeError as exc:
        return {
            "token_generated": False,
            "error": str(exc),
        }

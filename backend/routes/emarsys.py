"""Emarsys routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.services.emarsys_discovery import scan_emarsys_endpoints

router = APIRouter(prefix="/api/emarsys", tags=["emarsys"])


@router.get("/scan")
def scan_emarsys() -> dict[str, Any]:
    return scan_emarsys_endpoints()

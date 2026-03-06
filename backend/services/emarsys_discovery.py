"""Endpoint scanner for Emarsys APIs."""

from __future__ import annotations

from typing import Any

import requests

from backend.services.emarsys_auth import generate_wsse_header

EMARSYS_BASE_URL = "https://api.emarsys.net"
MAX_REQUESTS = 20
DISCOVERY_ENDPOINTS = [
    "/api/v2/email",
    "/api/v2/email/statistics",
    "/api/v2/contact",
    "/api/v2/contact/getdata",
    "/api/v2/contact/list",
    "/api/v2/segment",
    "/api/v2/segment/list",
    "/api/v2/program",
    "/api/v2/program/list",
    "/api/v2/campaign",
    "/api/v2/event",
    "/api/v2/event/trigger",
    "/api/v2/field",
    "/api/v2/form",
    "/api/v2/list",
    "/api/v2/tag",
    "/api/v2/template",
    "/api/v2/settings",
]


def _excerpt(text: str, limit: int = 200) -> str:
    return (text or "").strip().replace("\n", " ").replace("\r", " ")[:limit]


def scan_emarsys_endpoints() -> dict[str, Any]:
    targets = DISCOVERY_ENDPOINTS[:MAX_REQUESTS]
    available: list[str] = []
    forbidden: list[str] = []
    auth_error: list[str] = []
    not_found: list[str] = []
    results: list[dict[str, Any]] = []

    for endpoint in targets:
        url = f"{EMARSYS_BASE_URL}{endpoint}"
        wsse_header = generate_wsse_header()
        headers = {
            "X-WSSE": wsse_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = requests.get(url, headers=headers, timeout=20)
            response_excerpt = _excerpt(response.text)
            status_code = response.status_code
        except requests.RequestException as exc:
            status_code = 0
            response_excerpt = _excerpt(str(exc))

        if status_code == 200:
            available.append(endpoint)
        elif status_code == 403:
            forbidden.append(endpoint)
        elif status_code == 401:
            auth_error.append(endpoint)
        elif status_code == 404:
            not_found.append(endpoint)

        results.append(
            {
                "endpoint": endpoint,
                "status_code": status_code,
                "response_excerpt": response_excerpt,
            }
        )

    return {
        "available": available,
        "forbidden": forbidden,
        "auth_error": auth_error,
        "not_found": not_found,
        "results": results,
    }

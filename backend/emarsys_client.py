"""Cliente OAuth2 para API da Emarsys."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import requests

EMARSYS_CLIENT_ID = os.getenv("CLIENT_ID", "").strip() or os.getenv("EMARSYS_CLIENT_ID", "").strip()
EMARSYS_CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip() or os.getenv("EMARSYS_CLIENT_SECRET", "").strip()
EMARSYS_TOKEN_URL = os.getenv("TOKEN_ENDPOINT", "").strip() or os.getenv("EMARSYS_TOKEN_URL", "").strip()
EMARSYS_ACCOUNT_ID = os.getenv("EMARSYS_ACCOUNT_ID", "").strip()
EMARSYS_CAMPAIGNS_ENDPOINT = os.getenv("EMARSYS_CAMPAIGNS_URL", "").strip() or "https://api.emarsys.net/api/v3/campaigns"
EMARSYS_TIMEOUT_SECONDS = 20
EMARSYS_DISCOVERY_ENDPOINTS = [
    "/contacts",
    "/segments",
    "/events",
    "/accounts",
    "/fields",
    "/programs",
    "/email/messages",
    "/email/campaigns",
    "/analytics/campaigns",
    "/interactions/events",
    "/contacts/search",
]
logger = logging.getLogger(__name__)


def _extract_error_detail(response: requests.Response) -> str:
    try:
        body: Any = response.json()
        return str(body)
    except ValueError:
        return response.text.strip() or "sem detalhe"


def _limit_records(data: Any) -> Any:
    if isinstance(data, list):
        return data[:20]
    if isinstance(data, dict):
        limited = dict(data)
        for key, value in data.items():
            if isinstance(value, list):
                limited[key] = value[:20]
        return limited
    return data


def _excerpt(text: str, limit: int = 200) -> str:
    return (text or "").strip().replace("\n", " ").replace("\r", " ")[:limit]


def _build_v3_url(path: str) -> str:
    account_id = EMARSYS_ACCOUNT_ID.strip()
    if not account_id:
        raise RuntimeError("Variavel EMARSYS_ACCOUNT_ID nao configurada")
    safe_path = path if path.startswith("/") else f"/{path}"
    return f"https://api.emarsys.net/api/v3/{account_id}{safe_path}"


def _normalize_campaigns_url() -> str:
    configured = EMARSYS_CAMPAIGNS_ENDPOINT.strip()
    if not configured:
        return _build_v3_url("/campaigns")

    # Mantem endpoint custom quando nao e URL da Core API v3.
    if "/api/v3/" not in configured:
        return configured

    parsed = urlparse(configured)
    path = parsed.path
    marker = "/api/v3/"
    idx = path.find(marker)
    if idx == -1:
        return configured

    tail = path[idx + len(marker):].strip("/")
    if tail:
        first = tail.split("/", 1)[0]
        if first.isdigit():
            return configured

    # Injeta account_id automaticamente quando o endpoint vier sem tenant no path.
    if not EMARSYS_ACCOUNT_ID.strip():
        raise RuntimeError("Variavel EMARSYS_ACCOUNT_ID nao configurada")

    rebuilt_path = f"{path[: idx + len(marker)]}{EMARSYS_ACCOUNT_ID.strip()}/{tail}" if tail else f"{path[: idx + len(marker)]}{EMARSYS_ACCOUNT_ID.strip()}"
    return parsed._replace(path=rebuilt_path).geturl()


def get_access_token() -> str:
    """Solicita access token OAuth2 (client_credentials) da Emarsys."""
    if not EMARSYS_CLIENT_ID:
        raise RuntimeError("Variavel EMARSYS_CLIENT_ID nao configurada")
    if not EMARSYS_CLIENT_SECRET:
        raise RuntimeError("Variavel EMARSYS_CLIENT_SECRET nao configurada")
    if not EMARSYS_TOKEN_URL:
        raise RuntimeError("Variavel EMARSYS_TOKEN_URL nao configurada")

    payload = {"grant_type": "client_credentials"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        response = requests.post(
            EMARSYS_TOKEN_URL,
            data=payload,
            headers=headers,
            auth=(EMARSYS_CLIENT_ID, EMARSYS_CLIENT_SECRET),
            timeout=EMARSYS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        logger.exception("Falha de rede ao solicitar token Emarsys")
        raise RuntimeError(f"Falha de rede ao solicitar token Emarsys: {exc}") from exc

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        logger.error("Erro Emarsys ao gerar token (HTTP %s): %s", response.status_code, detail)
        raise RuntimeError(
            f"Erro Emarsys ao gerar token (HTTP {response.status_code}): {detail}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        logger.error("Resposta invalida da Emarsys ao gerar token: corpo nao e JSON")
        raise RuntimeError("Resposta invalida da Emarsys: corpo nao e JSON") from exc

    access_token = str(body.get("access_token", "")).strip()
    if not access_token:
        logger.error("Resposta da Emarsys nao contem access_token")
        raise RuntimeError("Resposta da Emarsys nao contem access_token")

    return access_token


def get_campaigns() -> Any:
    """Busca campanhas na API da Emarsys usando OAuth2 Bearer token."""
    token = get_access_token()
    endpoint_url = _normalize_campaigns_url()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            endpoint_url,
            headers=headers,
            timeout=EMARSYS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de rede ao buscar campanhas Emarsys: {exc}") from exc

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise RuntimeError(
            f"Erro Emarsys ao buscar campanhas (HTTP {response.status_code}): {detail}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Resposta invalida da Emarsys: corpo nao e JSON") from exc


def discover_emarsys() -> dict[str, Any]:
    """Executa chamadas de descoberta em endpoints Core API v3."""
    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    available: list[str] = []
    forbidden: list[str] = []
    not_found: list[str] = []
    results: list[dict[str, Any]] = []
    for path in EMARSYS_DISCOVERY_ENDPOINTS:
        endpoint = f"/api/v3/{EMARSYS_ACCOUNT_ID.strip()}{path}" if EMARSYS_ACCOUNT_ID.strip() else f"/api/v3{path}"
        try:
            url = _build_v3_url(path)
        except RuntimeError as exc:
            results.append(
                {
                    "endpoint": endpoint,
                    "status": "error",
                    "message": str(exc),
                }
            )
            continue
        try:
            response = requests.get(url, headers=headers, timeout=EMARSYS_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            results.append(
                {
                    "endpoint": endpoint,
                    "status": "error",
                    "message": f"Falha de rede ao consultar endpoint: {exc}",
                }
            )
            continue

        status_code = response.status_code
        if status_code == 200:
            available.append(endpoint)
        elif status_code == 403:
            forbidden.append(endpoint)
        elif status_code == 404:
            not_found.append(endpoint)

        results.append(
            {
                "endpoint": endpoint,
                "status_code": status_code,
                "response_excerpt": _excerpt(response.text),
            }
        )

    return {
        "available": available,
        "forbidden": forbidden,
        "not_found": not_found,
        "results": results,
    }

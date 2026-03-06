"""Cliente OAuth2 para API da Emarsys."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

EMARSYS_CLIENT_ID = os.getenv("CLIENT_ID", "").strip() or os.getenv("EMARSYS_CLIENT_ID", "").strip()
EMARSYS_CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip() or os.getenv("EMARSYS_CLIENT_SECRET", "").strip()
EMARSYS_TOKEN_URL = os.getenv("TOKEN_ENDPOINT", "").strip() or os.getenv("EMARSYS_TOKEN_URL", "").strip()
EMARSYS_CAMPAIGNS_URL = os.getenv("EMARSYS_CAMPAIGNS_URL", "").strip()
EMARSYS_TIMEOUT_SECONDS = 20
EMARSYS_DISCOVERY_ENDPOINTS = [
    "https://api.emarsys.net/api/v3/accounts",
    "https://api.emarsys.net/api/v3/programs",
    "https://api.emarsys.net/api/v3/segments",
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
    return data


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
    """Busca campanhas na API da Emarsys usando Bearer token."""
    if not EMARSYS_CAMPAIGNS_URL:
        raise RuntimeError("Variavel EMARSYS_CAMPAIGNS_URL nao configurada")

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        response = requests.get(
            EMARSYS_CAMPAIGNS_URL,
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

    results: list[dict[str, Any]] = []
    for url in EMARSYS_DISCOVERY_ENDPOINTS:
        endpoint = url.replace("https://api.emarsys.net", "")
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

        if response.status_code >= 400:
            results.append(
                {
                    "endpoint": endpoint,
                    "status": "error",
                    "message": _extract_error_detail(response),
                }
            )
            continue

        try:
            body = response.json()
        except ValueError:
            results.append(
                {
                    "endpoint": endpoint,
                    "status": "error",
                    "message": "Resposta invalida da Emarsys: corpo nao e JSON",
                }
            )
            continue

        results.append(
            {
                "endpoint": endpoint,
                "status": response.status_code,
                "data": _limit_records(body),
            }
        )

    return {"results": results}

"""Cliente OAuth2 para API da Emarsys."""

from __future__ import annotations

import os
from typing import Any

import requests

EMARSYS_CLIENT_ID = os.getenv("EMARSYS_CLIENT_ID", "").strip()
EMARSYS_CLIENT_SECRET = os.getenv("EMARSYS_CLIENT_SECRET", "").strip()
EMARSYS_TOKEN_URL = os.getenv("EMARSYS_TOKEN_URL", "").strip()
EMARSYS_CAMPAIGNS_URL = os.getenv("EMARSYS_CAMPAIGNS_URL", "").strip()
EMARSYS_TIMEOUT_SECONDS = 20


def get_access_token() -> str:
    """Solicita access token OAuth2 (client_credentials) da Emarsys."""
    if not EMARSYS_CLIENT_ID:
        raise RuntimeError("Variavel EMARSYS_CLIENT_ID nao configurada")
    if not EMARSYS_CLIENT_SECRET:
        raise RuntimeError("Variavel EMARSYS_CLIENT_SECRET nao configurada")
    if not EMARSYS_TOKEN_URL:
        raise RuntimeError("Variavel EMARSYS_TOKEN_URL nao configurada")

    payload = {"grant_type": "client_credentials"}

    try:
        response = requests.post(
            EMARSYS_TOKEN_URL,
            data=payload,
            auth=(EMARSYS_CLIENT_ID, EMARSYS_CLIENT_SECRET),
            timeout=EMARSYS_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de rede ao solicitar token Emarsys: {exc}") from exc

    if response.status_code >= 400:
        detail: str
        try:
            body: Any = response.json()
            detail = str(body)
        except ValueError:
            detail = response.text.strip() or "sem detalhe"
        raise RuntimeError(
            f"Erro Emarsys ao gerar token (HTTP {response.status_code}): {detail}"
        )

    try:
        body = response.json()
    except ValueError as exc:
        raise RuntimeError("Resposta invalida da Emarsys: corpo nao e JSON") from exc

    access_token = str(body.get("access_token", "")).strip()
    if not access_token:
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
        detail: str
        try:
            body: Any = response.json()
            detail = str(body)
        except ValueError:
            detail = response.text.strip() or "sem detalhe"
        raise RuntimeError(
            f"Erro Emarsys ao buscar campanhas (HTTP {response.status_code}): {detail}"
        )

    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Resposta invalida da Emarsys: corpo nao e JSON") from exc

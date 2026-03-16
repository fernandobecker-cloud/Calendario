"""Cliente OAuth2 para API da Emarsys."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_EMARSYS_TOKEN_URL = "https://auth.emarsys.net/oauth2/token"
DEFAULT_EMARSYS_CAMPAIGNS_ENDPOINT = "https://api.emarsys.net/api/v3/campaigns"
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


def _read_env(name: str, *fallbacks: str, default: str = "") -> str:
    for key in (name, *fallbacks):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return default


def _get_client_id() -> str:
    return _read_env("CLIENT_ID", "EMARSYS_CLIENT_ID")


def _get_client_secret() -> str:
    return _read_env("CLIENT_SECRET", "EMARSYS_CLIENT_SECRET")


def _get_token_url() -> str:
    return _read_env("TOKEN_ENDPOINT", "EMARSYS_TOKEN_URL", default=DEFAULT_EMARSYS_TOKEN_URL)


def _get_account_id() -> str:
    return _read_env("EMARSYS_ACCOUNT_ID")


def _get_campaigns_endpoint() -> str:
    return _read_env("EMARSYS_CAMPAIGNS_URL", default=DEFAULT_EMARSYS_CAMPAIGNS_ENDPOINT)


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
    account_id = _get_account_id()
    if not account_id:
        raise RuntimeError("Variavel EMARSYS_ACCOUNT_ID nao configurada")
    safe_path = path if path.startswith("/") else f"/{path}"
    return f"https://api.emarsys.net/api/v3/{account_id}{safe_path}"


def _normalize_campaigns_url() -> str:
    configured = _get_campaigns_endpoint()
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
    account_id = _get_account_id()
    if not account_id:
        raise RuntimeError("Variavel EMARSYS_ACCOUNT_ID nao configurada")

    rebuilt_path = f"{path[: idx + len(marker)]}{account_id}/{tail}" if tail else f"{path[: idx + len(marker)]}{account_id}"
    return parsed._replace(path=rebuilt_path).geturl()


def _request_access_token(
    token_url: str,
    payload: dict[str, str],
    headers: dict[str, str],
    client_id: str,
    client_secret: str,
    *,
    use_basic_auth: bool,
) -> requests.Response:
    request_kwargs: dict[str, Any] = {
        "data": payload,
        "headers": headers,
        "timeout": EMARSYS_TIMEOUT_SECONDS,
    }
    if use_basic_auth:
        request_kwargs["auth"] = (client_id, client_secret)
    return requests.post(token_url, **request_kwargs)


def _should_retry_with_client_secret_post(response: requests.Response) -> bool:
    if response.status_code < 400:
        return False
    detail = _extract_error_detail(response).lower()
    return "client_secret_post" in detail or "invalid_client" in detail


def get_access_token() -> str:
    """Solicita access token OAuth2 (client_credentials) da Emarsys."""
    client_id = _get_client_id()
    client_secret = _get_client_secret()
    token_url = _get_token_url()

    if not client_id:
        raise RuntimeError("Variavel EMARSYS_CLIENT_ID nao configurada")
    if not client_secret:
        raise RuntimeError("Variavel EMARSYS_CLIENT_SECRET nao configurada")
    if not token_url:
        raise RuntimeError("Variavel EMARSYS_TOKEN_URL nao configurada")

    payload = {"grant_type": "client_credentials"}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    try:
        response = _request_access_token(
            token_url,
            payload,
            headers,
            client_id,
            client_secret,
            use_basic_auth=True,
        )
    except requests.RequestException as exc:
        logger.exception("Falha de rede ao solicitar token Emarsys")
        raise RuntimeError(f"Falha de rede ao solicitar token Emarsys: {exc}") from exc

    if _should_retry_with_client_secret_post(response):
        fallback_payload = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        }
        try:
            response = _request_access_token(
                token_url,
                fallback_payload,
                headers,
                client_id,
                client_secret,
                use_basic_auth=False,
            )
        except requests.RequestException as exc:
            logger.exception("Falha de rede ao solicitar token Emarsys com client_secret_post")
            raise RuntimeError(
                f"Falha de rede ao solicitar token Emarsys com client_secret_post: {exc}"
            ) from exc

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
    account_id = _get_account_id()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    available: list[str] = []
    forbidden: list[str] = []
    not_found: list[str] = []
    results: list[dict[str, Any]] = []
    for path in EMARSYS_DISCOVERY_ENDPOINTS:
        endpoint = f"/api/v3/{account_id}{path}" if account_id else f"/api/v3{path}"
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
        "token_url": _get_token_url(),
        "account_id": account_id or None,
        "available": available,
        "forbidden": forbidden,
        "not_found": not_found,
        "results": results,
    }

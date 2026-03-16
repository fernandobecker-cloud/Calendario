"""Cliente OAuth2 para API da Emarsys."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import requests

DEFAULT_EMARSYS_TOKEN_URL = "https://auth.emarsys.net/oauth2/token"
DEFAULT_EMARSYS_CAMPAIGNS_ENDPOINT = "https://api.emarsys.net/api/v3/campaigns"
DEFAULT_EMARSYS_V2_BASE_URL = "https://api.emarsys.net/api/v2"
EMARSYS_TIMEOUT_SECONDS = 20
EMARSYS_MAX_RETRIES = 3
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
_TOKEN_CACHE: dict[str, Any] = {
    "access_token": "",
    "expires_at": 0,
    "scope": "",
    "payload": {},
}


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


def _get_v2_base_url() -> str:
    return _read_env("EMARSYS_V2_BASE_URL", default=DEFAULT_EMARSYS_V2_BASE_URL)


def _get_oauth_scope() -> str:
    return _read_env("EMARSYS_OAUTH_SCOPE", default="openid campaign analytics email")


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


def _decode_jwt_payload(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        return json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _request_with_retries(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> requests.Response:
    last_error: requests.RequestException | None = None
    for attempt in range(EMARSYS_MAX_RETRIES):
        started_at = time.perf_counter()
        try:
            response = requests.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=EMARSYS_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_error = exc
            logger.warning("Emarsys %s %s falhou na tentativa %s: %s", method, url, attempt + 1, exc)
            if attempt < EMARSYS_MAX_RETRIES - 1:
                time.sleep(2 ** attempt)
                continue
            raise

        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        logger.info("Emarsys %s %s -> HTTP %s em %sms", method, url, response.status_code, elapsed_ms)
        if response.status_code >= 500 and attempt < EMARSYS_MAX_RETRIES - 1:
            time.sleep(2 ** attempt)
            continue
        return response

    if last_error is not None:
        raise last_error
    raise RuntimeError("Falha inesperada ao executar requisicao Emarsys")


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
    if use_basic_auth:
        return requests.post(
            token_url,
            data=payload,
            headers=headers,
            auth=(client_id, client_secret),
            timeout=EMARSYS_TIMEOUT_SECONDS,
        )
    return _request_with_retries("POST", token_url, headers=headers, data=payload)


def _should_retry_with_client_secret_post(response: requests.Response) -> bool:
    if response.status_code < 400:
        return False
    detail = _extract_error_detail(response).lower()
    return "client_secret_post" in detail or "invalid_client" in detail


def get_access_token(*, force_refresh: bool = False) -> str:
    """Solicita access token OAuth2 (client_credentials) da Emarsys."""
    client_id = _get_client_id()
    client_secret = _get_client_secret()
    token_url = _get_token_url()
    requested_scope = _get_oauth_scope()

    if not client_id:
        raise RuntimeError("Variavel EMARSYS_CLIENT_ID nao configurada")
    if not client_secret:
        raise RuntimeError("Variavel EMARSYS_CLIENT_SECRET nao configurada")
    if not token_url:
        raise RuntimeError("Variavel EMARSYS_TOKEN_URL nao configurada")

    cached_token = str(_TOKEN_CACHE.get("access_token", "")).strip()
    cached_exp = int(_TOKEN_CACHE.get("expires_at", 0) or 0)
    if not force_refresh and cached_token and cached_exp > int(time.time()) + 60:
        return cached_token

    payload = {
        "grant_type": "client_credentials",
        "scope": requested_scope,
    }
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
            "scope": requested_scope,
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

    payload_data = _decode_jwt_payload(access_token)
    expires_at = int(payload_data.get("exp") or 0)
    token_scope = str(payload_data.get("scope") or body.get("scope") or requested_scope)
    _TOKEN_CACHE.update(
        {
            "access_token": access_token,
            "expires_at": expires_at,
            "scope": token_scope,
            "payload": payload_data,
        }
    )
    logger.info("Token Emarsys gerado com scope=%s exp=%s", token_scope, expires_at or "desconhecido")
    return access_token


def get_access_token_info(*, force_refresh: bool = False) -> dict[str, Any]:
    access_token = get_access_token(force_refresh=force_refresh)
    payload = dict(_TOKEN_CACHE.get("payload") or _decode_jwt_payload(access_token))
    return {
        "access_token": access_token,
        "scope": payload.get("scope") or _TOKEN_CACHE.get("scope") or _get_oauth_scope(),
        "expires_at": payload.get("exp"),
        "issuer": payload.get("iss"),
        "audience": payload.get("aud"),
        "client_id": payload.get("client_id") or payload.get("cid"),
        "roles": payload.get("roles") or payload.get("authorities") or payload.get("permissions"),
        "payload": payload,
    }


def _build_recommendation(token_generated: bool, token_scope: str, v2_status: int, v3_status: int) -> str:
    if not token_generated:
        return "Falha ao gerar token. Revise client_id, client_secret e o scope solicitado."
    if v2_status == 200 or v3_status == 200:
        return "Autenticacao e permissao confirmadas para pelo menos um endpoint."
    if v2_status == 400 or v3_status == 400:
        return "A requisicao foi rejeitada por formato ou scope invalido. Revise EMARSYS_OAUTH_SCOPE."
    if v2_status == 401 or v3_status == 401:
        return "O token foi rejeitado. Verifique expiracao, audience e metodo de autenticacao do client."
    if v2_status == 403 and v3_status == 403:
        if not token_scope:
            return "Token gerado sem scope visivel e endpoints negados. Revise os scopes do OAuth client e as permissoes no tenant."
        return "Token gerado, mas sem permissao nos endpoints testados. Libere os scopes/permissoes correspondentes no painel da Emarsys."
    return "Revise account_id, produto habilitado no tenant e permissoes do OAuth client."


def emarsys_health_check() -> dict[str, Any]:
    token_generated = False
    token_scope = ""
    token_error = ""
    v2_status = 0
    v3_status = 0
    v2_error = ""
    v3_error = ""

    try:
        token_info = get_access_token_info(force_refresh=True)
        token_generated = True
        token_scope = str(token_info.get("scope") or "")
        token = str(token_info["access_token"])
    except RuntimeError as exc:
        token = ""
        token_error = str(exc)
        token_info = {
            "scope": "",
            "expires_at": None,
            "issuer": None,
            "audience": None,
            "client_id": None,
            "roles": None,
        }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    v2_url = f"{_get_v2_base_url().rstrip('/')}/contact/"
    v3_url = _build_v3_url("/email/campaigns")

    if token:
        try:
            v2_response = _request_with_retries("GET", v2_url, headers=headers)
            v2_status = v2_response.status_code
            if v2_status >= 400:
                v2_error = _excerpt(_extract_error_detail(v2_response))
        except requests.RequestException as exc:
            v2_error = str(exc)

        try:
            v3_response = _request_with_retries("GET", v3_url, headers=headers)
            v3_status = v3_response.status_code
            if v3_status >= 400:
                v3_error = _excerpt(_extract_error_detail(v3_response))
        except requests.RequestException as exc:
            v3_error = str(exc)

    return {
        "token_generated": token_generated,
        "token_scope": token_scope,
        "token_expires_at": token_info.get("expires_at"),
        "token_issuer": token_info.get("issuer"),
        "token_audience": token_info.get("audience"),
        "token_client_id": token_info.get("client_id"),
        "token_roles": token_info.get("roles"),
        "token_error": token_error or None,
        "requested_scope": _get_oauth_scope(),
        "v2_url": v2_url,
        "v2_status": v2_status,
        "v2_error": v2_error or None,
        "v3_url": v3_url,
        "v3_status": v3_status,
        "v3_error": v3_error or None,
        "recommendation": _build_recommendation(token_generated, token_scope, v2_status, v3_status),
    }


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
        response = _request_with_retries("GET", endpoint_url, headers=headers)
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
            response = _request_with_retries("GET", url, headers=headers)
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

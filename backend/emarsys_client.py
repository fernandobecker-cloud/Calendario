"""Cliente OAuth2 para API da Emarsys."""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import requests

DEFAULT_EMARSYS_TOKEN_URL = "https://auth.emarsys.net/oauth2/token"
DEFAULT_EMARSYS_CORE_BASE_URL = "https://api.emarsys.net"
DEFAULT_EMARSYS_CAMPAIGNS_ENDPOINT = "https://api.emarsys.net/api/v3/email"
EMARSYS_TIMEOUT_SECONDS = 20
EMARSYS_MAX_RETRIES = 3
EMARSYS_DISCOVERY_ENDPOINTS = [
    "/v3/email",
    "/v3/email/1",
    "/v3/email/1/responsesummary",
    "/v3/contact",
    "/v3/segment",
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


def _get_core_base_url() -> str:
    return _read_env("EMARSYS_CORE_BASE_URL", default=DEFAULT_EMARSYS_CORE_BASE_URL)


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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


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
    safe_path = path if path.startswith("/") else f"/{path}"
    return f"{_get_core_base_url().rstrip('/')}{safe_path}"


def _normalize_campaigns_url() -> str:
    configured = _get_campaigns_endpoint()
    return configured or _build_v3_url("/api/v3/email")


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


def _build_recommendation(token_generated: bool, token_scope: str, v3_status: int) -> str:
    if not token_generated:
        return "Falha ao gerar token. Revise client_id, client_secret e o scope solicitado."
    if v3_status == 200:
        return "Autenticacao e permissao confirmadas para o endpoint documentado da Core API."
    if v3_status == 400:
        return "A requisicao foi rejeitada por formato ou scope invalido. Revise EMARSYS_OAUTH_SCOPE."
    if v3_status == 401:
        return "O token foi rejeitado. Verifique expiracao, audience e metodo de autenticacao do client."
    if v3_status == 403:
        if not token_scope:
            return "Token gerado sem scope visivel e endpoints negados. Revise os scopes do OAuth client e as permissoes no tenant."
        return "Token gerado, mas sem permissao no endpoint documentado da Core API. Libere o produto e as permissoes correspondentes no tenant."
    if v3_status == 404:
        return "O endpoint documentado nao foi encontrado. Revise a base URL da Core API habilitada para o tenant."
    return "Revise a configuracao da Core API, o produto habilitado no tenant e as permissoes do OAuth client."


def emarsys_health_check() -> dict[str, Any]:
    token_generated = False
    token_scope = ""
    token_error = ""
    v3_status = 0
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

    v3_url = _normalize_campaigns_url()

    if token:
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
        "v3_url": v3_url,
        "v3_status": v3_status,
        "v3_error": v3_error or None,
        "recommendation": _build_recommendation(token_generated, token_scope, v3_status),
    }


def emarsys_route_check() -> dict[str, Any]:
    token_info = get_access_token_info(force_refresh=True)
    token = str(token_info["access_token"])
    account_id = _get_account_id()
    base_url = _get_core_base_url().rstrip("/")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    candidate_paths = [
        "/api/v3/campaigns",
        "/v3/email",
        "/api/v3/email",
        "/api/v3/email/campaigns",
        "/api/v3/analytics/campaigns",
    ]
    if account_id:
        candidate_paths.extend(
            [
                f"/api/v3/{account_id}/email/campaigns",
                f"/api/v3/{account_id}/analytics/campaigns",
                f"/api/v3/{account_id}/interactions/events",
            ]
        )

    results: list[dict[str, Any]] = []
    for path in candidate_paths:
        url = f"{base_url}{path}"
        try:
            response = _request_with_retries("GET", url, headers=headers)
            results.append(
                {
                    "path": path,
                    "url": url,
                    "status_code": response.status_code,
                    "response_excerpt": _excerpt(response.text),
                }
            )
        except requests.RequestException as exc:
            results.append(
                {
                    "path": path,
                    "url": url,
                    "status": "error",
                    "message": str(exc),
                }
            )

    return {
        "token_generated": True,
        "token_scope": token_info.get("scope"),
        "token_issuer": token_info.get("issuer"),
        "token_audience": token_info.get("audience"),
        "token_client_id": token_info.get("client_id"),
        "account_id": account_id or None,
        "base_url": base_url,
        "results": results,
    }


def get_delivery_results(contact_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    token_info = get_access_token_info(force_refresh=True)
    token = str(token_info["access_token"])
    url = (
        f"{_get_core_base_url().rstrip('/')}/api/email/reporting/v2/contacts/{contact_id}/deliveryResults"
        f"?startDate={start_date}&endDate={end_date}"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        response = _request_with_retries("GET", url, headers=headers)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de rede ao buscar delivery results: {exc}") from exc

    response_body: Any
    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    return {
        "token_generated": True,
        "token_scope": token_info.get("scope"),
        "url": url,
        "status_code": response.status_code,
        "body": response_body,
    }


def get_response_summary(campaign_id: int) -> dict[str, Any]:
    token_info = get_access_token_info(force_refresh=True)
    token = str(token_info["access_token"])
    url = f"{_get_core_base_url().rstrip('/')}/api/v3/email/{campaign_id}/responsesummary"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        response = _request_with_retries("GET", url, headers=headers)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha de rede ao buscar response summary: {exc}") from exc

    response_body: Any
    try:
        response_body = response.json()
    except ValueError:
        response_body = response.text

    return {
        "token_generated": True,
        "token_scope": token_info.get("scope"),
        "url": url,
        "status_code": response.status_code,
        "body": response_body,
    }


def get_delivery_results_portal(contact_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    result = get_delivery_results(contact_id, start_date, end_date)
    body = result.get("body")
    rows = body.get("data", []) if isinstance(body, dict) else []
    normalized = [
        {
            "contact_id": contact_id,
            "campaign_id": str(item.get("campaignId", "")),
            "delivery_status": item.get("deliveryStatus"),
            "launch_date": item.get("launchDate"),
            "launch_list_id": str(item.get("launchListId", "")),
        }
        for item in rows
        if isinstance(item, dict)
    ]
    return {
        "contact_id": contact_id,
        "start_date": start_date,
        "end_date": end_date,
        "status_code": result.get("status_code"),
        "total": len(normalized),
        "results": normalized,
    }


def get_campaigns_portal() -> dict[str, Any]:
    raw = get_campaigns()
    rows = raw.get("data", []) if isinstance(raw, dict) else []
    campaigns: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        sent = _to_int(item.get("sent"))
        delivered = _to_int(item.get("delivered"))
        opens = _to_int(item.get("opens"))
        unique_opens = _to_int(item.get("unique_opens"))
        clicks = _to_int(item.get("clicks"))
        unique_clicks = _to_int(item.get("unique_clicks"))
        unsubscribes = _to_int(item.get("unsubscribes"))
        bounces = _to_int(item.get("bounces"))
        revenue = _to_float(item.get("revenue"))
        campaigns.append(
            {
                "campaign_id": str(item.get("id", "")),
                "campaign_name": str(item.get("name", "")).strip(),
                "sent_date": item.get("created"),
                "language": item.get("language"),
                "subject": item.get("subject"),
                "from_email": item.get("fromemail"),
                "from_name": item.get("fromname"),
                "status": item.get("status"),
                "source": item.get("source"),
                "metrics": {
                    "sent": sent,
                    "delivered": delivered,
                    "opens": opens,
                    "unique_opens": unique_opens,
                    "clicks": clicks,
                    "unique_clicks": unique_clicks,
                    "unsubscribes": unsubscribes,
                    "bounces": bounces,
                    "revenue": revenue,
                },
                "rates": {
                    "open_rate": (unique_opens / delivered) if delivered else 0.0,
                    "click_rate": (unique_clicks / delivered) if delivered else 0.0,
                    "ctr": (unique_clicks / unique_opens) if unique_opens else 0.0,
                    "unsubscribe_rate": (unsubscribes / delivered) if delivered else 0.0,
                    "bounce_rate": (bounces / sent) if sent else 0.0,
                },
                "raw": {
                    "email_category": item.get("email_category"),
                    "api_status": item.get("api_status"),
                    "api_error": item.get("api_error"),
                    "event_id": item.get("event_id"),
                    "is_delayed": item.get("is_delayed"),
                    "is_rti": item.get("is_rti"),
                    "tags": item.get("tags", []),
                    "features": item.get("features", []),
                },
            }
        )

    return {
        "total": len(campaigns),
        "reply_code": raw.get("replyCode") if isinstance(raw, dict) else None,
        "reply_text": raw.get("replyText") if isinstance(raw, dict) else None,
        "campaigns": campaigns,
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
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    available: list[str] = []
    forbidden: list[str] = []
    not_found: list[str] = []
    results: list[dict[str, Any]] = []
    for path in EMARSYS_DISCOVERY_ENDPOINTS:
        endpoint = path
        url = _build_v3_url(path)
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
        "account_id": _get_account_id() or None,
        "core_base_url": _get_core_base_url(),
        "available": available,
        "forbidden": forbidden,
        "not_found": not_found,
        "results": results,
    }

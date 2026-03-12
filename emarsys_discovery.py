#!/usr/bin/env python3
"""Emarsys API discovery script using OAuth2 client credentials."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from typing import Any

import requests

CLIENT_ID = os.getenv("CLIENT_ID", "").strip() or os.getenv("EMARSYS_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "").strip() or os.getenv("EMARSYS_CLIENT_SECRET", "").strip()
TOKEN_URL = os.getenv("TOKEN_ENDPOINT", "").strip() or os.getenv("EMARSYS_TOKEN_URL", "").strip() or "https://auth.emarsys.net/oauth2/token"
JWKS_URL = os.getenv("JWKS_URL", "").strip() or "https://auth.emarsys.net/.well-known/jwks.json"
ACCOUNT_ID = os.getenv("EMARSYS_ACCOUNT_ID", "").strip()

CANDIDATE_BASE_URLS = [
    "https://api.emarsys.net/api/v3/{account_id}",
    "https://api.emarsys.net/api/v2",
    "https://api.emarsys.net",
    "https://suite.emarsys.net/api/v2",
]

CAMPAIGN_PATHS = [
    "/campaigns",
    "/campaign",
    "/email",
    "/campaigns/list",
]


def _require_env() -> bool:
    ok = True
    if not CLIENT_ID:
        print("ERROR: CLIENT_ID/EMARSYS_CLIENT_ID nao configurado.")
        ok = False
    if not CLIENT_SECRET:
        print("ERROR: CLIENT_SECRET/EMARSYS_CLIENT_SECRET nao configurado.")
        ok = False
    if not TOKEN_URL:
        print("ERROR: TOKEN_ENDPOINT/EMARSYS_TOKEN_URL nao configurado.")
        ok = False
    if not ACCOUNT_ID:
        print("ERROR: EMARSYS_ACCOUNT_ID nao configurado.")
        ok = False
    return ok


def get_token() -> str | None:
    """Generate an access token via OAuth2 client_credentials."""
    print("\n[1/6] Gerando token OAuth2...")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    payload = {"grant_type": "client_credentials"}

    # Primeiro tenta client_secret_basic (foi o metodo exigido no seu tenant).
    try:
        resp = requests.post(
            TOKEN_URL,
            data=payload,
            headers=headers,
            auth=(CLIENT_ID, CLIENT_SECRET),
            timeout=20,
        )
    except requests.RequestException as exc:
        print(f"ERROR: Falha de rede ao gerar token: {exc}")
        return None

    # Fallback para client_secret_post, caso o tenant aceite esse metodo.
    if resp.status_code >= 400:
        try:
            details = resp.json()
        except ValueError:
            details = resp.text
        if "client_secret_post" in str(details).lower() or "invalid_client" in str(details).lower():
            fallback_payload = {
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            }
            try:
                resp = requests.post(TOKEN_URL, data=fallback_payload, headers=headers, timeout=20)
            except requests.RequestException as exc:
                print(f"ERROR: Falha de rede no fallback do token: {exc}")
                return None

    if resp.status_code != 200:
        print(f"ERROR: Token falhou ({resp.status_code}): {resp.text[:400]}")
        return None

    token_data = resp.json()
    print("OK: token gerado.")
    print(f"token_type={token_data.get('token_type')} expires_in={token_data.get('expires_in')}")
    return token_data.get("access_token")


def decode_jwt(token: str) -> dict[str, Any]:
    """Decode JWT payload without signature verification."""
    print("\n[2/6] Inspecionando JWT...")
    try:
        parts = token.split(".")
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return payload
    except Exception as exc:
        print(f"WARN: token nao parece JWT ou falhou decode: {exc}")
        return {}


def check_openid_discovery() -> dict[str, Any]:
    print("\n[3/6] OpenID discovery...")
    discovery_url = "https://auth.emarsys.net/.well-known/openid-configuration"
    try:
        resp = requests.get(discovery_url, timeout=20)
    except requests.RequestException as exc:
        print(f"WARN: falha ao consultar openid configuration: {exc}")
        return {}
    if resp.status_code == 200:
        data = resp.json()
        print("OK: openid configuration encontrado.")
        return data
    print(f"WARN: openid configuration indisponivel ({resp.status_code}).")
    return {}


def check_jwks() -> None:
    print("\n[4/6] Inspecionando JWKS...")
    try:
        resp = requests.get(JWKS_URL, timeout=20)
    except requests.RequestException as exc:
        print(f"WARN: falha ao consultar JWKS: {exc}")
        return
    if resp.status_code != 200:
        print(f"WARN: JWKS status={resp.status_code}")
        return
    data = resp.json()
    keys = data.get("keys", [])
    print(f"OK: {len(keys)} chave(s) encontrada(s).")
    for key in keys[:5]:
        print(f"- kid={key.get('kid')} alg={key.get('alg')} use={key.get('use')}")


def scan_endpoints(token: str) -> list[dict[str, Any]]:
    print("\n[5/6] Varrendo endpoints de campanhas...")
    headers = {"Authorization": f"Bearer {token}"}
    found: list[dict[str, Any]] = []

    for base_template in CANDIDATE_BASE_URLS:
        base = base_template.format(account_id=ACCOUNT_ID)
        for path in CAMPAIGN_PATHS:
            url = base + path
            try:
                resp = requests.get(url, headers=headers, timeout=10)
            except requests.RequestException as exc:
                print(f"WARN [{url}] erro de rede: {exc}")
                continue

            status = resp.status_code
            print(f"[{status}] GET {url}")
            if status == 200:
                data: Any
                try:
                    data = resp.json()
                except ValueError:
                    data = resp.text[:500]
                found.append({"url": url, "status": status, "data": data})
            elif status != 404:
                print(f"  response: {resp.text[:200]}")

    return found


def main() -> None:
    print("=" * 64)
    print("EMARSYS API DISCOVERY SCRIPT")
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 64)

    if not _require_env():
        return

    token = get_token()
    if not token:
        print("\nNao foi possivel continuar sem token.")
        return

    payload = decode_jwt(token)
    scopes = payload.get("scope") or payload.get("scp") or "nao encontrado"
    print(f"\nScopes no token: {scopes}")

    check_openid_discovery()
    check_jwks()
    found = scan_endpoints(token)

    print("\n[6/6] Resultado final")
    print("=" * 64)
    if found:
        print(f"OK: {len(found)} endpoint(s) com status 200:")
        for item in found:
            print(f"- {item['url']}")
    else:
        print("Nenhum endpoint retornou 200.")
        print("Se retornou 403, provavelmente faltam permissoes no tenant para o CLIENT_ID.")
    print("=" * 64)


if __name__ == "__main__":
    main()

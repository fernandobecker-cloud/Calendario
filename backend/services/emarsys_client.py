"""Cliente para a API da Emarsys (SAP Emarsys), usando autenticacao OIDC
(OAuth 2.0 client credentials) - metodo que a conta da iPlace ja usa
(confirmado na tela "Credenciais da API" do Emarsys, tipo "OIDC").

Portado do script standalone `emarsys_client.py` (testado localmente com
servidor HTTP fake) para dentro do backend, trocando `.env`/dotenv por
`os.getenv()`, no mesmo padrao de `backend/routes/open_data.py`.

COMO FUNCIONA A AUTENTICACAO
----------------------------
1. Com o Client ID + Client Secret (gerados na tela "Credenciais da API"),
   pede um access token em POST {EMARSYS_TOKEN_URL} com Basic Auth
   (client_id:client_secret) e grant_type=client_credentials.
2. O token e enviado como "Authorization: Bearer <token>" em cada chamada
   aos endpoints normais da API.
3. O token expira (campo "expires_in" da resposta); o cliente renova
   automaticamente quando precisar (com 30s de folga).

ATENCAO / DOMINIO DA API (nao totalmente confirmado ainda)
------------------------------------------------------------
Descoberto na pratica com a conta da iPlace: o dominio classico
`api.emarsys.net` (API v2 classica) NAO aceita o token OIDC em nenhum
endpoint - sempre exige o header WSSE antigo ("WSSE authentication header
is missing"), mesmo com Client ID/Secret OIDC corretos. A conta da iPlace
esta no produto "SAP Engagement Cloud", servido por um dominio diferente:
`api.sap.emarsys.net` - esse e o dominio que aceita o token OIDC (fonte:
repositorio publico "emartech/SAP-Engagement-Cloud-postman-collection-Beta").

O que AINDA NAO esta confirmado: o caminho exato do recurso de segmento
nesse dominio novo (testamos /segment, /segments, /combinedsegment,
/customers/{id}/segments - todos deram 404 na pratica). A pista mais forte
e que o nome historico do recurso "segmento" na API classica da Emarsys e
"filter", nao "segment" - ainda sem confirmacao contra a conta real. Use
`GET /api/emarsys/discover` (backend/routes/emarsys_segments.py) para
testar as combinacoes de dominio+caminho contra a conta real e descobrir
o caminho certo antes de confiar em `find_segment_by_name`/`export_segment`
abaixo.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

EMARSYS_TOKEN_URL = os.getenv("EMARSYS_TOKEN_URL", "https://auth.emarsys.net/oauth2/token").strip()
EMARSYS_BASE_URL = os.getenv("EMARSYS_BASE_URL", "https://api.sap.emarsys.net/api/v2").strip()
EMARSYS_CLIENT_ID = os.getenv("EMARSYS_CLIENT_ID", "").strip()
EMARSYS_CLIENT_SECRET = os.getenv("EMARSYS_CLIENT_SECRET", "").strip()

# Caminho do recurso de "segmento" dentro de EMARSYS_BASE_URL - NAO CONFIRMADO
# contra a conta real ainda (ver docstring do modulo). Configuravel para nao
# precisar de deploy novo assim que for confirmado via /api/emarsys/discover.
EMARSYS_SEGMENT_LIST_PATH = os.getenv("EMARSYS_SEGMENT_LIST_PATH", "/filter").strip()
EMARSYS_SEGMENT_EXPORT_PATH_TEMPLATE = os.getenv(
    "EMARSYS_SEGMENT_EXPORT_PATH_TEMPLATE", "/filter/{id}/export"
).strip()


class EmarsysError(RuntimeError):
    pass


@dataclass
class EmarsysConfig:
    client_id: str = EMARSYS_CLIENT_ID
    client_secret: str = EMARSYS_CLIENT_SECRET
    base_url: str = EMARSYS_BASE_URL
    token_url: str = EMARSYS_TOKEN_URL

    @classmethod
    def from_env(cls) -> "EmarsysConfig":
        return cls()


class EmarsysClient:
    def __init__(self, config: EmarsysConfig | None = None):
        self.config = config or EmarsysConfig.from_env()
        if not self.config.client_id or not self.config.client_secret:
            raise EmarsysError(
                "EMARSYS_CLIENT_ID/EMARSYS_CLIENT_SECRET nao configurados no ambiente."
            )
        self._token: Optional[str] = None
        self._token_expira_em: float = 0.0

    # ---------- Autenticacao (OIDC / OAuth2 client_credentials) ----------
    def _obter_token(self) -> str:
        agora = time.time()
        if self._token and agora < self._token_expira_em - 30:
            return self._token

        resp = requests.post(
            self.config.token_url,
            data={"grant_type": "client_credentials"},
            auth=(self.config.client_id, self.config.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if resp.status_code >= 400:
            raise EmarsysError(
                f"Falha ao obter token OIDC da Emarsys (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise EmarsysError(f"Resposta de token sem 'access_token': {data}")

        self._token = token
        self._token_expira_em = agora + float(data.get("expires_in", 300))
        return token

    def headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._obter_token()}",
        }

    def get_raw(self, base_url: str, path: str, *, timeout: int = 30) -> requests.Response:
        """GET sem parsing/validacao de envelope - usado pela descoberta de
        endpoints (varias bases/caminhos candidatos, sem assumir formato)."""
        return requests.get(f"{base_url}{path}", headers=self.headers(), timeout=timeout)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.config.base_url}{path}"
        resp = requests.request(method, url, headers=self.headers(), timeout=60, **kwargs)
        if resp.status_code >= 400:
            raise EmarsysError(
                f"Emarsys retornou HTTP {resp.status_code} em {method} {path}: {resp.text[:500]}"
            )
        try:
            data = resp.json()
        except ValueError:
            raise EmarsysError(f"Resposta nao-JSON da Emarsys em {method} {path}: {resp.text[:500]}")

        reply_code = data.get("replyCode")
        if reply_code not in (0, None):
            raise EmarsysError(f"Erro da Emarsys ({reply_code}): {data.get('replyText')}")
        return data

    # ---------- Chamadas usadas pela automacao ----------
    def test_conexao(self) -> list:
        """Pega um token OIDC e lista os itens do recurso de segmento configurado
        (EMARSYS_SEGMENT_LIST_PATH) - use para validar credenciais + caminho."""
        data = self._request("GET", EMARSYS_SEGMENT_LIST_PATH)
        return data.get("data", data.get("items", []))

    def find_segment_by_name(self, name: str) -> dict | None:
        """Busca um segmento pelo nome exato dentro do recurso configurado.

        NAO CONFIRMADO contra a conta real (ver docstring do modulo) - rode
        /api/emarsys/discover primeiro numa filial de teste (829) antes de
        confiar neste metodo em produção.
        """
        data = self._request("GET", EMARSYS_SEGMENT_LIST_PATH)
        itens = data.get("data", data.get("items", []))
        if isinstance(itens, dict) and isinstance(itens.get("items"), list):
            itens = itens["items"]
        for item in itens if isinstance(itens, list) else []:
            if not isinstance(item, dict):
                continue
            valor_nome = item.get("name") or item.get("nome") or item.get("title")
            if valor_nome and str(valor_nome).strip().lower() == name.strip().lower():
                return item
        return None

    def export_segment(self, segment_id: str, field_ids: list[str],
                        poll_seconds: int = 5, timeout_seconds: int = 300) -> bytes:
        """Dispara a exportacao de um segmento e aguarda o CSV ficar pronto.

        NAO CONFIRMADO contra a conta real (ver docstring do modulo) -
        EMARSYS_SEGMENT_EXPORT_PATH_TEMPLATE e a melhor hipotese atual, nao
        uma chamada ja testada.
        """
        path = EMARSYS_SEGMENT_EXPORT_PATH_TEMPLATE.format(id=segment_id)
        body = {"fields": field_ids, "format": "csv"}
        created = self._request("POST", path, json=body)
        export_id = created.get("data", {}).get("id")
        if not export_id:
            raise EmarsysError(f"Nao recebi um id de exportacao da Emarsys: {created}")

        waited = 0
        while waited < timeout_seconds:
            status_data = self._request("GET", f"/export/{export_id}")
            status = status_data.get("data", {}).get("status")
            if status == "ready" or status_data.get("data", {}).get("url"):
                return self._baixar_resultado_exportacao(export_id, status_data)
            if status == "error":
                raise EmarsysError(f"Exportacao {export_id} falhou: {status_data}")
            time.sleep(poll_seconds)
            waited += poll_seconds

        raise EmarsysError(f"Exportacao {export_id} nao ficou pronta em {timeout_seconds}s")

    def _baixar_resultado_exportacao(self, export_id: str, status_data: dict) -> bytes:
        url = status_data.get("data", {}).get("url")
        if url:
            resp = requests.get(url, timeout=120)
            resp.raise_for_status()
            return resp.content

        resp = requests.get(
            f"{self.config.base_url}/export/{export_id}/data",
            headers=self.headers(),
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content

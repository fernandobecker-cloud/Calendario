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

DOMINIO E CAMINHOS - CONFIRMADOS EM 2026-09 VIA POSTMAN COLLECTIONS PUBLICAS
------------------------------------------------------------------------------
A auditoria em /api/emarsys/discover mostrou que `api.sap.emarsys.net`
(dominio "SAP Engagement Cloud") so devolve 404 pra qualquer caminho de
segmento - essa teoria estava ERRADA (esse produto usa outro modelo,
`contactlist` estatico, sem segmento dinamico com criterios AND/NOT).
O caminho certo, confirmado contra os repositorios publicos do GitHub
`emartech/Emarsys-postman-collection` e `emartech/developer-hub-public-assets`
(que alimentam o dev.emarsys.com, um site que carrega via JS e por isso nao
dava pra ler direto): dominio CLASSICO `api.emarsys.net`, versao **v3**, SEM
account_id no path (o discover original testava
`/api/v3/{account_id}/filter`, com um segmento extra de path que nao existe
na API real - por isso ele so batia 403 generico, nao 404):

    GET  https://api.emarsys.net/api/v3/filter                 -> lista segmentos
    PUT  https://api.emarsys.net/api/v3/filter                  -> cria segmento
    POST https://api.emarsys.net/api/v3/export/filter           -> dispara export
    GET  https://api.emarsys.net/api/v3/export/{id}             -> status do export
    GET  https://api.emarsys.net/api/v3/export/{id}/data        -> baixa o CSV pronto

Confirmado apenas o CAMINHO e o FORMATO do envelope (`replyCode`/`replyText`/
`data`) e dos corpos de request/response - a Postman collection nao tem
exemplo real de resposta rodada contra uma conta (os campos tem valores
fake/lorem ipsum), e o dominio `api.emarsys.net/api/v3` em si so foi
confirmado como "aceita o token OIDC" (403 em vez de erro WSSE) pelo
`/api/emarsys/discover` rodado contra a conta real da iPlace - ainda nao
por uma chamada que tenha retornado 200. Ou seja: a FORMA esta confirmada
por documentacao publica, mas ainda falta confirmar que esse client OAuth
tem PERMISSAO/SCOPE liberado pra usar o recurso `filter`/`export` (o 403
pode ser por isso). Se `/api/emarsys/discover` ainda voltar 403/404 depois
dessa correcao, o proximo passo e verificar os escopos liberados na tela
"Credenciais da API" do Emarsys.

O QUE AINDA NAO ESTA CONFIRMADO
--------------------------------
- O valor exato do campo "status" que indica exportacao pronta (a doc so
  mostra "in progress" como exemplo generico) - `export_segment` abaixo
  trata qualquer status != "in progress"/erro como "pronto para baixar".
- `contact_fields` no corpo de POST /export/filter precisa dos IDs
  NUMERICOS de campo da Emarsys (ex: 3 = e-mail), nao nomes de campo -
  confirme os IDs na tela de campos do Emarsys antes de chamar /enviar.
- Se `Base_LJ.../NPI_LJ...` (segmento combinado, AND NOT opt-out) precisa
  do recurso separado `/combinedsegments` ou se um `PUT /filter` com
  `contactCriteria` aninhado (and/or/criteria, ver exemplo abaixo) já
  resolve. Sem efeito para leitura/export (que so precisa do ID do
  segmento, ja existente), so importa se algum dia implementarmos criacao
  automatica de segmento (fora de escopo por ora).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

EMARSYS_TOKEN_URL = os.getenv("EMARSYS_TOKEN_URL", "https://auth.emarsys.net/oauth2/token").strip()
EMARSYS_BASE_URL = os.getenv("EMARSYS_BASE_URL", "https://api.emarsys.net/api/v3").strip()
EMARSYS_CLIENT_ID = os.getenv("EMARSYS_CLIENT_ID", "").strip()
EMARSYS_CLIENT_SECRET = os.getenv("EMARSYS_CLIENT_SECRET", "").strip()

# Caminho do recurso de "segmento" dentro de EMARSYS_BASE_URL - confirmado
# via Postman collection publica (ver docstring do modulo). Mantido
# configuravel por env var pra ajustar sem redeploy se algo mudar.
EMARSYS_SEGMENT_LIST_PATH = os.getenv("EMARSYS_SEGMENT_LIST_PATH", "/filter").strip()
EMARSYS_EXPORT_PATH = os.getenv("EMARSYS_EXPORT_PATH", "/export/filter").strip()
EMARSYS_DISTRIBUTION_METHOD = os.getenv("EMARSYS_DISTRIBUTION_METHOD", "local").strip()


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
        """Busca um segmento pelo nome exato em GET /filter (envelope
        {"data": [{"id":.., "name":.., ...}, ...]}, confirmado via Postman
        collection publica - ver docstring do modulo)."""
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

    def export_segment(self, segment_id: int | str, field_ids: list[int | str],
                        poll_seconds: int = 5, timeout_seconds: int = 300) -> bytes:
        """Dispara a exportacao de um segmento (POST /export/filter) e aguarda
        o CSV ficar pronto, via polling em GET /export/{id} + download em
        GET /export/{id}/data - formato confirmado via Postman collection
        publica (ver docstring do modulo)."""
        body = {
            "distribution_method": EMARSYS_DISTRIBUTION_METHOD,
            "filter": int(segment_id) if str(segment_id).lstrip("-").isdigit() else segment_id,
            "contact_fields": [int(f) if str(f).isdigit() else f for f in field_ids],
            "delimiter": ",",
            "add_field_names_header": 1,
        }
        created = self._request("POST", EMARSYS_EXPORT_PATH, json=body)
        export_id = created.get("data", {}).get("id")
        if not export_id:
            raise EmarsysError(f"Nao recebi um id de exportacao da Emarsys: {created}")

        waited = 0
        while waited < timeout_seconds:
            status_data = self._request("GET", f"/export/{export_id}")
            status = str(status_data.get("data", {}).get("status", "")).strip().lower()
            if status in ("error", "failed", "falhou"):
                raise EmarsysError(f"Exportacao {export_id} falhou: {status_data}")
            if status and status != "in progress":
                return self._baixar_resultado_exportacao(export_id)
            time.sleep(poll_seconds)
            waited += poll_seconds

        raise EmarsysError(f"Exportacao {export_id} nao ficou pronta em {timeout_seconds}s")

    def _baixar_resultado_exportacao(self, export_id: str) -> bytes:
        resp = requests.get(
            f"{self.config.base_url}/export/{export_id}/data",
            headers=self.headers(),
            params={"offset": 0, "limit": 10_000_000},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.content

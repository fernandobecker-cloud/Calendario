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

DOWNLOAD DO EXPORT - GET /export/{id}/data NAO FUNCIONA, USE O WEBDAV
------------------------------------------------------------------------
Confirmado contra a conta real (2026-09): `GET /api/v3/export/{id}/data`
nao retorna o arquivo - devolve o mesmo JSON de `GET /export/{id}` (rota
nao implementada de fato, so documentada). E `GET /api/v2/export/{id}/data`
exige WSSE ("WSSE authentication header is missing"), que esta conta nao
tem configurado (so OIDC).

O que REALMENTE funciona: toda exportacao com `distribution_method="local"`
cai automaticamente numa pasta WebDAV hospedada pela propria Emarsys, em
`{EMARSYS_WEBDAV_BASE_URL}/export/{file_name}` (o `file_name` vem no corpo
de `GET /export/{id}` quando o status fica pronto, ex:
"export_33231_1_en-2026_09_03.csv"). Essa pasta e a mesma que aparece na
tela "Configurações de segurança" > "Encaminhamento de dados" (usuarios
WebDAV) do Emarsys - autenticacao HTTP Basic com usuario/senha WebDAV
(NAO e o Client ID/Secret OIDC, e uma credencial separada). Confirmado
que essa pasta EXIGE autenticacao (testado sem login = pede usuario/senha).

O QUE AINDA NAO ESTA CONFIRMADO
--------------------------------
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

# Pasta WebDAV hospedada pela Emarsys onde exports "local" realmente caem
# (ver docstring do modulo) - autenticacao HTTP Basic separada do OIDC.
EMARSYS_WEBDAV_BASE_URL = os.getenv("EMARSYS_WEBDAV_BASE_URL", "https://suite63.emarsys.net/storage/iplace").strip()
EMARSYS_WEBDAV_USER = os.getenv("EMARSYS_WEBDAV_USER", "").strip()
EMARSYS_WEBDAV_PASSWORD = os.getenv("EMARSYS_WEBDAV_PASSWORD", "").strip()


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
        # Sem Content-Type aqui de proposito: em GET (sem corpo) o curl que
        # confirmamos funcionando na conta real nao mandava esse header, e
        # o `requests` ja adiciona Content-Type: application/json por conta
        # propria quando o kwarg `json=` e passado (POST/PUT com corpo).
        return {"Authorization": f"Bearer {self._obter_token()}"}

    def get_raw(self, base_url: str, path: str, *, timeout: int = 30) -> requests.Response:
        """GET sem parsing/validacao de envelope - usado pela descoberta de
        endpoints (varias bases/caminhos candidatos, sem assumir formato)."""
        url = f"{base_url.rstrip('/')}{path}"
        return requests.get(url, headers=self.headers(), timeout=timeout)

    def _request(self, method: str, path: str, **kwargs) -> dict:
        # rstrip evita barra dupla se EMARSYS_BASE_URL tiver "/" no final
        # (ex: ".../v3/" + "/filter/123" -> ".../v3//filter/123", que vira
        # 404 de rota inexistente em vez de bater no recurso certo).
        url = f"{self.config.base_url.rstrip('/')}{path}"
        resp = requests.request(method, url, headers=self.headers(), timeout=60, **kwargs)
        if resp.status_code >= 400:
            raise EmarsysError(
                f"Emarsys retornou HTTP {resp.status_code} em {method} {url}: {resp.text[:500]}"
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

    def get_segment_by_id(self, segment_id: int | str) -> dict:
        """Busca um segmento por ID direto em GET /filter/{id} - CONFIRMADO
        funcionando contra a conta real (2026-09), diferente da busca por
        lista (ver find_segment_by_name abaixo). Retorna {"id", "name",
        "type", ...}."""
        data = self._request("GET", f"{EMARSYS_SEGMENT_LIST_PATH}/{segment_id}")
        return data.get("data", {})

    def find_segment_by_name(self, name: str) -> dict | None:
        """Busca um segmento pelo nome exato em GET /filter (lista completa).

        ATENCAO: confirmado contra a conta real (2026-09) que este endpoint
        (listar todos os segmentos) da 403 "sem_acesso" mesmo com a
        permissao "segment.list" ativa na tela de credenciais - ainda sem
        explicacao (aberto com o suporte da Emarsys). GET /filter/{id}
        direto (get_segment_by_id) funciona normalmente. Prefira preencher
        `segmento_combinado_id` no CSV de lojas (backend/data/
        mapeamento_lojas_sap.csv) em vez de depender deste metodo."""
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
                        poll_seconds: int = 5, timeout_seconds: int = 240) -> bytes:
        """Dispara a exportacao de um segmento (POST /export/filter) e aguarda
        o CSV ficar pronto, via polling em GET /export/{id} + download pelo
        WebDAV da Emarsys (GET /export/{id}/data nao funciona - ver docstring
        do modulo)."""
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
        ultimo_status = ""
        while waited < timeout_seconds:
            status_data = self._request("GET", f"/export/{export_id}")
            data = status_data.get("data", {})
            # Confirmado contra a conta real (2026-09): ha mais status
            # intermediarios do que a doc/collection publica sugere
            # ("scheduled", "in_progress", possivelmente outros) - em vez de
            # tentar enumerar todos os valores de "ainda processando", so
            # consideramos pronto quando file_name de fato aparecer.
            ultimo_status = str(data.get("status", "")).strip().lower()
            if ultimo_status in ("error", "failed", "falhou"):
                raise EmarsysError(f"Exportacao {export_id} falhou: {status_data}")
            file_name = data.get("file_name")
            if file_name:
                return self._baixar_do_webdav(file_name)
            time.sleep(poll_seconds)
            waited += poll_seconds

        raise EmarsysError(
            f"Exportacao {export_id} nao ficou pronta em {timeout_seconds}s (ultimo status: '{ultimo_status}')"
        )

    def _baixar_do_webdav(self, file_name: str) -> bytes:
        if not EMARSYS_WEBDAV_USER or not EMARSYS_WEBDAV_PASSWORD:
            raise EmarsysError(
                "EMARSYS_WEBDAV_USER/EMARSYS_WEBDAV_PASSWORD nao configurados - "
                "necessarios para baixar o export da pasta WebDAV da Emarsys."
            )
        resp = requests.get(
            f"{EMARSYS_WEBDAV_BASE_URL}/export/{file_name}",
            auth=(EMARSYS_WEBDAV_USER, EMARSYS_WEBDAV_PASSWORD),
            timeout=120,
        )
        if resp.status_code >= 400:
            raise EmarsysError(
                f"Falha ao baixar '{file_name}' do WebDAV (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        return resp.content

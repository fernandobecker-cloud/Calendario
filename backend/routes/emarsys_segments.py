"""Automacao de envio de listas de clientes do Emarsys para os gerentes de
cada loja da iPlace.

Porta a logica ja escrita e testada localmente (fora do portal, Python
puro) em `emarsys_client.py` / `mapa_lojas.py` / `descobrir_segmentos.py` /
`enviar_arquivos_lojas.py` para dentro do FastAPI, seguindo o padrao de
`backend/routes/open_data.py` (APIRouter, config via os.getenv()).

IMPORTANTE - O QUE AINDA NAO ESTA CONFIRMADO
---------------------------------------------
O caminho do recurso de "segmento" (`EMARSYS_SEGMENT_LIST_PATH`/
`EMARSYS_EXPORT_PATH` em `backend/services/emarsys_client.py`) ja foi
CONFIRMADO por documentacao publica (Postman collections oficiais da
Emarsys no GitHub - ver docstring desse modulo): dominio
`https://api.emarsys.net/api/v3`, recurso `/filter` (lista/cria segmento)
e `/export/filter` (dispara export). O que ainda falta confirmar contra a
conta real e se esse client OAuth tem PERMISSAO pra usar esse recurso (o
`/api/emarsys/discover` anterior batia 403 num caminho errado por acidente
- via account_id no path, que nao existe na API real; agora testa o
caminho certo).

Este modulo NAO implementa criacao automatica de segmento (a estrutura de
criterios AND/OR/NOT ate tem exemplo documentado, mas nunca foi testada
contra a conta real, e um POST malformado criaria segmento de marketing
errado numa conta de produção) - se o segmento de uma loja nao existir, os
endpoints abaixo retornam erro pedindo para criar manualmente na tela do
Emarsys (a filial 829 ja tem os dois segmentos prontos la e serve de caso
de teste).

Antes de usar /enviar ou /enviar-todas em producao, rode
GET /api/emarsys/discover para confirmar que o caminho responde 200 (nao
403/404) contra a conta real.

SEGURANCA
---------
- Todas as rotas exigem role="admin" (checagem local `require_admin`, sem
  importar de backend.server para nao criar import circular - server.py
  importa este modulo para registrar o router).
- `dry_run=true` e o padrao em /enviar e /enviar-todas: simula tudo (acha
  segmento, exporta, divide por loja) e mostra o que SERIA enviado, sem
  chamar SMTP. Para mandar de verdade e preciso `dry_run=false` explicito
  (e, em /enviar-todas, tambem `confirmar=true` - acao em massa).
- CSVs com dado de cliente sao gerados em diretorio temporario e apagados
  ao final da requisicao (nunca ficam em disco, LGPD).
"""

from __future__ import annotations

import csv
import io
import logging
import os
import smtplib
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from backend.services.emarsys_client import (
    EMARSYS_EXPORT_PATH,
    EMARSYS_SEGMENT_LIST_PATH,
    EmarsysClient,
    EmarsysError,
)
from backend.services.mapa_lojas import Loja, carregar_mapa, obter_loja

router = APIRouter(prefix="/api/emarsys", tags=["emarsys"])
log = logging.getLogger("emarsys_segments")

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USER
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() != "false"

CAMPO_LOJA_EXPORT = os.getenv("EMARSYS_CAMPO_LOJA_EXPORT", "codigo_loja").strip()

# Dominios+bases candidatos para /discover. https://api.emarsys.net/api/v3 e
# o confirmado por documentacao publica (Postman collections oficiais da
# Emarsys no GitHub - ver docstring do modulo e de emarsys_client.py); os
# demais ficam so pra registrar o contraste de erro (v2 classico exige WSSE,
# nunca aceita OIDC; api.sap.emarsys.net e o dominio "SAP Engagement Cloud",
# testado e confirmado como caminho ERRADO pra esta conta - usa outro
# modelo de dados, `contactlist` estatico, sem segmento dinamico).
CANDIDATOS_BASE = [
    "https://api.emarsys.net/api/v3",
    "https://api.emarsys.net/api/v2",
    "https://api.sap.emarsys.net/api/v2",
]
CANDIDATOS_SEGMENTO = ["/filter", "/segment", "/segments"]
CANDIDATOS_COMBINEDSEGMENT = ["/combinedsegments", "/combinedsegment"]


def require_admin(request: Request) -> None:
    auth_user = getattr(request.state, "auth_user", None)
    if auth_user is None:
        raise HTTPException(status_code=401, detail="Nao autenticado")
    if getattr(auth_user, "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem executar esta acao")


def _get_client() -> EmarsysClient:
    try:
        return EmarsysClient()
    except EmarsysError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Diagnostico (somente leitura) - porta descobrir_segmentos.py
# ---------------------------------------------------------------------------

def _tentar_get(client: EmarsysClient, base: str, path: str) -> dict[str, Any]:
    url = f"{base}{path}"
    try:
        resp = client.get_raw(base, path)
    except Exception as exc:  # rede, timeout, etc.
        return {"url": url, "status": "erro_rede", "detalhe": str(exc)}

    if "WSSE authentication header is missing" in resp.text:
        return {"url": url, "status": "dominio_errado_wsse"}
    if resp.status_code in (401, 403):
        return {"url": url, "status": "sem_acesso", "http_status": resp.status_code}
    if resp.status_code == 404:
        return {"url": url, "status": "nao_existe"}
    if resp.status_code >= 400:
        return {"url": url, "status": "erro", "http_status": resp.status_code, "corpo": resp.text[:300]}

    try:
        data = resp.json()
    except ValueError:
        return {"url": url, "status": "ok_formato_inesperado", "corpo": resp.text[:300]}

    itens = None
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            itens = data["data"]
        elif isinstance(data.get("items"), list):
            itens = data["items"]
        elif isinstance(data.get("data"), dict) and isinstance(data["data"].get("items"), list):
            itens = data["data"]["items"]
    elif isinstance(data, list):
        itens = data

    if itens is None:
        return {"url": url, "status": "ok_formato_inesperado", "corpo": str(data)[:500]}
    return {"url": url, "status": "ok", "total_itens": len(itens), "itens": itens}


def _buscar_por_nome(itens: list, nome: str) -> list:
    achados = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        valor_nome = item.get("name") or item.get("nome") or item.get("title")
        if valor_nome and nome.strip().lower() in str(valor_nome).strip().lower():
            achados.append(item)
    return achados


@router.get("/discover")
def discover(
    request: Request,
    nome: str = Query(default="", description="Nome (ou parte) do segmento a procurar"),
    filial: str = Query(default="", description="Numero da FILIAL - calcula Base_LJ.../NPI_LJ... automaticamente"),
) -> dict[str, Any]:
    """Testa combinacoes de dominio+caminho candidatas contra a conta real e
    procura o(s) nome(s) pedidos - somente GET, nao cria/altera nada.
    Use isto ANTES de confiar em /enviar - e o "primeiro passo tecnico"
    necessario para confirmar o caminho certo do recurso de segmento."""
    require_admin(request)

    nomes: list[str] = []
    loja: Loja | None = None
    if filial:
        try:
            loja = obter_loja(filial)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        nomes = [loja.nome_segmento_base, loja.nome_segmento_combinado]
    elif nome:
        nomes = [nome]
    else:
        raise HTTPException(status_code=400, detail="Informe 'nome' ou 'filial'.")

    client = _get_client()
    tentativas: list[dict[str, Any]] = []
    itens_segmento: list = []
    itens_combinado: list = []

    for base in CANDIDATOS_BASE:
        for path in CANDIDATOS_SEGMENTO:
            resultado = _tentar_get(client, base, path)
            tentativas.append({**resultado, "tipo": "segmento"})
            if resultado.get("status") == "ok":
                itens_segmento.extend(resultado.get("itens", []))
        for path in CANDIDATOS_COMBINEDSEGMENT:
            resultado = _tentar_get(client, base, path)
            tentativas.append({**resultado, "tipo": "combinedsegment"})
            if resultado.get("status") == "ok":
                itens_combinado.extend(resultado.get("itens", []))

    achados_por_nome = {
        n: _buscar_por_nome(itens_segmento, n) + _buscar_por_nome(itens_combinado, n)
        for n in nomes
    }

    # remove a lista bruta de itens das tentativas na resposta (fica so no achados_por_nome) -
    # evita responder um payload gigante com todos os segmentos da conta repetidos por tentativa.
    tentativas_resumidas = [{k: v for k, v in t.items() if k != "itens"} for t in tentativas]

    return {
        "loja": {"filial": loja.filial, "descricao": loja.descricao} if loja else None,
        "nomes_procurados": nomes,
        "achados": achados_por_nome,
        "algum_nao_encontrado": any(not v for v in achados_por_nome.values()),
        "tentativas": tentativas_resumidas,
        "total_tentativas": len(tentativas_resumidas),
    }


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    """Testa autenticacao + o caminho de segmento hoje configurado
    (EMARSYS_SEGMENT_LIST_PATH). Nao cria/altera nada."""
    require_admin(request)
    client = _get_client()
    try:
        itens = client.test_conexao()
    except EmarsysError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao conectar na Emarsys: {exc}") from exc
    return {
        "ok": True,
        "segment_list_path": EMARSYS_SEGMENT_LIST_PATH,
        "export_path": EMARSYS_EXPORT_PATH,
        "total_itens": len(itens),
    }


# ---------------------------------------------------------------------------
# Mapeamento de lojas (local, sem chamada externa)
# ---------------------------------------------------------------------------

@router.get("/lojas")
def listar_lojas(request: Request) -> dict[str, Any]:
    require_admin(request)
    mapa = carregar_mapa()
    return {
        "total": len(mapa),
        "items": [
            {
                "filial": loja.filial,
                "centro_sap": loja.centro_sap,
                "descricao": loja.descricao,
                "regional": loja.regional,
                "segmento_base": loja.nome_segmento_base,
                "segmento_combinado": loja.nome_segmento_combinado,
                "email_gerente": loja.email_gerente,
                "email_subgerente": loja.email_subgerente,
            }
            for loja in mapa.values()
        ],
    }


@router.get("/lojas/{filial}")
def obter_loja_endpoint(filial: str, request: Request) -> dict[str, Any]:
    require_admin(request)
    try:
        loja = obter_loja(filial)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "filial": loja.filial,
        "centro_sap": loja.centro_sap,
        "descricao": loja.descricao,
        "regional": loja.regional,
        "gerente_regional": loja.gerente_regional,
        "segmento_base": loja.nome_segmento_base,
        "segmento_combinado": loja.nome_segmento_combinado,
        "email_gerente": loja.email_gerente,
        "email_subgerente": loja.email_subgerente,
    }


# ---------------------------------------------------------------------------
# Exportar + dividir + enviar - porta enviar_arquivos_lojas.py
# ---------------------------------------------------------------------------

def _dividir_csv_por_loja(csv_bytes: bytes, campo_loja: str, *, filial_padrao: str) -> dict[str, list[dict]]:
    """Divide as linhas do export pelo campo de loja - so uma rede de
    seguranca (cada segmento ja e de uma loja so). Se a coluna nao vier no
    export (o campo so entra se seu ID numerico tiver sido passado em
    `campos`, e nao e obrigatorio), nao falha: trata tudo como pertencente
    a `filial_padrao` (a loja que estamos processando)."""
    texto = csv_bytes.decode("utf-8-sig")
    leitor = csv.DictReader(io.StringIO(texto))
    linhas = list(leitor)
    if campo_loja not in (leitor.fieldnames or []):
        return {filial_padrao: linhas} if linhas else {}
    por_loja: dict[str, list[dict]] = {}
    for linha in linhas:
        codigo = (linha.get(campo_loja) or "").strip() or filial_padrao
        por_loja.setdefault(codigo, []).append(linha)
    return por_loja


def _escrever_csv_temp(diretorio: Path, codigo_loja: str, linhas: list[dict]) -> Path:
    destino = diretorio / f"contatos_loja_{codigo_loja}.csv"
    with open(destino, "w", newline="", encoding="utf-8") as f:
        escritor = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        escritor.writeheader()
        escritor.writerows(linhas)
    return destino


def _enviar_email(destinatarios: list[str], assunto: str, corpo: str, anexo: Path) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD]):
        raise HTTPException(status_code=500, detail="SMTP_HOST/SMTP_USER/SMTP_PASSWORD nao configurados no ambiente.")
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto
    msg.set_content(corpo)
    with open(anexo, "rb") as f:
        msg.add_attachment(f.read(), maintype="text", subtype="csv", filename=anexo.name)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
        if SMTP_USE_TLS:
            server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)


def _processar_loja(
    client: EmarsysClient,
    loja: Loja,
    *,
    campos_exportacao: list[str],
    campo_loja: str,
    campanha: str,
    dry_run: bool,
    email_teste: str,
) -> dict[str, Any]:
    try:
        if loja.segmento_combinado_id:
            # GET /filter/{id} direto - confirmado funcionando. Preferido
            # sobre a busca por nome (GET /filter lista, que da 403 nesta
            # conta mesmo com a permissao certa ativa - ver docstring de
            # find_segment_by_name).
            segmento = client.get_segment_by_id(loja.segmento_combinado_id)
        else:
            segmento = client.find_segment_by_name(loja.nome_segmento_combinado)
    except EmarsysError as exc:
        return {
            "filial": loja.filial,
            "ok": False,
            "erro": f"Falha ao buscar segmento '{loja.nome_segmento_combinado}': {exc}",
        }
    if not segmento:
        return {
            "filial": loja.filial,
            "ok": False,
            "erro": f"Segmento '{loja.nome_segmento_combinado}' nao encontrado. "
                    f"Crie manualmente na tela do Emarsys antes de rodar este envio "
                    f"(estrutura AND/NOT ainda nao confirmada para criacao automatica), "
                    f"ou preencha 'segmento_combinado_id' no CSV de lojas se ja existir.",
        }
    segmento_id = segmento.get("id") or segmento.get("id_", "")

    try:
        csv_bytes = client.export_segment(str(segmento_id), campos_exportacao)
    except EmarsysError as exc:
        return {"filial": loja.filial, "ok": False, "erro": f"Falha ao exportar segmento: {exc}"}

    por_loja = _dividir_csv_por_loja(csv_bytes, campo_loja, filial_padrao=loja.filial)
    outras_filiais = sorted(set(por_loja) - {loja.filial})
    if outras_filiais:
        log.warning(
            "Segmento %s (filial %s) trouxe contatos de outras filiais no export: %s "
            "- isso indica que o segmento nao esta 100%% escopado so a essa loja.",
            loja.nome_segmento_combinado, loja.filial, outras_filiais,
        )

    resultado: dict[str, Any] = {
        "filial": loja.filial,
        "ok": True,
        "segmento_id": segmento_id,
        "grupos_no_export": {k: len(v) for k, v in por_loja.items()},
        "aviso_outras_filiais": outras_filiais or None,
        "dry_run": dry_run,
        "envios": [],
    }

    assunto_base = f"[iPlace CRM] Lista de clientes - {campanha}".strip()
    corpo_base = (
        "Ola,\n\n"
        f"Segue em anexo a lista de clientes da campanha \"{campanha}\" referente a sua loja.\n"
        "Este arquivo contem dados de clientes e deve ser tratado como confidencial "
        "(nao compartilhar com outras lojas ou terceiros).\n\n"
        "Att,\nCRM Grupo Herval / iPlace"
    )

    with tempfile.TemporaryDirectory(prefix="emarsys_lojas_") as tmp:
        tmp_path = Path(tmp)
        for codigo_loja, linhas in sorted(por_loja.items()):
            arquivo = _escrever_csv_temp(tmp_path, codigo_loja, linhas)
            if email_teste:
                destinatarios = [email_teste]
                assunto = f"[TESTE - loja {codigo_loja}] {assunto_base}"
            else:
                try:
                    loja_destino = obter_loja(codigo_loja)
                    destinatarios = [loja_destino.email_gerente, loja_destino.email_subgerente]
                except KeyError:
                    destinatarios = [f"gerente{codigo_loja}@iplace.com.br", f"subgerente{codigo_loja}@iplace.com.br"]
                assunto = assunto_base

            if dry_run:
                resultado["envios"].append({
                    "codigo_loja": codigo_loja, "contatos": len(linhas),
                    "destinatarios": destinatarios, "enviado": False,
                })
                continue

            try:
                _enviar_email(destinatarios, assunto, corpo_base, arquivo)
                resultado["envios"].append({
                    "codigo_loja": codigo_loja, "contatos": len(linhas),
                    "destinatarios": destinatarios, "enviado": True,
                })
            except Exception as exc:
                resultado["envios"].append({
                    "codigo_loja": codigo_loja, "contatos": len(linhas),
                    "destinatarios": destinatarios, "enviado": False, "erro": str(exc),
                })
        # arquivos CSV somem junto com o TemporaryDirectory ao saltar fora do `with` (LGPD).

    return resultado


@router.post("/enviar/{filial}")
def enviar_uma_loja(
    filial: str,
    request: Request,
    campanha: str = Query(default=""),
    campos: str = Query(default="", description="IDs NUMERICOS de campo da Emarsys a exportar (ex: 3 = e-mail), separados por virgula - confirme na tela de campos do Emarsys"),
    campo_loja: str = Query(default=CAMPO_LOJA_EXPORT, description="Nome da coluna de loja no CSV exportado - so tem efeito se o ID numerico do campo correspondente tambem estiver em 'campos'; senao o export inteiro conta como da filial pedida"),
    dry_run: bool = Query(default=True, description="true (padrao) = simula sem enviar e-mail nenhum"),
    email_teste: str = Query(default="", description="Se definido, envia so para este endereco em vez do gerente/subgerente real"),
) -> dict[str, Any]:
    require_admin(request)
    try:
        loja = obter_loja(filial)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    campos_exportacao = [c.strip() for c in campos.split(",") if c.strip()]
    client = _get_client()
    try:
        return _processar_loja(
            client, loja,
            campos_exportacao=campos_exportacao, campo_loja=campo_loja,
            campanha=campanha, dry_run=dry_run, email_teste=email_teste,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao processar loja {filial}: {exc}") from exc


@router.post("/enviar-todas")
def enviar_todas_lojas(
    request: Request,
    campanha: str = Query(default=""),
    campos: str = Query(default=""),
    campo_loja: str = Query(default=CAMPO_LOJA_EXPORT, description="Nome da coluna de loja no CSV exportado - so tem efeito se o ID numerico do campo correspondente tambem estiver em 'campos'; senao o export inteiro conta como da filial pedida"),
    dry_run: bool = Query(default=True, description="true (padrao) = simula sem enviar e-mail nenhum"),
    confirmar: bool = Query(default=False, description="precisa ser true (alem de dry_run=false) para disparar envio real em massa"),
    email_teste: str = Query(default="", description="Se definido, envia so para este endereco em vez do gerente/subgerente real"),
) -> dict[str, Any]:
    require_admin(request)
    if not dry_run and not confirmar:
        raise HTTPException(
            status_code=400,
            detail="Envio em massa real exige dry_run=false E confirmar=true explicitos.",
        )

    campos_exportacao = [c.strip() for c in campos.split(",") if c.strip()]
    client = _get_client()
    mapa = carregar_mapa()

    resultados = []
    for loja in mapa.values():
        try:
            resultados.append(_processar_loja(
                client, loja,
                campos_exportacao=campos_exportacao, campo_loja=campo_loja,
                campanha=campanha, dry_run=dry_run, email_teste=email_teste,
            ))
        except HTTPException as exc:
            resultados.append({"filial": loja.filial, "ok": False, "erro": exc.detail})
        except Exception as exc:
            resultados.append({"filial": loja.filial, "ok": False, "erro": str(exc)})

    return {
        "dry_run": dry_run,
        "total_lojas": len(resultados),
        "sucesso": sum(1 for r in resultados if r.get("ok")),
        "falha": sum(1 for r in resultados if not r.get("ok")),
        "resultados": resultados,
    }

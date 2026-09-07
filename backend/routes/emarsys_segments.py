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
Emarsys.

IMPORTANTE - BASE, nao COMBINADO: a automacao usa o segmento BASE
(Base_LJ...) de cada loja, nao o combinado (NPI_LJ..., que tem criterios
extras de uma campanha especifica). A unica vantagem do combinado pra uso
geral - excluir opt-out de WhatsApp - ja e feita no codigo (ver
`_filtrar_opt_out`), entao o base (lista completa de clientes da loja) e o
correto aqui. Erro identificado e corrigido em 2026-09: a automacao estava
usando o id do segmento COMBINADO da filial 829 (1028033362) por engano -
esse valor foi removido do CSV de lojas; falta preencher o id do segmento
BASE de 829 (e das demais lojas) em `segmento_base_id`.

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

import base64
import csv
import io
import logging
import os
import re
import smtplib
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

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

# IDs numericos sempre incluidos no export, mesmo que o admin nao peca em
# 'campos'. 13504/13505 (confirmados via GET /field/translate/en contra a
# conta real) sao os campos de opt-out de WhatsApp - o filtro de opt-out
# (ver `_filtrar_opt_out`) depende deles existirem no CSV. 17506 e campo
# customizado da iPlace que marca cliente SuperVIP (confirmado pelo
# usuario) - so informativo no CSV, sem logica de filtro em cima dele.
CAMPO_OPT_IN_ID = "13504"
CAMPO_OPT_IN_NOME = "Conversational WhatsApp Opt-In"
CAMPO_BAD_NUMBER_ID = "13505"
CAMPO_BAD_NUMBER_NOME = "Conversational WhatsApp Bad Number"
CAMPO_SUPERVIP_ID = "17506"
CAMPOS_OBRIGATORIOS_IDS = [CAMPO_OPT_IN_ID, CAMPO_BAD_NUMBER_ID, CAMPO_SUPERVIP_ID]

# Campos "de conteudo" usados como padrao quando o admin nao informa
# 'campos' explicitamente - confirmados contra um export real (2026-09):
# 1=First Name, 2=Last Name, 3=Email, 37=Mobile (Phone/15 e Nome da
# Loja/14831, loja/16493, Contact source/33 e Contact form/34 foram
# removidos do padrao a pedido do usuario - so celular, sem telefone fixo
# nem esses outros campos). Os obrigatorios (opt-out + SuperVIP) sao sempre
# somados a esta lista por `_com_campos_obrigatorios`, nao precisam ser
# repetidos aqui.
CAMPOS_PADRAO = "1,2,3,37"

# Guarda quais export_id ja foram efetivamente enviados (dry_run=false) pelo
# fluxo em duas fases (/enviar-todas/coletar), pra nao mandar o mesmo e-mail
# duas vezes se o admin passar o mesmo lote de novo por engano. So faz
# sentido em memoria porque o gunicorn roda com --workers 1 (ver start.sh) -
# nao sobrevive a reinicio do processo, o que e aceitavel pq o fluxo
# esperado e iniciar+coletar dentro do mesmo deploy.
_exports_ja_enviados: set[str] = set()


def _com_campos_obrigatorios(campos_exportacao: list[str]) -> list[str]:
    resultado = list(campos_exportacao)
    for campo_id in CAMPOS_OBRIGATORIOS_IDS:
        if campo_id not in resultado:
            resultado.append(campo_id)
    return resultado


def _filtrar_opt_out(linhas: list[dict]) -> tuple[list[dict], int]:
    """Remove contatos com opt-out de WhatsApp confirmado: opt-in != 'True'
    ou numero marcado como invalido pela Emarsys (campo nao-vazio). Se o CSV
    nao trouxer essas colunas (export antigo, ou 'campos' que por algum
    motivo nao incluiu os IDs obrigatorios), nao filtra nada - so avisa no
    log, pra nao excluir todo mundo por engano."""
    if not linhas:
        return linhas, 0
    colunas = linhas[0].keys()
    if CAMPO_OPT_IN_NOME not in colunas and CAMPO_BAD_NUMBER_NOME not in colunas:
        log.warning(
            "Export sem as colunas de opt-out ('%s' / '%s') - pulando filtro de opt-out.",
            CAMPO_OPT_IN_NOME, CAMPO_BAD_NUMBER_NOME,
        )
        return linhas, 0
    mantidos = []
    excluidos = 0
    for linha in linhas:
        opt_in = (linha.get(CAMPO_OPT_IN_NOME) or "").strip()
        bad_number = (linha.get(CAMPO_BAD_NUMBER_NOME) or "").strip()
        if opt_in.lower() != "true" or bad_number:
            excluidos += 1
            continue
        mantidos.append(linha)
    return mantidos, excluidos

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
                "segmento_base_id": loja.segmento_base_id or None,
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
        "segmento_base_id": loja.segmento_base_id or None,
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


_CARACTERES_INVALIDOS_ARQUIVO = re.compile(r'[\\/:*?"<>|]')


def _nome_arquivo_loja(codigo_loja: str) -> str:
    """Nome de arquivo com o nome da loja (pedido do usuario, pra nao
    confundir quando baixar de varias lojas de uma vez) - cai pro codigo
    puro se a loja nao estiver mapeada."""
    try:
        loja = obter_loja(codigo_loja)
        base = f"{codigo_loja} - {loja.descricao}"
    except KeyError:
        base = f"contatos_loja_{codigo_loja}"
    return _CARACTERES_INVALIDOS_ARQUIVO.sub("_", base).strip() + ".csv"


def _csv_bytes_em_memoria(linhas: list[dict]) -> bytes:
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=list(linhas[0].keys()))
    escritor.writeheader()
    escritor.writerows(linhas)
    return buffer.getvalue().encode("utf-8-sig")


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


def _resolver_segmento_id(client: EmarsysClient, loja: Loja) -> tuple[str, str]:
    """Acha o id do segmento BASE (Base_LJ...) da loja. Devolve
    (segmento_id, erro) - exatamente um dos dois preenchido.

    Usa o segmento BASE, nao o combinado (NPI_LJ...): o combinado tem
    criterios extras de uma campanha NPI especifica, e sua unica vantagem
    sobre o base pra uso geral (excluir opt-out de WhatsApp) ja e feita no
    codigo (ver `_filtrar_opt_out`) - o base e a lista completa de clientes
    da loja, correta pra automacao geral.

    Preferido: `segmento_base_id` do CSV de lojas, via GET /filter/{id}
    direto (confirmado funcionando). Fallback: busca por nome (GET /filter
    lista, que da 403 nesta conta mesmo com a permissao certa ativa - ver
    docstring de find_segment_by_name)."""
    try:
        if loja.segmento_base_id:
            segmento = client.get_segment_by_id(loja.segmento_base_id)
        else:
            segmento = client.find_segment_by_name(loja.nome_segmento_base)
    except EmarsysError as exc:
        return "", f"Falha ao buscar segmento '{loja.nome_segmento_base}': {exc}"
    if not segmento:
        return "", (
            f"Segmento '{loja.nome_segmento_base}' nao encontrado. "
            f"Crie manualmente na tela do Emarsys antes de rodar este envio, "
            f"ou preencha 'segmento_base_id' no CSV de lojas se ja existir."
        )
    segmento_id = segmento.get("id") or segmento.get("id_", "")
    return str(segmento_id), ""


def _dividir_e_enviar(
    loja: Loja,
    csv_bytes: bytes,
    *,
    segmento_id: str,
    campo_loja: str,
    campanha: str,
    dry_run: bool,
    email_teste: str,
    baixar_arquivo: bool = False,
) -> dict[str, Any]:
    """Divide o CSV ja baixado pelo campo de loja e manda (ou simula, se
    dry_run) um e-mail por loja encontrada. Usado tanto pelo fluxo sincrono
    de loja unica quanto pela etapa `coletar` do fluxo em duas fases.

    Se `baixar_arquivo=True`, NAO manda e-mail nenhum (ignora dry_run e
    email_teste) - so devolve o CSV de cada loja em base64 dentro do
    resultado, pro chamador (endpoint HTTP) devolver como download pro
    navegador. Existe pra quem prefere distribuir os arquivos por fora
    (outra automacao/ferramenta) em vez de usar o SMTP deste backend."""
    por_loja_bruto = _dividir_csv_por_loja(csv_bytes, campo_loja, filial_padrao=loja.filial)
    outras_filiais = sorted(set(por_loja_bruto) - {loja.filial})
    if outras_filiais:
        log.warning(
            "Segmento %s (filial %s) trouxe contatos de outras filiais no export: %s "
            "- isso indica que o segmento nao esta 100%% escopado so a essa loja.",
            loja.nome_segmento_base, loja.filial, outras_filiais,
        )

    por_loja: dict[str, list[dict]] = {}
    excluidos_opt_out: dict[str, int] = {}
    for codigo, linhas in por_loja_bruto.items():
        filtradas, excluidas = _filtrar_opt_out(linhas)
        por_loja[codigo] = filtradas
        if excluidas:
            excluidos_opt_out[codigo] = excluidas

    resultado: dict[str, Any] = {
        "filial": loja.filial,
        "ok": True,
        "segmento_id": segmento_id,
        "grupos_no_export": {k: len(v) for k, v in por_loja.items()},
        "excluidos_opt_out": excluidos_opt_out or None,
        "aviso_outras_filiais": outras_filiais or None,
        "dry_run": dry_run,
        "baixar_arquivo": baixar_arquivo,
        "envios": [],
    }

    if baixar_arquivo:
        # So gera os bytes do CSV em memoria, nunca escreve em disco no
        # servidor - quem baixa o arquivo e o navegador do admin, direto na
        # resposta HTTP (ver endpoints /enviar/{filial} e .../coletar).
        for codigo_loja, linhas in sorted(por_loja.items()):
            if not linhas:
                resultado["envios"].append({
                    "codigo_loja": codigo_loja, "contatos": 0,
                    "arquivo_nome": None, "arquivo_base64": None,
                    "motivo": "todos os contatos dessa loja foram excluidos por opt-out",
                })
                continue
            conteudo = _csv_bytes_em_memoria(linhas)
            resultado["envios"].append({
                "codigo_loja": codigo_loja, "contatos": len(linhas),
                "arquivo_nome": _nome_arquivo_loja(codigo_loja),
                "arquivo_base64": base64.b64encode(conteudo).decode("ascii"),
            })
        return resultado

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
            if not linhas:
                resultado["envios"].append({
                    "codigo_loja": codigo_loja, "contatos": 0,
                    "destinatarios": [], "enviado": False,
                    "motivo": "todos os contatos dessa loja foram excluidos por opt-out",
                })
                continue
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


def _processar_loja(
    client: EmarsysClient,
    loja: Loja,
    *,
    campos_exportacao: list[str],
    campo_loja: str,
    campanha: str,
    dry_run: bool,
    email_teste: str,
    baixar_arquivo: bool = False,
) -> dict[str, Any]:
    """Fluxo completo e sincrono (acha segmento -> exporta -> espera ficar
    pronto -> divide -> envia) para uma loja - usado por /enviar/{filial} e
    /enviar-todas. Para o fluxo em duas fases (iniciar-todas/coletar), veja
    `_resolver_segmento_id` + `client.iniciar_export`/`verificar_export` +
    `_dividir_e_enviar` chamados separadamente."""
    segmento_id, erro = _resolver_segmento_id(client, loja)
    if erro:
        return {"filial": loja.filial, "ok": False, "erro": erro}

    try:
        csv_bytes = client.export_segment(segmento_id, campos_exportacao)
    except EmarsysError as exc:
        return {"filial": loja.filial, "ok": False, "erro": f"Falha ao exportar segmento: {exc}"}

    return _dividir_e_enviar(
        loja, csv_bytes,
        segmento_id=segmento_id, campo_loja=campo_loja,
        campanha=campanha, dry_run=dry_run, email_teste=email_teste,
        baixar_arquivo=baixar_arquivo,
    )


@router.post("/enviar/{filial}")
def enviar_uma_loja(
    filial: str,
    request: Request,
    campanha: str = Query(default=""),
    campos: str = Query(default=CAMPOS_PADRAO, description="IDs NUMERICOS de campo da Emarsys a exportar, separados por virgula - padrao ja cobre nome/email/telefone/loja; opt-out e SuperVIP sao sempre adicionados por baixo dos panos"),
    campo_loja: str = Query(default=CAMPO_LOJA_EXPORT, description="Nome da coluna de loja no CSV exportado - so tem efeito se o ID numerico do campo correspondente tambem estiver em 'campos'; senao o export inteiro conta como da filial pedida"),
    dry_run: bool = Query(default=True, description="true (padrao) = simula sem enviar e-mail nenhum"),
    email_teste: str = Query(default="", description="Se definido, envia so para este endereco em vez do gerente/subgerente real"),
    baixar_arquivo: bool = Query(default=False, description="Se true, NAO envia e-mail nenhum (ignora dry_run/email_teste) - so devolve o CSV em base64 pro navegador baixar"),
) -> dict[str, Any]:
    require_admin(request)
    try:
        loja = obter_loja(filial)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    campos_exportacao = _com_campos_obrigatorios([c.strip() for c in campos.split(",") if c.strip()])
    client = _get_client()
    try:
        return _processar_loja(
            client, loja,
            campos_exportacao=campos_exportacao, campo_loja=campo_loja,
            campanha=campanha, dry_run=dry_run, email_teste=email_teste,
            baixar_arquivo=baixar_arquivo,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao processar loja {filial}: {exc}") from exc


@router.post("/enviar-todas")
def enviar_todas_lojas(
    request: Request,
    campanha: str = Query(default=""),
    campos: str = Query(default=CAMPOS_PADRAO),
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

    campos_exportacao = _com_campos_obrigatorios([c.strip() for c in campos.split(",") if c.strip()])
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


# ---------------------------------------------------------------------------
# Fluxo em duas fases (iniciar todas / coletar todas) - resolve o problema de
# tempo de exportacao muito variavel entre lojas (algumas com poucos
# contatos, outras com milhares): em vez de UMA requisicao serial esperando
# cada loja terminar (o que /enviar-todas faz), aqui o admin primeiro dispara
# o export de todas de uma vez (rapido, so o POST) e recebe um "lote" com o
# export_id de cada loja; depois chama /coletar passando esse lote de volta,
# quantas vezes for preciso, ate todas saírem de "pendente".
# ---------------------------------------------------------------------------

class ItemLote(BaseModel):
    # coerce_numbers_to_str: a Emarsys devolve export_id como numero (int) -
    # sem isso, o Pydantic v2 rejeita com 422 (numero != string, mais
    # estrito que o v1) mesmo com o campo tipado como str.
    model_config = ConfigDict(coerce_numbers_to_str=True)

    filial: str
    segmento_id: str
    export_id: str


class ColetarBody(BaseModel):
    lote: list[ItemLote]


@router.post("/enviar-todas/iniciar")
def iniciar_todas_lojas(
    request: Request,
    campos: str = Query(default=CAMPOS_PADRAO, description="IDs NUMERICOS de campo da Emarsys a exportar, separados por virgula - os mesmos que serao usados depois em /coletar"),
) -> dict[str, Any]:
    """Fase 1: acha o segmento e dispara o export (POST /export/filter) de
    TODAS as lojas, sem esperar nenhum ficar pronto. Devolve o 'lote' que
    deve ser guardado (pelo chamador) e reenviado para /enviar-todas/coletar
    depois - nao ha estado guardado no servidor entre as duas chamadas."""
    require_admin(request)
    campos_exportacao = _com_campos_obrigatorios([c.strip() for c in campos.split(",") if c.strip()])
    client = _get_client()
    mapa = carregar_mapa()

    lote: list[dict[str, Any]] = []
    falhas: list[dict[str, Any]] = []
    for loja in mapa.values():
        segmento_id, erro = _resolver_segmento_id(client, loja)
        if erro:
            falhas.append({"filial": loja.filial, "ok": False, "erro": erro})
            continue
        try:
            export_id = client.iniciar_export(segmento_id, campos_exportacao)
        except EmarsysError as exc:
            falhas.append({"filial": loja.filial, "ok": False, "erro": f"Falha ao disparar exportacao: {exc}"})
            continue
        lote.append({"filial": loja.filial, "segmento_id": segmento_id, "export_id": export_id})

    return {
        "total_lojas": len(mapa),
        "iniciados": len(lote),
        "falhas": len(falhas),
        "lote": lote,
        "erros": falhas,
    }


@router.post("/enviar-todas/coletar")
def coletar_todas_lojas(
    body: ColetarBody,
    request: Request,
    campanha: str = Query(default=""),
    campo_loja: str = Query(default=CAMPO_LOJA_EXPORT, description="Nome da coluna de loja no CSV exportado - so tem efeito se o ID numerico do campo correspondente tambem estiver em 'campos'; senao o export inteiro conta como da filial pedida"),
    dry_run: bool = Query(default=True, description="true (padrao) = simula sem enviar e-mail nenhum"),
    confirmar: bool = Query(default=False, description="precisa ser true (alem de dry_run=false) para disparar envio real em massa"),
    email_teste: str = Query(default="", description="Se definido, envia so para este endereco em vez do gerente/subgerente real"),
    baixar_arquivo: bool = Query(default=False, description="Se true, NAO envia e-mail nenhum (ignora dry_run/confirmar/email_teste) - so devolve os CSVs em base64 pro navegador baixar"),
) -> dict[str, Any]:
    """Fase 2: recebe de volta o 'lote' devolvido por /enviar-todas/iniciar
    e, para cada item, checa o status UMA vez (sem esperar/repetir polling).
    As que ja estao prontas (tem file_name): baixa, divide, envia (ou
    simula). As que ainda nao: marca como 'pendente' para o admin rodar
    /coletar de novo mais tarde com o MESMO lote (so reenviando os itens
    ainda pendentes evita repetir o envio dos que ja foram concluidos)."""
    require_admin(request)
    if not baixar_arquivo and not dry_run and not confirmar:
        raise HTTPException(
            status_code=400,
            detail="Envio em massa real exige dry_run=false E confirmar=true explicitos.",
        )

    client = _get_client()
    resultados = []
    for item in body.lote:
        if not baixar_arquivo and not dry_run and item.export_id in _exports_ja_enviados:
            resultados.append({
                "filial": item.filial, "ok": True, "ja_enviado": True,
                "envios": [],
            })
            continue

        try:
            loja = obter_loja(item.filial)
        except KeyError as exc:
            resultados.append({"filial": item.filial, "ok": False, "erro": str(exc)})
            continue

        try:
            status_data = client.verificar_export(item.export_id)
        except EmarsysError as exc:
            resultados.append({"filial": item.filial, "ok": False, "erro": f"Falha ao checar status: {exc}"})
            continue

        status_atual = str(status_data.get("status", "")).strip().lower()
        if status_atual in ("error", "failed", "falhou"):
            resultados.append({"filial": item.filial, "ok": False, "erro": f"Exportacao falhou: {status_data}"})
            continue

        file_name = status_data.get("file_name")
        if not file_name:
            resultados.append({
                "filial": item.filial, "ok": False, "pendente": True,
                "status_atual": status_atual or "desconhecido",
            })
            continue

        try:
            csv_bytes = client.baixar_export(file_name)
        except EmarsysError as exc:
            resultados.append({"filial": item.filial, "ok": False, "erro": f"Falha ao baixar export: {exc}"})
            continue

        resultado_loja = _dividir_e_enviar(
            loja, csv_bytes,
            segmento_id=item.segmento_id, campo_loja=campo_loja,
            campanha=campanha, dry_run=dry_run, email_teste=email_teste,
            baixar_arquivo=baixar_arquivo,
        )
        algum_email_enviado = any(e.get("enviado") for e in resultado_loja.get("envios", []))
        if not baixar_arquivo and not dry_run and algum_email_enviado:
            # Marca como enviado se PELO MENOS um e-mail de verdade saiu -
            # "ok" sozinho nao serve (fica True mesmo se todo envio de
            # e-mail falhar, ja que so descreve o split ter funcionado).
            _exports_ja_enviados.add(item.export_id)
        resultados.append(resultado_loja)

    return {
        "dry_run": dry_run,
        "total": len(resultados),
        "sucesso": sum(1 for r in resultados if r.get("ok")),
        "pendente": sum(1 for r in resultados if r.get("pendente")),
        "falha": sum(1 for r in resultados if not r.get("ok") and not r.get("pendente")),
        "resultados": resultados,
    }

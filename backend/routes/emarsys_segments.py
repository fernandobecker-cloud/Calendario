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
from backend.routes.open_data import (
    _normalize_match_key,
    automation_node_diagnostico,
    disparos_reais_por_cpfs,
    receita_atribuida_por_cpfs,
    receita_pos_disparo_por_cpfs,
)

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
    offset: int = Query(default=0, ge=0, description="Indice da loja onde comecar - fluxo em lotes, pra nao estourar o timeout do proxy processando as ~89 lojas numa unica chamada"),
    limite: int = Query(default=10, ge=1, le=89, description="Quantas lojas processar nesta chamada"),
) -> dict[str, Any]:
    """Fase 1: acha o segmento e dispara o export (POST /export/filter) de
    um LOTE de lojas por vez (nao todas de uma vez - processar as ~89 numa
    unica requisicao demora minutos e o proxy do Render derruba a conexao
    com 502 antes de terminar), sem esperar nenhuma ficar pronta. Quem
    chama deve repetir com `offset=proximo_offset` ate ele vir None,
    acumulando 'lote' e 'erros' de cada chamada - o que sera reenviado
    para /enviar-todas/coletar no final. Nao ha estado guardado no
    servidor entre chamadas."""
    require_admin(request)
    campos_exportacao = _com_campos_obrigatorios([c.strip() for c in campos.split(",") if c.strip()])
    client = _get_client()
    lojas_lista = list(carregar_mapa().values())
    total = len(lojas_lista)
    fatia = lojas_lista[offset:offset + limite]

    lote: list[dict[str, Any]] = []
    falhas: list[dict[str, Any]] = []
    for loja in fatia:
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

    proximo_offset = offset + limite
    return {
        "total_lojas": total,
        "offset": offset,
        "processados_nesta_chamada": len(fatia),
        "proximo_offset": proximo_offset if proximo_offset < total else None,
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


# ---------------------------------------------------------------------------
# Export de um segmento qualquer, por ID direto - nao precisa estar mapeado
# numa loja. Usado pra consultas pontuais (ex: cruzar uma lista de clientes
# de outra ferramenta, como uma campanha de WhatsApp feita fora da Emarsys,
# com a Base de Vendas).
# ---------------------------------------------------------------------------

@router.post("/segmento/{segmento_id}/exportar")
def exportar_segmento_generico(
    segmento_id: str,
    request: Request,
    campos: str = Query(default=CAMPOS_PADRAO, description="IDs NUMERICOS de campo da Emarsys a exportar, separados por virgula"),
    baixar_arquivo: bool = Query(default=False, description="Se true, tambem devolve o CSV inteiro em base64 pro navegador baixar"),
) -> dict[str, Any]:
    """Exporta um segmento pelo ID, sem precisar de mapeamento de loja.
    Devolve as colunas e uma amostra das primeiras linhas (pra conferir o que
    veio sem precisar decodificar nada), e opcionalmente o CSV inteiro."""
    require_admin(request)
    client = _get_client()
    try:
        segmento = client.get_segment_by_id(segmento_id)
    except EmarsysError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar segmento {segmento_id}: {exc}") from exc
    if not segmento:
        raise HTTPException(status_code=404, detail=f"Segmento {segmento_id} nao encontrado.")

    campos_exportacao = [c.strip() for c in campos.split(",") if c.strip()]
    try:
        csv_bytes = client.export_segment(segmento_id, campos_exportacao)
    except EmarsysError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao exportar segmento {segmento_id}: {exc}") from exc

    texto = csv_bytes.decode("utf-8-sig")
    leitor = csv.DictReader(io.StringIO(texto))
    linhas = list(leitor)

    resultado: dict[str, Any] = {
        "segmento_id": segmento_id,
        "segmento_nome": segmento.get("name"),
        "segmento_tipo": segmento.get("type"),
        "colunas": leitor.fieldnames,
        "total_contatos": len(linhas),
        "amostra": linhas[:5],
    }
    if baixar_arquivo:
        resultado["arquivo_nome"] = f"segmento_{segmento_id}.csv"
        resultado["arquivo_base64"] = base64.b64encode(csv_bytes).decode("ascii")
    return resultado


# ---------------------------------------------------------------------------
# Receita atribuida para os contatos de um segmento - usado para segmentos
# que viraram audiencia em outra ferramenta (ex: uma campanha de WhatsApp
# disparada pelo Omnichat). Exporta so o CPF (campo 12908, confirmado pelo
# usuario) e cruza com si_purchases/revenue_attribution no BigQuery - nunca
# usa telefone, que nao existe no Open Data (ver backend/routes/open_data.py).
#
# Duas metricas, propositalmente separadas:
# - `receita_pos_disparo` (o que interessa de verdade aqui): comprou algo
#   entre a data do disparo e o fim da janela, sem depender de qual canal (ou
#   nenhum) a Emarsys credita internamente - ela nao enxerga o Omnichat, entao
#   e a unica forma de medir esse disparo.
# - `atribuicao_nativa_emarsys`: o que o modelo de atribuicao por canal da
#   propria Emarsys (revenue_attribution) credita pra esses contatos no mesmo
#   periodo - mantido so como contexto/comparacao, NAO mede o Omnichat (so
#   canais que a Emarsys mesma dispara: email, SMS, WhatsApp nativo dela).
#
# LIMITACAO: um segmento estatico (ex: "recebeu WPP de 12 a 16/09") junta
# disparos de dias/campanhas diferentes numa lista so - por isso o endpoint
# abaixo pede UM `data_disparo` unico pro segmento inteiro, o que so e
# preciso se o segmento de fato corresponder a um unico dia/disparo. Pra
# descobrir a data REAL de cada contato (quando o segmento junta varios
# dias), ver `/segmento/{id}/disparos-reais` mais abaixo.
# ---------------------------------------------------------------------------

def _exportar_cpfs_do_segmento(client: EmarsysClient, segmento_id: str, campo_cpf: str) -> tuple[dict, list[str], int]:
    """Busca o segmento, exporta so o campo de CPF e devolve
    (segmento, cpfs_normalizados, total_contatos_no_csv) - logica comum aos
    endpoints de receita-atribuida e disparos-reais, que partem do mesmo
    export de segmento."""
    try:
        segmento = client.get_segment_by_id(segmento_id)
    except EmarsysError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar segmento {segmento_id}: {exc}") from exc
    if not segmento:
        raise HTTPException(status_code=404, detail=f"Segmento {segmento_id} nao encontrado.")

    try:
        csv_bytes = client.export_segment(segmento_id, [campo_cpf.strip()])
    except EmarsysError as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao exportar segmento {segmento_id}: {exc}") from exc

    texto = csv_bytes.decode("utf-8-sig")
    leitor = csv.DictReader(io.StringIO(texto))
    linhas = list(leitor)
    colunas = leitor.fieldnames or []

    coluna_cpf = colunas[0] if len(colunas) == 1 else next(
        (c for c in colunas if "cpf" in c.strip().lower()), None
    )
    if not coluna_cpf:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Nao consegui identificar a coluna de CPF no export do segmento {segmento_id} "
                f"(colunas recebidas: {colunas}). Confira o ID do campo ({campo_cpf}) na tela "
                "de campos da Emarsys."
            ),
        )

    cpfs_normalizados = [_normalize_match_key(linha.get(coluna_cpf) or "") for linha in linhas]
    return segmento, cpfs_normalizados, len(linhas)


@router.post("/segmento/{segmento_id}/receita-atribuida")
def receita_atribuida_segmento(
    segmento_id: str,
    request: Request,
    data_disparo: str = Query(pattern=r"^\d{4}-\d{2}-\d{2}$", description="Data em que o disparo foi feito (ex: no Omnichat), YYYY-MM-DD"),
    janela_dias: int = Query(default=7, ge=1, le=60, description="Quantos dias apos o disparo contam como janela de atribuicao"),
    campanha: str = Query(default="", description="Nome da campanha/disparo, so para identificar o resultado - nao afeta a consulta"),
    skus: str = Query(default="", description="SKUs (product_external_id) do produto promovido, separados por virgula - filtra a metrica 'npi'. Vazio = usa a lista padrao do lancamento iPhone 18 (VENDAS_NPI_SKUS)"),
    campo_cpf: str = Query(default="12908", description="ID numerico do campo de CPF na Emarsys"),
) -> dict[str, Any]:
    """Pega os contatos de um segmento da Emarsys (ex: a audiencia usada para
    montar um disparo de WhatsApp em outra ferramenta, como o Omnichat),
    exporta so o CPF de cada um e mede quantos compraram (e quanto) entre a
    data do disparo e o fim da janela - direto em `si_purchases`, sem
    depender do modelo de atribuicao por canal da Emarsys (que nao enxerga
    disparos feitos fora dela). Devolve receita 'total' (qualquer compra -
    teto superior) e 'npi' (so os SKUs do produto promovido - proxy mais
    proxima do efeito real). Tambem devolve, so como contexto, o que a
    atribuicao nativa da Emarsys credita pra esses contatos no mesmo
    periodo. O cruzamento e 100% por CPF - telefone nunca entra nessa conta,
    porque nao existe no Open Data."""
    require_admin(request)
    client = _get_client()
    segmento, cpfs_normalizados, total_contatos_segmento = _exportar_cpfs_do_segmento(client, segmento_id, campo_cpf)

    skus_campanha = [s.strip() for s in skus.split(",") if s.strip()] or None

    try:
        pos_disparo = receita_pos_disparo_por_cpfs(cpfs_normalizados, data_disparo, janela_dias, skus_campanha)
        nativo = receita_atribuida_por_cpfs(cpfs_normalizados, data_disparo, pos_disparo["fim_janela"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao calcular receita: {exc}") from exc

    return {
        "segmento_id": segmento_id,
        "segmento_nome": segmento.get("name"),
        "campanha": campanha or None,
        "total_contatos_segmento": total_contatos_segmento,
        "total_cpfs_informados": pos_disparo["total_cpfs_informados"],
        "data_disparo": pos_disparo["data_disparo"],
        "janela_dias": pos_disparo["janela_dias"],
        "fim_janela": pos_disparo["fim_janela"],
        "skus_campanha": pos_disparo["skus_campanha"],
        "receita_pos_disparo": {
            "total": pos_disparo["total"],
            "npi": pos_disparo["npi"],
            "metric_definition": pos_disparo["metric_definition"],
        },
        "atribuicao_nativa_emarsys": {
            "nota": (
                "Isto NAO mede o Omnichat - a Emarsys so credita canais que ela "
                "mesma dispara (email, SMS, WhatsApp nativo dela). Mantido aqui "
                "so como contexto/comparacao com receita_pos_disparo."
            ),
            "total_cpfs_encontrados_emarsys": nativo["total_cpfs_encontrados_emarsys"],
            "taxa_match_pct": nativo["taxa_match_pct"],
            "by_channel": nativo["by_channel"],
            "total_pedidos_atribuidos": nativo["total_pedidos_atribuidos"],
            "total_receita_atribuida": nativo["total_receita_atribuida"],
        },
    }


# ---------------------------------------------------------------------------
# Diagnostico: descobre se um disparo de WhatsApp esta rastreado por contato
# em `conversation_sends`/`conversation_messages` (o mesmo par de tabelas do
# `/whatsapp-apuracao` existente) - se sim, devolve a data REAL de envio de
# cada combinacao (message_id, dia), em vez de depender de um unico
# `data_disparo` informado manualmente pro segmento inteiro. Util quando o
# segmento e estatico e junta disparos de dias diferentes (ex: "recebeu WPP
# de 12 a 16/09").
# ---------------------------------------------------------------------------

@router.post("/segmento/{segmento_id}/disparos-reais")
def disparos_reais_segmento(
    segmento_id: str,
    request: Request,
    nome_campanha: str = Query(min_length=2, description="Trecho do nome da campanha em conversation_messages.name (LIKE, sem diferenciar maiusculas)"),
    campo_cpf: str = Query(default="12908", description="ID numerico do campo de CPF na Emarsys"),
) -> dict[str, Any]:
    """Pega os contatos de um segmento, exporta o CPF de cada um e verifica
    se aparecem em `conversation_sends` para alguma `conversation_messages`
    cujo nome bata com `nome_campanha` - se aparecerem, devolve por
    (message_id, data_envio) quantos CPFs do segmento receberam naquele dia
    especificamente. Isso permite tratar cada contato com a data de disparo
    dele mesmo, em vez de uma data unica pro segmento inteiro - use isso
    antes de rodar `/receita-atribuida` num segmento que junta varios dias."""
    require_admin(request)
    client = _get_client()
    segmento, cpfs_normalizados, total_contatos_segmento = _exportar_cpfs_do_segmento(client, segmento_id, campo_cpf)

    try:
        resultado = disparos_reais_por_cpfs(cpfs_normalizados, nome_campanha)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar disparos reais: {exc}") from exc

    resultado["segmento_id"] = segmento_id
    resultado["segmento_nome"] = segmento.get("name")
    resultado["total_contatos_segmento"] = total_contatos_segmento
    return resultado


# ---------------------------------------------------------------------------
# Diagnostico de automacao (Automation Center classico) - quando o disparo
# sai por um node de webhook (ex: chamando o Omnichat) em vez do canal
# nativo de WhatsApp da Emarsys, ele nao aparece em conversation_sends (ver
# `/disparos-reais` acima). Esse endpoint olha `automation_node_executions`
# direto pelo ac_program_id (numero depois de "/edit/ac/" na URL do
# Emarsys), sem precisar do segmento/CPF - so pra descobrir QUAIS nodes
# existem, quantas execucoes cada um teve, quando, e o formato real do
# campo `participants` (via JSON de exemplo, sem adivinhar nome de campo).
# ---------------------------------------------------------------------------

@router.get("/automation/{ac_program_id}/diagnostico")
def automation_diagnostico(ac_program_id: str, request: Request) -> dict[str, Any]:
    """Resume `automation_node_executions` para um programa da Automation
    Center classica: por (node_id, execution_phase), quantas linhas,
    primeiro/ultimo evento, e um JSON de exemplo do participante - usado
    pra achar o node_id certo (ex: o node que chama o webhook do Omnichat)
    e o nome do campo de contato dentro de `participants`, antes de montar
    uma consulta de cruzamento CPF x execucao do node."""
    require_admin(request)
    try:
        return automation_node_diagnostico(ac_program_id.strip())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar automation_node_executions: {exc}") from exc

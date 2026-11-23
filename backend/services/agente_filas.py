"""Filas de atendimento das lojas e do televendas na Omnichat.

A Omnichat manda os eventos de atendimento (chat-routed, chat-finished) para a
API do agente, que repassa em lotes para o portal (POST /api/agente-ia/fila/eventos).
Aqui cada lote:
  - entra na memória (eventos das últimas _JANELA_H horas), de onde o painel é
    calculado sem consultar o BigQuery a cada atualização;
  - é gravado no BigQuery (portal_crm.agente_fila_eventos, partição por dia)
    para o histórico. Só no primeiro uso depois de um reinício o portal lê o
    BigQuery, para recuperar as últimas horas.

Só entram no painel os times de loja (o número da filial no nome do time na
Omnichat, ex.: "AT638 | FORTALEZA" -> filial 638, casado com
backend/data/mapeamento_lojas_sap.csv) e o time do televendas escolhido no
painel Televendas. Assistência e outros times ficam de fora.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from backend.services import agente_televendas
from backend.services.agente_planilha import PlanilhaErroBQ, _DATASET, _PROJECT_ID, _cliente
from backend.services.mapa_lojas import carregar_mapa

log = logging.getLogger(__name__)

_TABELA = "agente_fila_eventos"
_TIMEOUT_S = 60
_JANELA_H = 26  # o dia de hoje + folga para quem entrou na fila antes da meia-noite
ESPERA_MAX_H = 2  # espera mais longa que isso é evento perdido: sai da fila
FUSO = ZoneInfo("America/Sao_Paulo")
_RE_FILIAL = re.compile(r"^\s*[A-Za-z]*\s*0*(\d{2,4})\b")

_SCHEMA = [
    bigquery.SchemaField("trace_id", "STRING"),
    bigquery.SchemaField("tipo", "STRING"),
    bigquery.SchemaField("momento", "TIMESTAMP"),
    bigquery.SchemaField("atendimento_id", "STRING"),
    bigquery.SchemaField("para_tipo", "STRING"),
    bigquery.SchemaField("para_id", "STRING"),
    bigquery.SchemaField("para_nome", "STRING"),
    bigquery.SchemaField("de_tipo", "STRING"),
    bigquery.SchemaField("por_id", "STRING"),
    bigquery.SchemaField("por_nome", "STRING"),
    bigquery.SchemaField("motivo_encerramento", "STRING"),
    bigquery.SchemaField("plataforma", "STRING"),
    bigquery.SchemaField("recebido_em", "TIMESTAMP"),
    # Colunas novas (a tabela ganha as que faltarem no primeiro uso):
    bigquery.SchemaField("conversa_id", "STRING"),  # hash do telefone, liga entrada e saída da fila
    bigquery.SchemaField("por_usuario_tipo", "STRING"),  # routedBy.userType: quem encaminhou (bot, usuário...)
    bigquery.SchemaField("rota_tipo", "STRING"),
    bigquery.SchemaField("origem", "STRING"),
    # Registros "omni-interacao" (API v1 da Omnichat, consultada pela API do agente):
    bigquery.SchemaField("interacao_status", "STRING"),
    bigquery.SchemaField("contatado_em", "TIMESTAMP"),  # vendedor clicou em "Assumir atendimento"
    bigquery.SchemaField("contatado_por", "STRING"),
    bigquery.SchemaField("encaminhado_em", "TIMESTAMP"),
    bigquery.SchemaField("origem_id", "STRING"),  # ex.: 20261123_WMKT_Whizz
    bigquery.SchemaField("origem_canal", "STRING"),
    bigquery.SchemaField("origem_tipo", "STRING"),
    bigquery.SchemaField("origem_url", "STRING"),
    # Resposta de campanha (webhook message-replies):
    bigquery.SchemaField("campanha_id", "STRING"),
    bigquery.SchemaField("campanha_nome", "STRING"),
]
# Quem respondeu a uma campanha e caiu na fila de uma loja até este tempo depois conta como campanha.
CAMPANHA_JANELA_H = 24
_CAMPOS = [c.name for c in _SCHEMA]

_lock = threading.Lock()
# Últimos eventos completos (sem telefone) para o diagnóstico; só em memória.
_brutos: deque = deque(maxlen=40)
_estado: dict[str, Any] = {"carregado": False, "tentou_em": -1e9, "tabela_ok": False, "eventos": [], "traces": set()}


def _tabela_id() -> str:
    if not _PROJECT_ID:
        raise PlanilhaErroBQ("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"{_PROJECT_ID}.{_DATASET}.{_TABELA}"


def _momento(valor: Any) -> datetime | None:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _garantir_tabela() -> None:
    if _estado["tabela_ok"]:
        return
    tabela = bigquery.Table(_tabela_id(), schema=_SCHEMA)
    tabela.time_partitioning = bigquery.TimePartitioning(type_=bigquery.TimePartitioningType.DAY, field="momento")
    cliente = _cliente()
    tabela = cliente.create_table(tabela, exists_ok=True, timeout=_TIMEOUT_S)
    existentes = {c.name for c in tabela.schema}
    faltando = [c for c in _SCHEMA if c.name not in existentes]
    if faltando:
        tabela.schema = list(tabela.schema) + faltando
        cliente.update_table(tabela, ["schema"], timeout=_TIMEOUT_S)
    _estado["tabela_ok"] = True


def _carregar_recentes() -> None:
    """Uma vez por reinício do portal: as últimas horas do BigQuery para a memória."""
    if _estado["carregado"] or time.monotonic() - _estado["tentou_em"] < 300:
        return
    _estado["tentou_em"] = time.monotonic()
    try:
        _garantir_tabela()  # as colunas novas precisam existir antes do SELECT
    except PlanilhaErroBQ:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("filas: nao consegui conferir a tabela no BigQuery: %s", exc)
        return
    desde = datetime.now(timezone.utc) - timedelta(hours=_JANELA_H)
    sql = (
        f"SELECT {', '.join(_CAMPOS)} FROM `{_tabela_id()}` "
        "WHERE momento >= @desde ORDER BY momento"
    )
    config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("desde", "TIMESTAMP", desde)])
    try:
        linhas = list(_cliente().query(sql, job_config=config).result(timeout=_TIMEOUT_S))
    except NotFound:
        linhas = []
    except PlanilhaErroBQ:
        raise
    except Exception as exc:  # noqa: BLE001
        log.warning("filas: nao consegui ler o historico recente do BigQuery: %s", exc)
        return  # tenta de novo na proxima vez; o painel segue com o que chegar
    for row in linhas:
        evento = dict(row.items())
        if evento["trace_id"] not in _estado["traces"]:
            _estado["traces"].add(evento["trace_id"])
            _estado["eventos"].append(evento)
    _estado["eventos"].sort(key=lambda e: e["momento"])
    _estado["carregado"] = True


def _limpar_memoria() -> None:
    limite = datetime.now(timezone.utc) - timedelta(hours=_JANELA_H)
    antigos = [e for e in _estado["eventos"] if e["momento"] < limite]
    if antigos:
        _estado["eventos"] = [e for e in _estado["eventos"] if e["momento"] >= limite]
        for e in antigos:
            _estado["traces"].discard(e["trace_id"])


def receber(eventos: list[dict[str, Any]]) -> dict[str, int]:
    """Lote vindo da API do agente: memória + BigQuery (sem repetir trace_id)."""
    agora = datetime.now(timezone.utc)
    novos = []
    with _lock:
        try:
            _carregar_recentes()
        except PlanilhaErroBQ as exc:
            log.warning("filas: %s", exc)
        for bruto in eventos:
            if not isinstance(bruto, dict) or not bruto.get("trace_id"):
                continue
            if isinstance(bruto.get("bruto"), dict):
                _brutos.append({"recebido_em": agora.astimezone(FUSO).isoformat(), "evento": bruto["bruto"]})
            momento = _momento(bruto.get("momento")) or agora
            evento = {c: (str(bruto[c]) if bruto.get(c) is not None else None) for c in _CAMPOS}
            evento.update(momento=momento, recebido_em=agora)
            if evento["trace_id"] in _estado["traces"]:
                continue
            _estado["traces"].add(evento["trace_id"])
            _estado["eventos"].append(evento)
            novos.append(evento)
        _estado["eventos"].sort(key=lambda e: e["momento"])
        _limpar_memoria()
    if novos:
        registros = [{**e, "momento": e["momento"].isoformat(), "recebido_em": e["recebido_em"].isoformat()}
                     for e in novos]
        try:
            _garantir_tabela()
            erros = _cliente().insert_rows_json(_tabela_id(), registros, row_ids=[e["trace_id"] for e in novos],
                                                timeout=_TIMEOUT_S)
            if erros:
                log.warning("filas: BigQuery recusou %s linha(s): %s", len(erros), erros[:3])
        except Exception as exc:  # noqa: BLE001 - o painel segue em memória mesmo sem gravar
            log.warning("filas: nao consegui gravar %s evento(s) no BigQuery: %s", len(novos), exc)
    return {"recebidos": len(eventos), "novos": len(novos)}


# --- Painel ---------------------------------------------------------------------


def filial_do_time(nome: str | None) -> str | None:
    achou = _RE_FILIAL.match(nome or "")
    return achou.group(1) if achou else None


def _minutos(segundos: list[float]) -> float | None:
    return round(sum(segundos) / len(segundos) / 60, 1) if segundos else None


def _novo_contador() -> dict[str, Any]:
    return {"na_fila": 0, "espera_mais_antiga_min": 0.0, "entraram_hoje": 0, "atendidos_hoje": 0,
            "sem_atendimento_hoje": 0, "entraram_campanha": 0, "entraram_organico": 0,
            "campanhas": {}, "_esperas": [], "_duracoes": []}


def rotulo_origem(e: dict[str, Any]) -> str:
    """Origem do atendimento vinda da API da Omnichat, em texto (para o diagnóstico)."""
    partes = [e.get("origem_tipo"), e.get("origem_canal"), e.get("origem_id"), e.get("origem_url")]
    return " · ".join(str(p) for p in partes if p) or "(sem origem: orgânico)"


def classe_origem(e: dict[str, Any]) -> str:
    """campanha ou organico. Sem origem preenchida = orgânico (veio direto pelo WhatsApp)."""
    texto = rotulo_origem(e).lower()
    if "sem origem" in texto or "organ" in texto:
        return "organico"
    return "campanha"


# Destinos que tiram o cliente da fila sem ser um vendedor pegando o atendimento.
_DESTINOS_BOT = ("BOT", "FLOW", "CHATBOT", "BOTFLOW")


def calcular(eventos: list[dict[str, Any]], agora: datetime,
             saidas: dict[str, int] | None = None) -> dict[str, dict[str, Any]]:
    """Repassa os eventos em ordem e devolve os números de cada time (por id do time).

    Um atendimento roteado para um TIME entra na fila daquele time; quando vai
    para um atendente (USER ou outro destino que não seja bot), sai da fila e
    conta como atendido (espera = tempo entre os dois); encerrado ainda na fila
    conta como "saiu sem atendimento". O atendimento é seguido pela conversa
    (hash do telefone), porque o objectId pode mudar quando o vendedor pega.
    Em `saidas` (opcional) fica a contagem de como cada um saiu da fila.
    """
    saidas = saidas if saidas is not None else {}
    # Origem de cada atendimento (registros da API da Omnichat), pelo objectId do webhook.
    origem_de: dict[str, str] = {}
    for e in eventos:
        if e.get("tipo") == "omni-interacao" and e.get("atendimento_id"):
            origem_de[e["atendimento_id"]] = classe_origem(e)
    # Respostas de campanha (message-replies) por conversa: só classifica quando o evento está ligado.
    com_respostas = any(e.get("tipo") == "message-replies" for e in eventos)
    respondeu: dict[str, tuple[datetime, str]] = {}
    janela = timedelta(hours=CAMPANHA_JANELA_H)
    inicio_dia = agora.astimezone(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    por_time: dict[str, dict[str, Any]] = {}
    nomes: dict[str, str] = {}
    situacao: dict[str, dict[str, Any]] = {}  # atendimento -> {time, fila: bool, desde}

    def time_de(time_id: str) -> dict[str, Any]:
        return por_time.setdefault(time_id, _novo_contador())

    for e in eventos:
        at = e.get("conversa_id") or e.get("atendimento_id")
        if not at:
            continue
        momento = e["momento"]
        hoje = momento >= inicio_dia
        atual = situacao.get(at)
        if e.get("tipo") == "message-replies":
            respondeu[at] = (momento, e.get("campanha_nome") or e.get("campanha_id") or "(campanha sem nome)")
            continue
        if e.get("tipo") == "chat-routed":
            para = (e.get("para_tipo") or "").upper()
            if para == "TEAM" and e.get("para_id"):
                if e.get("para_nome"):
                    nomes[e["para_id"]] = e["para_nome"]
                situacao[at] = {"time": e["para_id"], "fila": True, "desde": momento}
                if hoje:
                    cont = time_de(e["para_id"])
                    cont["entraram_hoje"] += 1
                    classe = origem_de.get(e.get("atendimento_id") or "")
                    resposta = respondeu.get(at)
                    if resposta and timedelta(0) <= momento - resposta[0] <= janela:
                        classe = "campanha"
                        cont["campanhas"][resposta[1]] = cont["campanhas"].get(resposta[1], 0) + 1
                    elif not classe and com_respostas:
                        classe = "organico"
                    if classe:
                        cont[f"entraram_{classe}"] += 1
            elif para and not any(b in para for b in _DESTINOS_BOT):
                if atual and atual["fila"]:
                    saidas[f"atendido ({para})"] = saidas.get(f"atendido ({para})", 0) + 1
                    if hoje:
                        cont = time_de(atual["time"])
                        cont["atendidos_hoje"] += 1
                        cont["_esperas"].append((momento - atual["desde"]).total_seconds())
                    situacao[at] = {"time": atual["time"], "fila": False, "desde": momento}
                # Já com atendente e indo para outro atendente: segue o mesmo atendimento.
            elif atual:
                if atual["fila"]:
                    saidas[f"voltou para bot ({para or '-'})"] = saidas.get(f"voltou para bot ({para or '-'})", 0) + 1
                situacao.pop(at, None)  # foi para um bot
        elif e.get("tipo") in ("omni-interacao", "primeira-resposta"):
            # O vendedor assumiu (o webhook não avisa o clique): primeira mensagem dele
            # (message-sent) ou contactedAt da API da Omnichat.
            pela_api = e.get("tipo") == "omni-interacao"
            if (e.get("contatado_em") or not pela_api) and atual and atual["fila"]:
                como = "atendido (assumiu, pela API)" if pela_api else "atendido (primeira mensagem do vendedor)"
                saidas[como] = saidas.get(como, 0) + 1
                if hoje:
                    cont = time_de(atual["time"])
                    cont["atendidos_hoje"] += 1
                    cont["_esperas"].append(max(0.0, (momento - atual["desde"]).total_seconds()))
                situacao[at] = {"time": atual["time"], "fila": False, "desde": momento}
        elif e.get("tipo") == "chat-finished" and atual:
            if atual["fila"]:
                saidas["encerrado na fila"] = saidas.get("encerrado na fila", 0) + 1
            if hoje:
                cont = time_de(atual["time"])
                if atual["fila"]:
                    cont["sem_atendimento_hoje"] += 1
                else:
                    cont["_duracoes"].append((momento - atual["desde"]).total_seconds())
            situacao.pop(at, None)

    limite = agora - timedelta(hours=ESPERA_MAX_H)
    for s in situacao.values():
        if s["fila"] and s["desde"] < limite:
            saidas[f"expirou (+{ESPERA_MAX_H}h sem evento)"] = saidas.get(f"expirou (+{ESPERA_MAX_H}h sem evento)", 0) + 1
        if s["fila"] and s["desde"] >= limite:
            cont = time_de(s["time"])
            cont["na_fila"] += 1
            cont["espera_mais_antiga_min"] = max(cont["espera_mais_antiga_min"],
                                                 round((agora - s["desde"]).total_seconds() / 60, 1))
    resultado = {}
    for time_id, cont in por_time.items():
        resultado[time_id] = {
            "nome": nomes.get(time_id),
            **{k: v for k, v in cont.items() if not k.startswith("_")},
            "espera_media_min": _minutos(cont["_esperas"]),
            "atendimento_medio_min": _minutos(cont["_duracoes"]),
        }
    for time_id, nome in nomes.items():
        resultado.setdefault(time_id, {"nome": nome, **{k: v for k, v in _novo_contador().items()
                                                        if not k.startswith("_")},
                                       "espera_media_min": None, "atendimento_medio_min": None})
    return resultado


def _somar(partes: list[dict[str, Any]]) -> dict[str, Any]:
    total = {"na_fila": 0, "espera_mais_antiga_min": 0.0, "entraram_hoje": 0, "atendidos_hoje": 0,
             "sem_atendimento_hoje": 0, "entraram_campanha": 0, "entraram_organico": 0, "campanhas": {}}
    esperas, duracoes = [], []
    for p in partes:
        for k in ("na_fila", "entraram_hoje", "atendidos_hoje", "sem_atendimento_hoje",
                  "entraram_campanha", "entraram_organico"):
            total[k] += p.get(k) or 0
        for nome, n in (p.get("campanhas") or {}).items():
            total["campanhas"][nome] = total["campanhas"].get(nome, 0) + n
        total["espera_mais_antiga_min"] = max(total["espera_mais_antiga_min"], p.get("espera_mais_antiga_min") or 0)
        if p.get("espera_media_min") is not None:
            esperas.append((p["espera_media_min"], p.get("atendidos_hoje") or 0))
        if p.get("atendimento_medio_min") is not None:
            duracoes.append(p["atendimento_medio_min"])
    peso = sum(n for _, n in esperas)
    total["espera_media_min"] = round(sum(m * n for m, n in esperas) / peso, 1) if peso else None
    total["atendimento_medio_min"] = round(sum(duracoes) / len(duracoes), 1) if duracoes else None
    return total


def _nome_loja(descricao: str) -> str:
    nome = re.sub(r"^\s*IPLACE\s*-\s*", "", descricao or "", flags=re.I).strip()
    return re.sub(r"\s*-\s*", " - ", nome)


def painel(com_televendas: bool = True) -> dict[str, Any]:
    """Números por loja e regional. O link dos gerentes chama sem o televendas."""
    agora = datetime.now(timezone.utc)
    with _lock:
        try:
            _carregar_recentes()
        except PlanilhaErroBQ as exc:
            log.warning("filas: %s", exc)
        eventos = list(_estado["eventos"])
    por_time = calcular(eventos, agora)

    try:
        televendas_id = (agente_televendas.carregar() or {}).get("time_id")
    except PlanilhaErroBQ:
        televendas_id = None
    televendas = None
    if televendas_id and com_televendas:
        dados = por_time.get(televendas_id)
        televendas = {**_somar([dados] if dados else []), "nome": "Televendas"}

    mapa = carregar_mapa()
    por_filial: dict[str, list[dict[str, Any]]] = {}
    for time_id, dados in por_time.items():
        filial = filial_do_time(dados.get("nome"))
        if time_id != televendas_id and filial in mapa:
            por_filial.setdefault(filial, []).append(dados)

    regionais: dict[str, dict[str, Any]] = {}
    for filial, loja in mapa.items():
        times = por_filial.get(filial, [])
        linha = {
            "filial": filial,
            "loja": _nome_loja(loja.descricao),  # nome do SAP, o mesmo do resto do portal
            "na_omnichat": bool(times),
            **_somar(times),
        }
        reg = regionais.setdefault(loja.regional or "Sem regional", {
            "regional": loja.regional or "Sem regional", "lojas": []})
        reg["lojas"].append(linha)
    lista = []
    for reg in sorted(regionais.values(), key=lambda r: r["regional"]):
        reg["lojas"].sort(key=lambda l: (-l["na_fila"], -l["espera_mais_antiga_min"], l["loja"]))
        reg["total"] = _somar(reg["lojas"])
        lista.append(reg)
    ultimo = eventos[-1]["recebido_em"] if eventos else None
    resposta = {
        "atualizado_em": agora.astimezone(FUSO).isoformat(),
        "ultimo_evento_em": ultimo.astimezone(FUSO).isoformat() if isinstance(ultimo, datetime) else None,
        "regionais": lista,
        "total_lojas": _somar([r["total"] for r in lista]),
    }
    if com_televendas:
        resposta["televendas"] = televendas
    return resposta


def diagnostico() -> dict[str, Any]:
    """Para o admin: o que chegou nas últimas horas e como cada time foi classificado."""
    with _lock:
        try:
            _carregar_recentes()
        except PlanilhaErroBQ as exc:
            log.warning("filas: %s", exc)
        eventos = list(_estado["eventos"])
    inicio_dia = datetime.now(FUSO).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        televendas_id = (agente_televendas.carregar() or {}).get("time_id")
    except PlanilhaErroBQ:
        televendas_id = None
    mapa = carregar_mapa()
    tipos: dict[str, int] = {}
    times: dict[str, dict[str, Any]] = {}
    encaminhou: dict[str, int] = {}
    origens: dict[str, int] = {}
    saidas: dict[str, int] = {}
    calcular(eventos, datetime.now(timezone.utc), saidas)
    for e in eventos:
        if e.get("tipo") == "message-replies" and e["momento"] >= inicio_dia:
            rot = f"Resposta de campanha: {e.get('campanha_nome') or e.get('campanha_id') or '(sem nome)'}"
            origens[rot] = origens.get(rot, 0) + 1
        if e.get("tipo") == "omni-interacao" and e["momento"] >= inicio_dia:
            origens[rotulo_origem(e)] = origens.get(rotulo_origem(e), 0) + 1
        chave = f"{e.get('tipo')} -> {e.get('para_tipo') or '-'}"
        tipos[chave] = tipos.get(chave, 0) + 1
        if (e.get("para_tipo") or "").upper() == "TEAM" and e.get("para_id"):
            t = times.setdefault(e["para_id"], {"id": e["para_id"], "nome": None, "eventos": 0, "hoje": 0})
            t["nome"] = e.get("para_nome") or t["nome"]
            t["eventos"] += 1
            t["hoje"] += 1 if e["momento"] >= inicio_dia else 0
            if e["momento"] >= inicio_dia and filial_do_time(e.get("para_nome")) in mapa and e["para_id"] != televendas_id:
                quem = (f"{e.get('por_nome') or '(sem nome)'} · tipo {e.get('por_usuario_tipo') or '-'}"
                        f" · rota {e.get('rota_tipo') or '-'} · vinha de {e.get('de_tipo') or '-'}")
                encaminhou[quem] = encaminhou.get(quem, 0) + 1
    for t in times.values():
        filial = filial_do_time(t["nome"])
        if t["id"] == televendas_id:
            t["classificacao"] = "Televendas"
        elif filial in mapa:
            t["classificacao"] = f"Loja {filial} ({mapa[filial].regional})"
        else:
            t["classificacao"] = "Fora do painel"
    return {
        "eventos_em_memoria": len(eventos),
        "primeiro": eventos[0]["momento"].astimezone(FUSO).isoformat() if eventos else None,
        "ultimo": eventos[-1]["momento"].astimezone(FUSO).isoformat() if eventos else None,
        "por_tipo": dict(sorted(tipos.items(), key=lambda kv: -kv[1])),
        "ultimos_eventos_completos": list(reversed(_brutos)),
        "origens_hoje": [{"origem": k, "classe": classe_origem({"origem_id": k} if "sem origem" not in k else {}),
                          "atendimentos": v} for k, v in sorted(origens.items(), key=lambda kv: -kv[1])[:30]],
        "saidas_da_fila": dict(sorted(saidas.items(), key=lambda kv: -kv[1])),
        # Quem mandou o cliente para a fila das lojas hoje (para separar bot principal e Whizz).
        "encaminhado_para_lojas_por": [{"quem": k, "hoje": v}
                                       for k, v in sorted(encaminhou.items(), key=lambda kv: -kv[1])[:30]],
        "times": sorted(times.values(), key=lambda t: (t["classificacao"] == "Fora do painel", t["nome"] or "")),
    }

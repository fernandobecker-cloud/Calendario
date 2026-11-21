"""Fila do televendas, para a Ana deixar de oferecer o televendas quando ele
estiver cheio.

A Omnichat avisa por webhook (painel > Configurações > Webhooks) cada vez que
um atendimento muda de dono:
    chat-routed   -> toType TEAM: o cliente entrou na fila daquele time;
                     toType USER (ou outro): foi pego por alguém, saiu da fila.
    chat-finished -> saiu da fila.
Aqui fica, em memória, quem está esperando em cada time e desde quando.

A configuração (modo, time do televendas e limites) é feita no portal (aba
Catálogo do agente) e lida de lá a cada CONFIG_TTL_S:
    modo "automatico"    -> segue a fila, com dois limites para não ficar
                            ligando e desligando (desliga com >= limite_desliga
                            esperando, religa com <= limite_religa);
    modo "disponivel"    -> televendas sempre oferecido;
    modo "indisponivel"  -> televendas nunca oferecido.

Limites conhecidos:
- Num reinício (deploy) a fila recomeça vazia: quem já esperava só entra na
  conta ao ser roteado de novo. Por isso cada espera expira em ESPERA_MAX_S e o
  modo manual vale por cima de tudo.
- Sem configuração ou sem time escolhido, o televendas fica disponível
  (o comportamento de antes).
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime

import requests

from . import config

log = logging.getLogger("agente_api.fila")

MODOS = ("automatico", "disponivel", "indisponivel")
AVISO_INDISPONIVEL = (
    "TELEVENDAS INDISPONÍVEL NO MOMENTO (alta demanda): ao perguntar o canal de compra, ofereça "
    "somente SITE ou LOJA FÍSICA. Se o cliente pedir televendas, explique que o televendas está "
    "com alta demanda agora e sugira o site (envie o link) ou a loja física."
)

_lock = threading.Lock()
# objectId do atendimento -> {"time": id do time, "desde": epoch}
_espera: dict[str, dict] = {}
# id do time -> {"nome", "visto_em"}: para o portal mostrar a lista e o CRM escolher o televendas
_times: dict[str, dict] = {}
_traces: OrderedDict[str, None] = OrderedDict()
_MAX_TRACES = 20000
_estado = {"disponivel": True, "eventos": 0, "ultimo_evento": None, "inicio": time.time()}
_config = {"lido_em": 0.0, "dados": None}


class WebhookNaoAutorizado(Exception):
    pass


def autorizar_webhook(authorization: str | None, x_api_key: str | None) -> None:
    token = config.OMNI_WEBHOOK_TOKEN
    if not token:
        raise WebhookNaoAutorizado("OMNI_WEBHOOK_TOKEN nao configurado no servidor.")
    recebido = x_api_key or ""
    if authorization:
        recebido = authorization[7:] if authorization.lower().startswith("bearer ") else authorization
    if not hmac.compare_digest(recebido.strip().encode(), token.encode()):
        raise WebhookNaoAutorizado("Token invalido.")


def _epoch(texto) -> float:
    try:
        return datetime.fromisoformat(str(texto).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return time.time()


def registrar_evento(evento: dict) -> str:
    """Aplica um evento do webhook. Devolve o que foi feito (para o log)."""
    tipo = evento.get("type")
    payload = evento.get("payload") or {}
    chave = str(payload.get("objectId") or payload.get("chatId") or "")
    trace = f"{evento.get('traceId')}:{tipo}:{chave}"
    with _lock:
        if trace in _traces:
            return "repetido"
        _traces[trace] = None
        if len(_traces) > _MAX_TRACES:
            _traces.popitem(last=False)
        _estado["eventos"] += 1
        _estado["ultimo_evento"] = time.time()
        if not chave:
            return "sem id"
        if tipo == "chat-routed":
            destino = payload.get("to") or {}
            if str(payload.get("toType") or "").upper() == "TEAM" and destino.get("id"):
                time_id = str(destino["id"])
                _times[time_id] = {"nome": destino.get("name") or _times.get(time_id, {}).get("nome"),
                                   "visto_em": time.time()}
                _espera[chave] = {"time": time_id, "desde": _epoch(payload.get("timeStamp"))}
                return f"entrou na fila {time_id}"
            return "saiu da fila" if _espera.pop(chave, None) else "ignorado"
        if tipo == "chat-finished":
            return "saiu da fila" if _espera.pop(chave, None) else "ignorado"
        return "ignorado"


def _limpar_expirados(agora: float) -> None:
    for chave in [c for c, e in _espera.items() if agora - e["desde"] > config.ESPERA_MAX_S]:
        del _espera[chave]


def _baixar_config() -> dict | None:
    try:
        resp = requests.get(
            config.TELEVENDAS_CONFIG_URL,
            headers={"x-api-key": config.TOKEN, "User-Agent": config.USER_AGENT},
            timeout=4,
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        dados = resp.json()
        return dados if isinstance(dados, dict) else None
    except (requests.RequestException, ValueError) as exc:
        log.warning("nao consegui ler a configuracao do televendas no portal: %s", exc)
        return None


def ler_config() -> dict:
    """Configuração do portal, relida a cada CONFIG_TTL_S (fica com a última boa se o portal cair)."""
    agora = time.monotonic()
    if not _config["lido_em"] or agora - _config["lido_em"] > config.TELEVENDAS_CONFIG_TTL_S:
        novo = _baixar_config()
        _config["lido_em"] = agora
        if novo is not None:
            _config["dados"] = novo
    return _config["dados"] or {}


def _decidir(cfg: dict, na_fila: int) -> bool:
    modo = cfg.get("modo") if cfg.get("modo") in MODOS else "disponivel"
    if modo != "automatico":
        return modo == "disponivel"
    if not cfg.get("time_id"):
        return True
    desliga = int(cfg.get("limite_desliga") or 0)
    religa = int(cfg.get("limite_religa") or 0)
    if desliga <= 0:
        return True
    if _estado["disponivel"] and na_fila >= desliga:
        return False
    if not _estado["disponivel"] and na_fila <= min(religa, desliga - 1):
        return True
    return _estado["disponivel"]


def situacao() -> dict:
    cfg = ler_config()
    agora = time.time()
    with _lock:
        _limpar_expirados(agora)
        time_id = cfg.get("time_id")
        esperando = [e for e in _espera.values() if e["time"] == time_id] if time_id else []
        disponivel = _decidir(cfg, len(esperando))
        if disponivel != _estado["disponivel"]:
            log.info("televendas %s (fila %s)", "DISPONIVEL" if disponivel else "INDISPONIVEL", len(esperando))
        _estado["disponivel"] = disponivel
        por_time: dict[str, int] = {}
        for e in _espera.values():
            por_time[e["time"]] = por_time.get(e["time"], 0) + 1
        return {
            "disponivel": disponivel,
            "config": cfg,
            "na_fila": len(esperando),
            "espera_mais_antiga_min": round((agora - min(e["desde"] for e in esperando)) / 60, 1) if esperando else 0,
            "eventos_recebidos": _estado["eventos"],
            "ultimo_evento": datetime.fromtimestamp(_estado["ultimo_evento"]).astimezone().isoformat()
            if _estado["ultimo_evento"] else None,
            "contando_desde": datetime.fromtimestamp(_estado["inicio"]).astimezone().isoformat(),
            "times": sorted(
                ({"id": t, "nome": d["nome"], "na_fila": por_time.get(t, 0)} for t, d in _times.items()),
                key=lambda t: (t["nome"] or "").lower(),
            ),
        }


def televendas_disponivel() -> bool:
    try:
        return situacao()["disponivel"]
    except Exception:  # noqa: BLE001 - a busca de produtos nunca pode cair por causa da fila
        log.exception("erro ao calcular a fila do televendas")
        return True

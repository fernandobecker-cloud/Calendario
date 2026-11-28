"""Status das mensagens de campanha da Omnichat (webhook message-status).

Cada mensagem de campanha gera avisos de enviada, entregue, lida ou falha. Aqui só
fica um buffer: a cada FILA_ENVIO_S os avisos vão para o portal, que grava no
BigQuery (portal_crm.omni_campanha_status). A apuração de NPI usa essa tabela no
lugar da exportação manual da Omnichat (apuracao_npi26.dados_omni).

O telefone vai junto (é o que liga o envio ao contato da Emarsys). O formato do
evento não está documentado: os campos são procurados em mais de um lugar e o
evento completo vai junto nos primeiros avisos e sempre que faltar algum campo,
para dar para corrigir a leitura sem perder dados.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone

import requests

from . import config

log = logging.getLogger("agente_api.campanha_status")

_LOTE = 5000
_MAX_PENDENTES = 400_000
_BRUTOS_INICIAIS = 50  # depois de cada reinício, os primeiros vão com o evento completo
_MAX_TRACES = 300_000

_lock = threading.Lock()
_envio_lock = threading.Lock()
_pendentes: list[dict] = []
_traces: "OrderedDict[str, None]" = OrderedDict()
_exemplos: deque = deque(maxlen=5)
_estado = {"recebidos": 0, "enviados": 0, "descartados": 0, "ultimo": None, "ultimo_erro": None, "com_bruto": 0}


def _dict(valor) -> dict:
    return valor if isinstance(valor, dict) else {}


def _primeiro(*valores):
    for v in valores:
        if v not in (None, "", {}, []):
            return v
    return None


def _momento(payload: dict, mensagem: dict, disparo: dict) -> str:
    bruto = _primeiro(payload.get("timeStamp"), payload.get("timestamp"), payload.get("updatedAt"),
                      mensagem.get("updatedAt"), disparo.get("updatedAt"), payload.get("createdAt"))
    if isinstance(bruto, (int, float)):
        return datetime.fromtimestamp(bruto / 1000 if bruto > 1e11 else bruto, timezone.utc).isoformat()
    if bruto:
        return str(bruto)
    return datetime.now(timezone.utc).isoformat()


def eh_de_campanha(evento: dict) -> bool:
    payload = _dict(evento.get("payload"))
    origem = str(evento.get("origin") or evento.get("source") or "").lower()
    return "campaign" in origem or bool(payload.get("campaign") or payload.get("dispatch")
                                        or payload.get("campaignId") or payload.get("dispatchId"))


def extrair(evento: dict) -> dict:
    payload = _dict(evento.get("payload"))
    campanha = _dict(payload.get("campaign"))
    disparo = _dict(payload.get("dispatch"))
    contato = _dict(payload.get("contact")) or _dict(disparo.get("audienceContact"))
    mensagem = _dict(payload.get("message"))
    template = _dict(payload.get("template")) or _dict(mensagem.get("template")) or _dict(campanha.get("template"))
    telefone = _primeiro(contato.get("phoneNumber"), contato.get("phone"), payload.get("phoneNumber"),
                         payload.get("phone"), disparo.get("phoneNumber"), payload.get("chatId"), payload.get("to"))
    if isinstance(telefone, dict):
        telefone = _primeiro(telefone.get("phoneNumber"), telefone.get("id"))
    if telefone and contato.get("countryCode") and not str(telefone).startswith(str(contato["countryCode"])):
        telefone = f"{contato['countryCode']}{telefone}"
    status = _primeiro(payload.get("status"), mensagem.get("status"), disparo.get("status"))
    return {
        "momento": _momento(payload, mensagem, disparo),
        "status": str(status).upper() if status else None,
        "telefone": str(telefone) if telefone else None,
        "campanha_id": str(_primeiro(campanha.get("id"), payload.get("campaignId"), disparo.get("campaignId")) or "")
        or None,
        "campanha_nome": _primeiro(campanha.get("name"), payload.get("campaignName")),
        "template": _primeiro(template.get("name"), template.get("title"), template.get("elementName"),
                              payload.get("templateName"), payload.get("templateTitle"),
                              mensagem.get("templateName"), campanha.get("templateName"),
                              campanha.get("templateTitle")),
        "disparo_id": str(_primeiro(disparo.get("id"), payload.get("dispatchId"), mensagem.get("id"),
                                    payload.get("objectId")) or "") or None,
    }


def registrar(evento: dict) -> str:
    """Chamado pelo webhook para cada message-status. Não bloqueia."""
    if not eh_de_campanha(evento):
        return "ignorado"
    reg = extrair(evento)
    trace = f"{evento.get('traceId')}:{reg['status']}:{reg['disparo_id'] or reg['telefone']}"
    with _lock:
        if trace in _traces:
            return "repetido"
        _traces[trace] = None
        if len(_traces) > _MAX_TRACES:
            _traces.popitem(last=False)
        _estado["recebidos"] += 1
        _estado["ultimo"] = time.time()
        faltando = not (reg["telefone"] and reg["status"] and (reg["template"] or reg["campanha_nome"]))
        bruto = None
        if faltando or _estado["com_bruto"] < _BRUTOS_INICIAIS:
            _estado["com_bruto"] += 1
            bruto = json.dumps(evento, ensure_ascii=False, default=str)[:20000]
            _exemplos.append(evento)
        _pendentes.append({"trace_id": trace, **reg, "bruto": bruto})
        if len(_pendentes) > _MAX_PENDENTES:
            excesso = len(_pendentes) - _MAX_PENDENTES
            del _pendentes[:excesso]
            _estado["descartados"] += excesso
    return "status de campanha"


def enviar_pendentes() -> int:
    with _envio_lock:
        with _lock:
            lote = _pendentes[:_LOTE]
        if not lote or not config.CAMPANHA_STATUS_URL:
            return 0
        try:
            resp = requests.post(config.CAMPANHA_STATUS_URL, json={"registros": lote},
                                 headers={"x-api-key": config.TOKEN, "User-Agent": config.USER_AGENT}, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as exc:
            _estado["ultimo_erro"] = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {exc}"
            log.warning("nao consegui enviar %s status de campanha ao portal: %s", len(lote), exc)
            return 0
        with _lock:
            del _pendentes[: len(lote)]
            _estado["enviados"] += len(lote)
        return len(lote)


def _loop() -> None:
    while True:
        time.sleep(config.FILA_ENVIO_S)
        try:
            while enviar_pendentes() >= _LOTE:
                pass
        except Exception:  # noqa: BLE001 - a thread de envio nao pode morrer
            log.exception("erro no envio dos status de campanha")


def iniciar() -> None:
    threading.Thread(target=_loop, name="envio-campanha-status", daemon=True).start()


def situacao() -> dict:
    with _lock:
        return {
            "recebidos": _estado["recebidos"], "enviados": _estado["enviados"], "pendentes": len(_pendentes),
            "descartados": _estado["descartados"], "ultimo_erro": _estado["ultimo_erro"],
            "ultimo": datetime.fromtimestamp(_estado["ultimo"]).astimezone().isoformat() if _estado["ultimo"] else None,
            "exemplos": list(_exemplos),
        }

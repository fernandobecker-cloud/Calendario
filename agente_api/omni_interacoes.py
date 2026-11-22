"""Detalhes do atendimento pela API v1 da Omnichat (GET /interactions/{id}).

O webhook avisa que o cliente entrou na fila de um time, mas não diz:
  - a origem do atendimento (orgânico x campanha, ex. "20261123_WMKT_Whizz");
  - quando o vendedor clicou em "Assumir atendimento" (não gera chat-routed).
Os dois estão no atendimento (Interaction): `origin` e `contactedAt`.

Fluxo:
  1. fila.registrar_evento chama `entrou(...)` quando alguém entra na fila de um time;
  2. a thread daqui consulta o atendimento (origem) e segue reconsultando a cada
     OMNI_RECONSULTA_S enquanto ele estiver esperando;
  3. quando aparece `contactedAt` (assumido) ou o atendimento termina, manda um
     registro "omni-interacao" para o portal (mesmo envio dos eventos do webhook)
     e tira o cliente da fila do televendas na memória.

Limites: no máximo OMNI_API_RPS requisições por segundo (a Omnichat permite 10/s
somando todas as integrações da loja). 429 pausa as consultas por 5 min; 401/403
pausa por 30 min. Sem OMNI_API_KEY/OMNI_API_SECRET nada roda.

Qual id do webhook é o do atendimento não está documentado: tenta o csrId e,
se não achar, o objectId; guarda qual funcionou.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timezone

import requests

from . import config

log = logging.getLogger("agente_api.omni_interacoes")

_MAX_ACOMPANHANDO = 5000
_ESPERA_MAX_S = 3 * 3600  # depois disso desiste de reconsultar

_lock = threading.Lock()
_novos: deque = deque()
# chave da conversa -> {"ids": [...], "id_ok", "atendimento_id", "conversa_id", "desde", "proxima", "origem_enviada"}
_acompanhando: "OrderedDict[str, dict]" = OrderedDict()
_estado = {"pausado_ate": 0.0, "ultima_req": 0.0, "campo_id": None, "consultas": 0, "erros": 0,
           "ultimo_erro": None, "iniciado": False}


def ligado() -> bool:
    return bool(config.OMNI_API_KEY and config.OMNI_API_SECRET)


def entrou(chave: str, csr_id: str | None, object_id: str | None, conversa_id: str | None) -> None:
    """Chamado (sem bloquear) quando o cliente entra na fila de um time."""
    if not ligado():
        return
    ids = [i for i in ((csr_id, object_id) if _estado["campo_id"] != "objectId" else (object_id, csr_id)) if i]
    if not ids:
        return
    with _lock:
        _acompanhando.pop(chave, None)
        _acompanhando[chave] = {"ids": ids, "id_ok": None, "atendimento_id": object_id, "conversa_id": conversa_id,
                                "desde": time.time(), "proxima": 0.0, "origem_enviada": False}
        while len(_acompanhando) > _MAX_ACOMPANHANDO:
            _acompanhando.popitem(last=False)
        _novos.append(chave)


def saiu(chave: str) -> None:
    """O webhook já disse que saiu (encerrado ou passado a um vendedor)."""
    with _lock:
        item = _acompanhando.get(chave)
        if item and item["origem_enviada"]:
            _acompanhando.pop(chave, None)
        elif item:
            item["parar_depois_da_origem"] = True


def _data(valor) -> str | None:
    if isinstance(valor, dict):
        valor = valor.get("iso")
    if not valor:
        return None
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except ValueError:
        return None


def _nome(dado) -> str | None:
    if isinstance(dado, dict):
        return dado.get("name") or dado.get("username") or dado.get("objectId")
    return str(dado) if dado else None


def _get(interacao_id: str) -> tuple[int, dict | None]:
    espera = 1.0 / max(config.OMNI_API_RPS, 0.1) - (time.monotonic() - _estado["ultima_req"])
    if espera > 0:
        time.sleep(espera)
    _estado["ultima_req"] = time.monotonic()
    _estado["consultas"] += 1
    resp = requests.get(
        f"{config.OMNI_API_URL}/interactions/{interacao_id}",
        headers={"x-api-key": config.OMNI_API_KEY, "x-api-secret": config.OMNI_API_SECRET,
                 "Accept": "application/json", "User-Agent": config.USER_AGENT},
        timeout=15,
    )
    try:
        corpo = resp.json()
    except ValueError:
        corpo = None
    return resp.status_code, corpo if isinstance(corpo, dict) else None


def _consultar(item: dict) -> dict | None:
    """Busca o atendimento tentando os ids na ordem. None = falhou (tenta de novo depois)."""
    ids = [item["id_ok"]] if item["id_ok"] else item["ids"]
    for i, interacao_id in enumerate(ids):
        status, corpo = _get(interacao_id)
        if status == 200 and corpo:
            if not item["id_ok"]:
                item["id_ok"] = interacao_id
                campo = "csrId" if interacao_id != item["atendimento_id"] else "objectId"
                if _estado["campo_id"] != campo:
                    log.info("omnichat: o id do atendimento e o %s do webhook", campo)
                _estado["campo_id"] = campo
            return corpo
        if status == 429:
            _estado["pausado_ate"] = time.time() + 300
            _erro("429 (limite de requisicoes): pausando 5 min")
            return None
        if status in (401, 403):
            _estado["pausado_ate"] = time.time() + 1800
            _erro(f"{status}: chave ou segredo recusado, pausando 30 min")
            return None
        if status != 404 or i == len(ids) - 1:
            _erro(f"{status} ao consultar o atendimento")
            return None
    return None


def _erro(texto: str) -> None:
    _estado["erros"] += 1
    _estado["ultimo_erro"] = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {texto}"
    log.warning("omnichat api: %s", texto)


def _registro(item: dict, corpo: dict, contatado_em: str | None) -> dict:
    origem = corpo.get("origin") if isinstance(corpo.get("origin"), dict) else {}
    status = str(corpo.get("status") or "")
    momento = contatado_em or _data(corpo.get("finishedAt")) or datetime.now(timezone.utc).isoformat()
    return {
        "trace_id": f"omni:{item['id_ok']}:{status}:{contatado_em or ''}",
        "tipo": "omni-interacao",
        "momento": momento,
        "atendimento_id": item["atendimento_id"],
        "conversa_id": item["conversa_id"],
        "para_id": str(corpo.get("teamId") or corpo.get("botFowardedToTeam") or "") or None,
        "interacao_status": status or None,
        "contatado_em": contatado_em,
        "contatado_por": _nome(corpo.get("contactedBy")),
        "encaminhado_em": _data(corpo.get("botFowardedAt")),
        "origem_id": str(origem.get("id") or "") or None,
        "origem_canal": origem.get("channel"),
        "origem_tipo": origem.get("type"),
        "origem_url": origem.get("url"),
        "bruto": {k: corpo.get(k) for k in ("objectId", "status", "origin", "teamId", "botFowardedToTeam",
                                            "botFowardedAt", "contactedAt", "finishedAt", "retailerCreated")},
    }


def _processar(chave: str, guardar, tirar_da_fila) -> None:
    with _lock:
        item = _acompanhando.get(chave)
    if not item:
        return
    corpo = _consultar(item)
    agora = time.time()
    if corpo is None:
        item["proxima"] = agora + config.OMNI_RECONSULTA_S
        if not item["id_ok"] and agora - item["desde"] > 600:
            with _lock:
                _acompanhando.pop(chave, None)  # nenhum id funcionou
        return
    contatado_em = _data(corpo.get("contactedAt"))
    status = str(corpo.get("status") or "").upper()
    terminou = bool(contatado_em) or status in ("CONTACTED", "FINISHED")
    if terminou or not item["origem_enviada"]:
        guardar(_registro(item, corpo, contatado_em))
        item["origem_enviada"] = True
    if terminou:
        tirar_da_fila(chave)
    if terminou or item.get("parar_depois_da_origem") or agora - item["desde"] > _ESPERA_MAX_S:
        with _lock:
            _acompanhando.pop(chave, None)
    else:
        item["proxima"] = agora + config.OMNI_RECONSULTA_S


def _proxima_chave() -> str | None:
    with _lock:
        if _novos:
            return _novos.popleft()
        agora = time.time()
        for chave, item in _acompanhando.items():
            if item["proxima"] and item["proxima"] <= agora:
                item["proxima"] = 0.0  # evita pegar duas vezes
                return chave
    return None


def _loop(guardar, tirar_da_fila) -> None:
    while True:
        try:
            if time.time() < _estado["pausado_ate"]:
                time.sleep(10)
                continue
            chave = _proxima_chave()
            if chave is None:
                time.sleep(2)
                continue
            _processar(chave, guardar, tirar_da_fila)
        except Exception:  # noqa: BLE001 - a thread nao pode morrer
            log.exception("erro nas consultas da Omnichat")
            time.sleep(5)


def iniciar(guardar, tirar_da_fila) -> None:
    if not ligado() or _estado["iniciado"]:
        if not ligado():
            log.info("omnichat api desligada (OMNI_API_KEY/OMNI_API_SECRET nao configurados)")
        return
    _estado["iniciado"] = True
    threading.Thread(target=_loop, args=(guardar, tirar_da_fila), name="omni-interacoes", daemon=True).start()


def situacao() -> dict:
    with _lock:
        return {"ligado": ligado(), "acompanhando": len(_acompanhando), "na_vez": len(_novos),
                "consultas": _estado["consultas"], "erros": _estado["erros"], "ultimo_erro": _estado["ultimo_erro"],
                "id_do_atendimento": _estado["campo_id"],
                "pausado_ate": datetime.fromtimestamp(_estado["pausado_ate"]).astimezone().isoformat()
                if _estado["pausado_ate"] > time.time() else None}

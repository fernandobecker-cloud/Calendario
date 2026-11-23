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

import hashlib
import hmac
import logging
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone

import requests

from . import config, omni_interacoes

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
    # O telefone (chatId) é o que liga a entrada na fila à saída: o objectId pode
    # mudar quando o vendedor pega o atendimento. Fica só em memória, nunca é enviado.
    contato = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    mensagem = payload.get("message") if isinstance(payload.get("message"), dict) else {}
    chave = str(payload.get("chatId") or contato.get("phoneNumber") or payload.get("objectId") or "")
    trace = f"{evento.get('traceId')}:{tipo}:{payload.get('objectId') or mensagem.get('id') or chave}"
    with _lock:
        if trace in _traces:
            return "repetido"
        _traces[trace] = None
        if len(_traces) > _MAX_TRACES:
            _traces.popitem(last=False)
        _estado["eventos"] += 1
        _estado["ultimo_evento"] = time.time()
        _guardar_para_envio(evento, trace)
        if not chave:
            return "sem id"
        if tipo == "chat-routed":
            destino = payload.get("to") or {}
            if str(payload.get("toType") or "").upper() == "TEAM" and destino.get("id"):
                time_id = str(destino["id"])
                _times[time_id] = {"nome": destino.get("name") or _times.get(time_id, {}).get("nome"),
                                   "visto_em": time.time()}
                _espera[chave] = {"time": time_id, "desde": _epoch(payload.get("timeStamp"))}
                omni_interacoes.entrou(chave, payload.get("csrId"), payload.get("objectId"),
                                       _conversa(payload.get("chatId")))
                return f"entrou na fila {time_id}"
            omni_interacoes.saiu(chave)
            return "saiu da fila" if _espera.pop(chave, None) else "ignorado"
        if tipo == "chat-finished":
            omni_interacoes.saiu(chave)
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
            "omnichat_api": omni_interacoes.situacao(),
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



# --- Envio dos eventos para o portal (histórico no BigQuery e painel das filas) ---
# O portal grava e monta o painel por loja/regional. Aqui só fica um buffer:
# se o portal estiver fora, os eventos esperam (até _MAX_PENDENTES) e vão depois.

_pendentes: list[dict] = []
_MAX_PENDENTES = 50000
_envio_lock = threading.Lock()


def _pessoa(dado) -> tuple[str | None, str | None]:
    dado = dado if isinstance(dado, dict) else {}
    return (str(dado["id"]) if dado.get("id") else None), dado.get("name")


_CAMPOS_TELEFONE = {"chatid", "phone", "phonenumber", "telefone", "number", "msisdn", "waid"}


def _sem_telefone(dado):
    if isinstance(dado, dict):
        return {k: ("***" if str(k).lower() in _CAMPOS_TELEFONE else _sem_telefone(v)) for k, v in dado.items()}
    if isinstance(dado, list):
        return [_sem_telefone(v) for v in dado]
    if isinstance(dado, str) and re.fullmatch(r"\+?\d{10,15}", dado.strip()):
        return "***"
    return dado


def _conversa(chat_id) -> str | None:
    """Código da conversa a partir do telefone, sem dar para voltar ao número."""
    if not chat_id:
        return None
    segredo = (config.TOKEN or config.OMNI_WEBHOOK_TOKEN or "agente").encode()
    return hmac.new(segredo, str(chat_id).encode(), hashlib.sha256).hexdigest()[:20]


def _guardar_para_envio(evento: dict, trace: str) -> None:
    """Registro enxuto do evento, sem o telefone do cliente (chatId)."""
    payload = evento.get("payload") or {}
    para_id, para_nome = _pessoa(payload.get("to"))
    por = payload.get("finishedBy") or payload.get("routedBy")
    por_id, por_nome = _pessoa(por)
    # Resposta de campanha (message-replies): campanha + telefone, sem chatId/objectId.
    contato = payload.get("contact") if isinstance(payload.get("contact"), dict) else {}
    campanha = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else {}
    momento = payload.get("timeStamp")
    if not momento and isinstance(payload.get("timestamp"), (int, float)):
        momento = datetime.fromtimestamp(payload["timestamp"] / 1000, timezone.utc).isoformat()
    _pendentes.append({
        "trace_id": trace,
        "tipo": evento.get("type"),
        "momento": momento or datetime.now().astimezone().isoformat(),
        "atendimento_id": str(payload.get("objectId") or "") or None,
        "conversa_id": _conversa(payload.get("chatId") or contato.get("phoneNumber")),
        "campanha_id": str(campanha.get("id") or "") or None,
        "campanha_nome": campanha.get("name"),
        "para_tipo": payload.get("toType"),
        "para_id": para_id,
        "para_nome": para_nome,
        "de_tipo": payload.get("fromType"),
        "por_id": por_id,
        "por_nome": por_nome,
        "por_usuario_tipo": por.get("userType") if isinstance(por, dict) else None,
        "rota_tipo": payload.get("routeType"),
        "origem": evento.get("origin"),
        "motivo_encerramento": payload.get("closingReason"),
        "plataforma": payload.get("platform"),
        # Evento completo sem o telefone: o portal guarda só os últimos em memória
        # (diagnóstico), para descobrir campos novos. Não vai para o BigQuery.
        "bruto": _sem_telefone(evento),
    })
    if len(_pendentes) > _MAX_PENDENTES:
        del _pendentes[: len(_pendentes) - _MAX_PENDENTES]


def enviar_pendentes() -> int:
    """Manda o buffer ao portal. Devolve quantos foram enviados (0 se falhou)."""
    with _envio_lock:
        with _lock:
            lote = _pendentes[:2000]
        if not lote or not config.FILA_EVENTOS_URL:
            return 0
        try:
            resp = requests.post(
                config.FILA_EVENTOS_URL,
                json={"eventos": lote},
                headers={"x-api-key": config.TOKEN, "User-Agent": config.USER_AGENT},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            log.warning("nao consegui enviar %s eventos da fila ao portal: %s", len(lote), exc)
            return 0
        with _lock:
            del _pendentes[: len(lote)]
        return len(lote)


def _loop_de_envio() -> None:
    while True:
        time.sleep(config.FILA_ENVIO_S)
        try:
            while enviar_pendentes() >= 2000:
                pass
        except Exception:  # noqa: BLE001 - a thread de envio nao pode morrer
            log.exception("erro no envio dos eventos da fila")


def _guardar_registro(registro: dict) -> None:
    """Registro pronto (ex.: detalhes do atendimento vindos da API da Omnichat) para o portal."""
    with _lock:
        _pendentes.append(registro)
        if len(_pendentes) > _MAX_PENDENTES:
            del _pendentes[: len(_pendentes) - _MAX_PENDENTES]


def _tirar_da_fila(chave: str) -> None:
    """O vendedor assumiu (visto pela API da Omnichat): sai da fila do televendas."""
    with _lock:
        _espera.pop(chave, None)


def iniciar_envio() -> None:
    threading.Thread(target=_loop_de_envio, name="envio-fila", daemon=True).start()
    omni_interacoes.iniciar(_guardar_registro, _tirar_da_fila)

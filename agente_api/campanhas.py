"""Números de envio das campanhas de WhatsApp pela API de campanhas da Omnichat.

GET {OMNI_CAMPANHAS_URL}/campaigns/ devolve as campanhas criadas no período, cada uma
com `base` e `stats` (sent, delivered, read, error). O portal junta isso com as
respostas (webhook message-replies) e os encaminhamentos para um time, que já ficam
no BigQuery, para montar o funil da aba Filas.

Guarda o resultado por 5 min para não repetir consultas a cada atualização da tela.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from . import config

log = logging.getLogger("agente_api.campanhas")

_CACHE_S = 300
_MAX_PAGINAS = 20  # 100 campanhas por página
_lock = threading.Lock()
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


class CampanhasErro(RuntimeError):
    pass


def ligado() -> bool:
    return bool(config.OMNI_CAMPANHAS_KEY and config.OMNI_CAMPANHAS_SECRET)


def _numero(valor) -> int:
    try:
        return int(valor or 0)
    except (TypeError, ValueError):
        return 0


def _get(params: dict) -> dict:
    try:
        resp = requests.get(
            f"{config.OMNI_CAMPANHAS_URL}/campaigns/",
            params=params,
            headers={"x-api-key": config.OMNI_CAMPANHAS_KEY, "x-api-secret": config.OMNI_CAMPANHAS_SECRET,
                     "Accept": "application/json", "User-Agent": config.USER_AGENT},
            timeout=30,
        )
    except requests.RequestException as exc:
        raise CampanhasErro(f"Sem resposta da API de campanhas da Omnichat: {exc}") from exc
    if resp.status_code in (401, 403):
        raise CampanhasErro(f"A API de campanhas da Omnichat recusou a chave ({resp.status_code}): "
                            f"{resp.text[:200]}")
    if resp.status_code != 200:
        raise CampanhasErro(f"API de campanhas da Omnichat respondeu {resp.status_code}: {resp.text[:200]}")
    try:
        corpo = resp.json()
    except ValueError as exc:
        raise CampanhasErro("A API de campanhas da Omnichat não devolveu JSON.") from exc
    return corpo if isinstance(corpo, dict) else {"items": corpo if isinstance(corpo, list) else []}


def listar(inicio: str, fim: str) -> dict:
    """Campanhas criadas entre inicio e fim (YYYY-MM-DD, horário de Brasília)."""
    if not ligado():
        raise CampanhasErro("Faltam OMNI_API_KEY / OMNI_API_SECRET no agente-ia-api.")
    chave = (inicio, fim)
    with _lock:
        guardado = _cache.get(chave)
        if guardado and time.monotonic() - guardado[0] < _CACHE_S:
            return guardado[1]
    params = {"startDate": f"{inicio}T00:00:00", "endDate": f"{fim}T23:59:59",
              "timeZone": "America/Sao_Paulo", "limit": 100}
    campanhas = []
    for _ in range(_MAX_PAGINAS):
        corpo = _get(params)
        for item in corpo.get("items") or []:
            if not isinstance(item, dict):
                continue
            camp = item.get("campaign") if isinstance(item.get("campaign"), dict) else item
            stats = item.get("stats") if isinstance(item.get("stats"), dict) else {}
            campanhas.append({
                "id": str(camp.get("id") or camp.get("_id") or camp.get("objectId") or "") or None,
                "nome": camp.get("name"),
                "status": camp.get("status"),
                "criada_em": camp.get("createdAt"),
                "base": _numero(item.get("base")),
                "enviadas": _numero(stats.get("sent")),
                "entregues": _numero(stats.get("delivered")),
                "lidas": _numero(stats.get("read")),
                "erro": _numero(stats.get("error")),
                "agendadas": _numero(stats.get("scheduled")),
            })
        proxima = corpo.get("tokenPagination")
        if not proxima:
            break
        params["tokenPagination"] = proxima
    resultado = {"campanhas": campanhas, "consultado_em": time.time()}
    with _lock:
        _cache[chave] = (time.monotonic(), resultado)
        if len(_cache) > 50:
            _cache.pop(next(iter(_cache)))
    log.info("campanhas %s a %s: %s", inicio, fim, len(campanhas))
    return resultado

"""Alertas de fila alta das lojas no Microsoft Teams.

A cada minuto o portal confere o painel das filas (agente_filas.painel, em
memória) e, quando uma loja passa de um limite, posta um cartão num canal do
Teams. Os canais são webhooks do Teams (app Workflows, "Postar em um canal
quando uma solicitação de webhook for recebida") e ficam em variáveis de ambiente
do portal, porque quem tem a URL consegue postar no canal:
    TEAMS_WEBHOOK_URL       canal geral (recebe tudo que não tiver canal próprio)
    TEAMS_WEBHOOK_R1 ... R7 canal de cada regional (opcional)

As regras (ligado, limites, intervalo, horário) são editadas na aba Filas e
gravadas numa tabela de uma linha no BigQuery (portal_crm.filas_alertas).

Para não virar spam: uma loja só gera aviso ao entrar em alerta; enquanto
continuar acima do limite, repete no máximo a cada `intervalo_min`; volta a
avisar de novo assim que sair e entrar em alerta outra vez. Os avisos de um
mesmo minuto vão juntos, num cartão por canal.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

import requests
from google.api_core.exceptions import NotFound
from google.cloud import bigquery

from backend.services import agente_filas
from backend.services.agente_planilha import PlanilhaErroBQ, _DATASET, _PROJECT_ID, _cliente

log = logging.getLogger(__name__)

_TABELA = "filas_alertas"
_TIMEOUT_S = 60
_CACHE_TTL_S = 300
_CICLO_S = 60

PADRAO = {"ativo": False, "limite_fila": 8, "limite_espera_min": 20, "intervalo_min": 30,
          "hora_inicio": 10, "hora_fim": 22}

_SCHEMA = (
    bigquery.SchemaField("ativo", "BOOLEAN"),
    bigquery.SchemaField("limite_fila", "INTEGER"),
    bigquery.SchemaField("limite_espera_min", "INTEGER"),
    bigquery.SchemaField("intervalo_min", "INTEGER"),
    bigquery.SchemaField("hora_inicio", "INTEGER"),
    bigquery.SchemaField("hora_fim", "INTEGER"),
    bigquery.SchemaField("alterado_por", "STRING"),
    bigquery.SchemaField("alterado_em", "TIMESTAMP"),
)

_lock = threading.Lock()
_cache: dict[str, Any] = {"lido_em": 0.0, "dados": None}
# filial -> {"em_alerta": bool, "avisado_em": epoch}
_lojas: dict[str, dict[str, Any]] = {}
_enviados: deque = deque(maxlen=50)
_estado = {"iniciado": False, "ultimo_ciclo": None, "ultimo_erro": None}


class ConfigInvalida(ValueError):
    pass


def _tabela_id() -> str:
    if not _PROJECT_ID:
        raise PlanilhaErroBQ("Variavel BASE_VENDAS_BQ_PROJECT nao configurada")
    return f"{_PROJECT_ID}.{_DATASET}.{_TABELA}"


def canais() -> dict[str, str]:
    """Regional (ou "geral") -> URL do webhook do Teams."""
    saida = {}
    geral = os.getenv("TEAMS_WEBHOOK_URL", "").strip()
    if geral:
        saida["geral"] = geral
    for n in range(1, 10):
        url = os.getenv(f"TEAMS_WEBHOOK_R{n}", "").strip()
        if url:
            saida[f"R{n}"] = url
    return saida


def validar(dados: dict[str, Any]) -> dict[str, Any]:
    try:
        cfg = {
            "ativo": bool(dados.get("ativo")),
            "limite_fila": int(dados.get("limite_fila") or 0),
            "limite_espera_min": int(dados.get("limite_espera_min") or 0),
            "intervalo_min": int(dados.get("intervalo_min") or 0),
            "hora_inicio": int(dados.get("hora_inicio") if dados.get("hora_inicio") is not None else 0),
            "hora_fim": int(dados.get("hora_fim") if dados.get("hora_fim") is not None else 24),
        }
    except (TypeError, ValueError) as exc:
        raise ConfigInvalida("Os campos precisam ser números inteiros.") from exc
    if cfg["limite_fila"] < 1 and cfg["limite_espera_min"] < 1:
        raise ConfigInvalida("Preencha pelo menos um limite: clientes na fila ou minutos de espera.")
    if cfg["intervalo_min"] < 5:
        raise ConfigInvalida("O intervalo entre avisos da mesma loja precisa ser de pelo menos 5 min.")
    if not 0 <= cfg["hora_inicio"] < cfg["hora_fim"] <= 24:
        raise ConfigInvalida("Horário inválido: o início precisa ser antes do fim (0 a 24 h).")
    return cfg


def salvar(dados: dict[str, Any], usuario: str) -> dict[str, Any]:
    registro = {**validar(dados), "alterado_por": usuario,
                "alterado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    job = bigquery.LoadJobConfig(schema=_SCHEMA, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE)
    try:
        _cliente().load_table_from_json([registro], _tabela_id(), job_config=job).result(timeout=_TIMEOUT_S)
    except PlanilhaErroBQ:
        raise
    except Exception as exc:
        raise PlanilhaErroBQ(f"Falha ao gravar os alertas no BigQuery: {exc}") from exc
    with _lock:
        _cache.update(dados=registro, lido_em=time.monotonic())
    return registro


def carregar() -> dict[str, Any]:
    with _lock:
        if _cache["lido_em"] and time.monotonic() - _cache["lido_em"] < _CACHE_TTL_S:
            return _cache["dados"] or dict(PADRAO)
        try:
            linhas = list(_cliente().list_rows(_tabela_id(), timeout=_TIMEOUT_S))
        except NotFound:
            linhas = []
        except Exception as exc:  # noqa: BLE001
            if _cache["lido_em"]:
                return _cache["dados"] or dict(PADRAO)
            raise PlanilhaErroBQ(f"Falha ao ler os alertas no BigQuery: {exc}") from exc
        dados = None
        if linhas:
            dados = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in linhas[0].items()}
        _cache.update(dados=dados, lido_em=time.monotonic())
        return dados or dict(PADRAO)


# --- Cartão do Teams ------------------------------------------------------------


def _cartao(titulo: str, linhas: list[str], link: str | None) -> dict[str, Any]:
    corpo: list[dict[str, Any]] = [{"type": "TextBlock", "text": titulo, "weight": "Bolder", "size": "Medium",
                                    "wrap": True}]
    corpo += [{"type": "TextBlock", "text": l, "wrap": True, "spacing": "Small"} for l in linhas]
    conteudo: dict[str, Any] = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                                "type": "AdaptiveCard", "version": "1.4", "body": corpo}
    if link:
        conteudo["actions"] = [{"type": "Action.OpenUrl", "title": "Abrir o painel das filas", "url": link}]
    return {"type": "message", "attachments": [
        {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": conteudo}]}


def _postar(url: str, cartao: dict[str, Any]) -> str | None:
    """Devolve None se deu certo, ou o erro."""
    try:
        resp = requests.post(url, json=cartao, timeout=15)
        if resp.status_code >= 300:
            return f"Teams respondeu {resp.status_code}: {resp.text[:200]}"
    except requests.RequestException as exc:
        return f"falha ao postar no Teams: {exc}"
    return None


def _link() -> str | None:
    base = os.getenv("PORTAL_URL_PUBLICA", "https://calendario-39gp.onrender.com").rstrip("/")
    chave = os.getenv("FILAS_LINK_CHAVE", "").strip()
    return f"{base}/filas/{chave}" if chave else None


def _min(valor: float | None) -> str:
    if not valor:
        return "–"
    return f"{int(valor // 60)}h{int(valor % 60):02d}" if valor >= 60 else f"{round(valor)} min"


def enviar_teste(usuario: str) -> dict[str, Any]:
    destinos = canais()
    if not destinos:
        return {"enviados": [], "erros": ["Nenhum canal configurado (TEAMS_WEBHOOK_URL ou TEAMS_WEBHOOK_R1..R7)."]}
    enviados, erros = [], []
    for nome, url in destinos.items():
        cartao = _cartao(f"✅ Teste dos alertas de fila ({nome})",
                         [f"Enviado pelo portal do CRM por {usuario}. Os avisos de fila alta das lojas vão chegar aqui."],
                         _link())
        erro = _postar(url, cartao)
        (erros.append(f"{nome}: {erro}") if erro else enviados.append(nome))
    return {"enviados": enviados, "erros": erros}


# --- Verificação periódica --------------------------------------------------------


def _dentro_do_horario(cfg: dict[str, Any], agora: datetime) -> bool:
    hora = agora.astimezone(agente_filas.FUSO).hour
    return int(cfg["hora_inicio"]) <= hora < int(cfg["hora_fim"])


def _em_alerta(loja: dict[str, Any], cfg: dict[str, Any]) -> bool:
    if not loja.get("na_fila"):
        return False
    fila = int(cfg.get("limite_fila") or 0)
    espera = int(cfg.get("limite_espera_min") or 0)
    return bool((fila and loja["na_fila"] >= fila) or (espera and (loja.get("espera_mais_antiga_min") or 0) >= espera))


def verificar(cfg: dict[str, Any], painel: dict[str, Any], agora_epoch: float) -> dict[str, list[dict[str, Any]]]:
    """Decide quais lojas avisar agora (por regional) e atualiza o estado de cada loja."""
    avisar: dict[str, list[dict[str, Any]]] = {}
    intervalo = int(cfg["intervalo_min"]) * 60
    for reg in painel.get("regionais", []):
        for loja in reg["lojas"]:
            estado = _lojas.setdefault(loja["filial"], {"em_alerta": False, "avisado_em": 0.0})
            if not _em_alerta(loja, cfg):
                estado["em_alerta"] = False
                continue
            if not estado["em_alerta"] or agora_epoch - estado["avisado_em"] >= intervalo:
                avisar.setdefault(reg["regional"], []).append({**loja, "repetido": estado["em_alerta"]})
                estado["avisado_em"] = agora_epoch
            estado["em_alerta"] = True
    return avisar


def _enviar(avisar: dict[str, list[dict[str, Any]]], cfg: dict[str, Any]) -> None:
    destinos = canais()
    if not destinos:
        _estado["ultimo_erro"] = "Nenhum canal do Teams configurado."
        return
    por_canal: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for regional, lojas in avisar.items():
        canal = regional if regional in destinos else "geral"
        if canal not in destinos:
            continue
        por_canal.setdefault(canal, []).extend((regional, l) for l in lojas)
    for canal, itens in por_canal.items():
        linhas = [
            f"**{l['filial']} {l['loja']}** ({reg}): {l['na_fila']} na fila, mais antigo há "
            f"{_min(l.get('espera_mais_antiga_min'))}{' · continua alta' if l['repetido'] else ''}"
            for reg, l in sorted(itens, key=lambda x: -x[1]["na_fila"])
        ]
        titulo = "⚠️ Fila alta " + ("na loja" if len(itens) == 1 else f"em {len(itens)} lojas")
        rodape = (f"Limite: {cfg['limite_fila']} na fila ou {cfg['limite_espera_min']} min de espera. "
                  f"Novo aviso da mesma loja em {cfg['intervalo_min']} min se continuar.")
        erro = _postar(destinos[canal], _cartao(titulo, linhas + [f"_{rodape}_"], _link()))
        _enviados.appendleft({"em": datetime.now(agente_filas.FUSO).isoformat(timespec="seconds"), "canal": canal,
                              "lojas": [f"{l['filial']} {l['loja']}" for _, l in itens], "erro": erro})
        if erro:
            _estado["ultimo_erro"] = erro
            log.warning("alertas: %s", erro)


def ciclo() -> None:
    cfg = carregar()
    agora = datetime.now(timezone.utc)
    _estado["ultimo_ciclo"] = agora.astimezone(agente_filas.FUSO).isoformat(timespec="seconds")
    if not cfg.get("ativo") or not _dentro_do_horario(cfg, agora):
        return
    avisar = verificar(cfg, agente_filas.painel(com_televendas=False), time.time())
    if avisar:
        _enviar(avisar, cfg)


def _loop() -> None:
    while True:
        time.sleep(_CICLO_S)
        try:
            ciclo()
        except Exception as exc:  # noqa: BLE001 - a thread nao pode morrer
            _estado["ultimo_erro"] = str(exc)[:300]
            log.exception("alertas: erro no ciclo")


def iniciar() -> None:
    if _estado["iniciado"]:
        return
    _estado["iniciado"] = True
    threading.Thread(target=_loop, name="alertas-filas", daemon=True).start()


def situacao() -> dict[str, Any]:
    try:
        cfg = carregar()
    except PlanilhaErroBQ as exc:
        cfg = {**PADRAO, "erro": str(exc)}
    return {"config": cfg, "canais": sorted(canais()), "ultimo_ciclo": _estado["ultimo_ciclo"],
            "ultimo_erro": _estado["ultimo_erro"], "enviados": list(_enviados),
            "lojas_em_alerta": sorted(f for f, e in _lojas.items() if e["em_alerta"])}

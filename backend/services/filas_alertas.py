"""Alertas de fila alta das lojas no Microsoft Teams.

A cada minuto o portal confere o painel das filas (agente_filas.painel, em
memória) e, quando uma loja passa de um limite, posta um cartão num canal do
Teams. Os canais são webhooks do Teams (app Workflows, "Postar em um canal
quando uma solicitação de webhook for recebida") e ficam em variáveis de ambiente
do portal, porque quem tem a URL consegue postar no canal:
    TEAMS_WEBHOOK_URL       canal geral (recebe tudo que não tiver canal próprio)
    TEAMS_WEBHOOK_R1 ... R7 canal de cada regional (opcional)

Opcional (status_hora): no começo de cada hora, dentro do horário, o canal geral
recebe um status de todas as regionais (fila agora, entradas, atendidos, mkt x
orgânico e lojas em alerta), mesmo que nenhuma loja esteja em alerta.

Opcional (marcar_gerentes): o alerta de cada loja marca (@) o gerente e o
subgerente dela no Teams, pelo e-mail padrão gerente{filial}@ / subgerente{filial}@.

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
          "hora_inicio": 10, "hora_fim": 22, "status_hora": False,
          "marcar_gerentes": False}

_SCHEMA = (
    bigquery.SchemaField("ativo", "BOOLEAN"),
    bigquery.SchemaField("limite_fila", "INTEGER"),
    bigquery.SchemaField("limite_espera_min", "INTEGER"),
    bigquery.SchemaField("intervalo_min", "INTEGER"),
    bigquery.SchemaField("hora_inicio", "INTEGER"),
    bigquery.SchemaField("hora_fim", "INTEGER"),
    bigquery.SchemaField("status_hora", "BOOLEAN"),
    bigquery.SchemaField("marcar_gerentes", "BOOLEAN"),
    bigquery.SchemaField("alterado_por", "STRING"),
    bigquery.SchemaField("alterado_em", "TIMESTAMP"),
)

_lock = threading.Lock()
_cache: dict[str, Any] = {"lido_em": 0.0, "dados": None}
# filial -> {"em_alerta": bool, "avisado_em": epoch}
_lojas: dict[str, dict[str, Any]] = {}
_enviados: deque = deque(maxlen=50)
_estado = {"iniciado": False, "ultimo_ciclo": None, "ultimo_erro": None, "status_enviado": None}


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
            "status_hora": bool(dados.get("status_hora")),
            "marcar_gerentes": bool(dados.get("marcar_gerentes")),
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
            return {**PADRAO, **_cache["dados"]} if _cache["dados"] else dict(PADRAO)
        try:
            linhas = list(_cliente().list_rows(_tabela_id(), timeout=_TIMEOUT_S))
        except NotFound:
            linhas = []
        except Exception as exc:  # noqa: BLE001
            if _cache["lido_em"]:
                return {**PADRAO, **_cache["dados"]} if _cache["dados"] else dict(PADRAO)
            raise PlanilhaErroBQ(f"Falha ao ler os alertas no BigQuery: {exc}") from exc
        dados = None
        if linhas:
            dados = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in linhas[0].items()}
        _cache.update(dados=dados, lido_em=time.monotonic())
        return {**PADRAO, **dados} if dados else dict(PADRAO)


# --- Cartão do Teams ------------------------------------------------------------


def _mencoes(filial: str) -> tuple[str, list[dict[str, Any]]]:
    """Texto com @gerente e @subgerente da loja e as entidades que o Teams pede para marcar."""
    loja = agente_filas.carregar_mapa().get(filial)
    if not loja:
        return "", []
    texto, entidades = [], []
    for cargo, email in (("Gerente", loja.email_gerente), ("Subgerente", loja.email_subgerente)):
        marca = f"<at>{cargo} {filial}</at>"
        texto.append(marca)
        entidades.append({"type": "mention", "text": marca, "mentioned": {"id": email, "name": f"{cargo} {filial}"}})
    return " ".join(texto), entidades


def _cartao(titulo: str, linhas: list[str], link: str | None,
            mencoes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    corpo: list[dict[str, Any]] = [{"type": "TextBlock", "text": titulo, "weight": "Bolder", "size": "Medium",
                                    "wrap": True}]
    corpo += [{"type": "TextBlock", "text": l, "wrap": True, "spacing": "Small"} for l in linhas]
    conteudo: dict[str, Any] = {"$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                                "type": "AdaptiveCard", "version": "1.4", "body": corpo}
    if mencoes:
        conteudo["msteams"] = {"entities": mencoes}
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


# --- Status geral de hora em hora (canal geral) ---------------------------------


def _gerentes() -> dict[str, str]:
    """Regional -> primeiro nome do gerente regional (do mapa de lojas)."""
    try:
        mapa = agente_filas.carregar_mapa()
    except Exception:  # noqa: BLE001 - o status sai sem o nome
        return {}
    saida = {}
    for loja in mapa.values():
        if loja.regional and loja.gerente_regional and loja.regional not in saida:
            saida[loja.regional] = loja.gerente_regional.split()[0].title()
    return saida


def _resumo(t: dict[str, Any]) -> str:
    espera = f" (maior espera {_min(t.get('espera_mais_antiga_min'))})" if t["na_fila"] else ""
    return (f"{t['na_fila']} na fila agora{espera} · hoje "
            f"{t['entraram_hoje']} entraram ({t['entraram_campanha']} mkt · {t['entraram_organico']} orgânico), "
            f"{t['atendidos_hoje']} atendidos, espera média {_min(t.get('espera_media_min'))}")


def montar_status(painel: dict[str, Any], cfg: dict[str, Any], agora: datetime) -> tuple[str, list[str]]:
    gerentes = _gerentes()
    titulo = f"📊 Status das filas às {agora.astimezone(agente_filas.FUSO):%H:%M}"
    linhas = [f"**Todas as lojas:** {_resumo(painel['total_lojas'])}"]
    alerta = []
    for reg in painel.get("regionais", []):
        nome = reg["regional"] + (f" ({gerentes[reg['regional']]})" if reg["regional"] in gerentes else "")
        linhas.append(f"**{nome}:** {_resumo(reg['total'])}")
        alerta += [(reg["regional"], l) for l in reg["lojas"] if _em_alerta(l, cfg)]
    if alerta:
        alerta.sort(key=lambda x: (-x[1]["na_fila"], -(x[1].get("espera_mais_antiga_min") or 0)))
        lojas = "; ".join(f"{l['filial']} {l['loja']} ({reg}): {l['na_fila']} na fila, "
                          f"{_min(l.get('espera_mais_antiga_min'))}" for reg, l in alerta[:8])
        mais = f" e mais {len(alerta) - 8}" if len(alerta) > 8 else ""
        linhas.append(f"⚠️ **Em alerta agora ({len(alerta)}):** {lojas}{mais}")
    else:
        linhas.append("✅ Nenhuma loja acima do limite agora.")
    return titulo, linhas


def enviar_status(painel: dict[str, Any] | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    url = canais().get("geral")
    if not url:
        return {"enviados": [], "erros": ["Canal geral não configurado (TEAMS_WEBHOOK_URL)."]}
    cfg = cfg or carregar()
    painel = painel or agente_filas.painel(com_televendas=False)
    titulo, linhas = montar_status(painel, cfg, datetime.now(timezone.utc))
    erro = _postar(url, _cartao(titulo, linhas, _link()))
    _enviados.appendleft({"em": datetime.now(agente_filas.FUSO).isoformat(timespec="seconds"), "canal": "geral",
                          "lojas": ["status geral"], "erro": erro})
    if erro:
        _estado["ultimo_erro"] = erro
        log.warning("status: %s", erro)
        return {"enviados": [], "erros": [f"geral: {erro}"]}
    return {"enviados": ["geral"], "erros": []}


def status_devido(cfg: dict[str, Any], agora: datetime) -> str | None:
    """Chave da hora (ex. "2026-11-27 14") se o status desta hora ainda não saiu.
    Vai nos primeiros minutos de cada hora cheia, depois do início e até o fim do
    horário (com 10h-22h: 11h, 12h, ..., 22h - o das 22h fecha o dia)."""
    if not cfg.get("status_hora"):
        return None
    local = agora.astimezone(agente_filas.FUSO)
    if local.minute >= 5 or not int(cfg["hora_inicio"]) < local.hour <= int(cfg["hora_fim"]):
        return None
    chave = local.strftime("%Y-%m-%d %H")
    return None if chave == _estado["status_enviado"] else chave


def testar_marcacao(filial: str, usuario: str) -> dict[str, Any]:
    """Posta no canal da regional da loja um cartão marcando o gerente e o subgerente dela."""
    loja = agente_filas.carregar_mapa().get(str(filial).strip())
    if not loja:
        return {"enviados": [], "erros": [f"Loja {filial} não está no mapa de lojas."]}
    destinos = canais()
    canal = loja.regional if loja.regional in destinos else "geral"
    if canal not in destinos:
        return {"enviados": [], "erros": ["Nenhum canal configurado para essa loja."]}
    marca, entidades = _mencoes(loja.filial)
    cartao = _cartao(f"✅ Teste de marcação ({loja.filial} {agente_filas._nome_loja(loja.descricao)})",
                     [f"{marca}: teste dos alertas de fila enviado pelo portal do CRM por {usuario}. "
                      "Se o seu nome apareceu marcado, os avisos de fila alta da loja vão marcar vocês."],
                     _link(), entidades)
    erro = _postar(destinos[canal], cartao)
    return {"enviados": [] if erro else [canal], "erros": [f"{canal}: {erro}"] if erro else []}


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
        linhas, entidades = [], []
        for reg, l in sorted(itens, key=lambda x: -x[1]["na_fila"]):
            marca = ""
            if cfg.get("marcar_gerentes"):
                marca, ents = _mencoes(l["filial"])
                entidades += ents
            linhas.append(f"**{l['filial']} {l['loja']}** ({reg}): {l['na_fila']} na fila, mais antigo há "
                          f"{_min(l.get('espera_mais_antiga_min'))}{' · continua alta' if l['repetido'] else ''}"
                          f"{' · ' + marca if marca else ''}")
        titulo = "⚠️ Fila alta " + ("na loja" if len(itens) == 1 else f"em {len(itens)} lojas")
        rodape = (f"Limite: {cfg['limite_fila']} na fila ou {cfg['limite_espera_min']} min de espera. "
                  f"Novo aviso da mesma loja em {cfg['intervalo_min']} min se continuar.")
        erro = _postar(destinos[canal], _cartao(titulo, linhas + [f"_{rodape}_"], _link(), entidades))
        _enviados.appendleft({"em": datetime.now(agente_filas.FUSO).isoformat(timespec="seconds"), "canal": canal,
                              "lojas": [f"{l['filial']} {l['loja']}" for _, l in itens], "erro": erro})
        if erro:
            _estado["ultimo_erro"] = erro
            log.warning("alertas: %s", erro)


def ciclo() -> None:
    cfg = carregar()
    agora = datetime.now(timezone.utc)
    _estado["ultimo_ciclo"] = agora.astimezone(agente_filas.FUSO).isoformat(timespec="seconds")
    painel = None
    if cfg.get("ativo") and _dentro_do_horario(cfg, agora):
        painel = agente_filas.painel(com_televendas=False)
        avisar = verificar(cfg, painel, time.time())
        if avisar:
            _enviar(avisar, cfg)
    chave = status_devido(cfg, agora)
    if chave:
        _estado["status_enviado"] = chave  # marca antes: se falhar, não repete a cada minuto
        enviar_status(painel, cfg)


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

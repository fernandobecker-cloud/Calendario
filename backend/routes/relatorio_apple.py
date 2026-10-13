"""Relatorio da Apple (FY26 Report Campaign Template, aba CRM) - uma linha por
disparo dos periodos NPI, nas colunas A..AB do template.

Receita (T/V) e a MESMA da aba Resultados NPI: `calcular_npi_canal` rodado
por periodo, so que quebrado por disparo (ver `disparos` la) - a soma das
linhas de um canal bate com a celula daquele canal na aba NPI (menos o
"Sem atribuicao", que nao e disparo). Entram todas as campanhas com envio
dentro dos periodos escolhidos ou com receita atribuida neles (decisao do
usuario: "todas dentro dos periodos NPI"), mais os templates do Omnichat
marcados na tela.

Metricas (J..Q) vem das tabelas de evento da Emarsys por campaign_id (Email,
SMS, WhatsApp nativo - cujo campaign_id na atribuicao e o message_id das
conversation_*, confirmado 8/8 em 2026-10 - e Web Push) e do dados_omni por
template. Contagens sao de contatos/conversas unicos. Convencoes:
- SMS "entregue" = status ACCEPTED no sms_send_reports (mesma regra do resto
  do portal). SMS nao tem abertura.
- CTR = cliques / aberturas (pedido do usuario).
- WhatsApp nativo nao exporta clique nem opt-out.
- Investimento = envios x custo unitario do canal (planilha do usuario).

Colunas manuais (C audiencia, E asset, F destino, G SO, R leads, AB) saem
vazias; I (tamanho da audiencia) sai pre-preenchida com contatos unicos
enviados.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from google.cloud import bigquery
from pydantic import BaseModel

from backend.event_sources import run_bigquery_records
from backend.routes.npi_resultados import npi_db
from backend.routes.open_data import (
    BASE_VENDAS_BQ_PROJECT,
    EMARSYS_OPEN_DATA_DATASET,
    EMARSYS_OPEN_DATA_LOCATION,
    EMARSYS_OPEN_DATA_PROJECT_ID,
    _quote_identifier,
    calcular_npi_canal,
)

router = APIRouter(prefix="/api/relatorio-apple", tags=["relatorio-apple"])

# Custo por envio (R$), da planilha do usuario:
# =SE(H2="email";J2*0,0019;SE(H2="whatsapp";J2*0,65;SE(H2="WebPush";J2*0,0019;
#   SE(H2="RCS";J2*0,18;SE(H2="SMS";J2*0,04;0)))))
# WhatsApp nativo e Omnichat custam igual (confirmado com o usuario).
CUSTO_POR_ENVIO = {
    "Email": 0.0019,
    "WhatsApp": 0.65,
    "WebPush": 0.0019,
    "RCS": 0.18,
    "SMS": 0.04,
}

# canal interno (calcular_npi_canal / metricas) -> formato da coluna H
FORMATO = {
    "email": "Email",
    "sms": "SMS",
    "whatsapp_nativo": "WhatsApp",
    "whatsapp_omni": "WhatsApp",
    "web_push": "WebPush",
    "rcs": "RCS",
}

_TZ = "America/Sao_Paulo"


def _t(name: str) -> str:
    """Tabela do Open Data (todas tem o sufixo do id da conta, igual ao dataset)."""
    project = _quote_identifier(EMARSYS_OPEN_DATA_PROJECT_ID)
    dataset = _quote_identifier(EMARSYS_OPEN_DATA_DATASET)
    suffix = EMARSYS_OPEN_DATA_DATASET.rsplit("_", 1)[-1]
    return f"`{project}.{dataset}.{name}_{suffix}`"


def _canal_de(canal_npi: str) -> str:
    """calcular_npi_canal devolve canais extras em minusculo cru - a Emarsys
    pode mandar web push como WEBPUSH ou WEB_PUSH."""
    canal = canal_npi.replace("-", "_").lower()
    return "web_push" if canal == "webpush" else canal


def _build_emarsys_metricas_sql() -> str:
    """Uma linha por campanha dos canais da Emarsys. Campanha entra se teve
    envio entre @start e @end ou se esta nas listas de ids com receita.
    Eventos posteriores (abertura/clique/bounce) olham ate @end + 15 dias."""
    janela_envio = (
        "DATE(partitiontime) BETWEEN DATE_SUB(@start, INTERVAL 2 DAY) AND DATE_ADD(@end, INTERVAL 2 DAY) "
        f"AND DATE(event_time, '{_TZ}') BETWEEN @start AND @end"
    )
    janela_larga = "DATE(partitiontime) BETWEEN DATE_SUB(@start, INTERVAL 45 DAY) AND DATE_ADD(@end, INTERVAL 15 DAY)"

    def contagem(tabela: str, chave: str, ids_cte: str, extra: str = "", distinto: str = "contact_id") -> str:
        return f"""
  SELECT CAST({chave} AS STRING) AS id, COUNT(DISTINCT {distinto}) AS n
  FROM {_t(tabela)}
  WHERE {janela_larga} AND CAST({chave} AS STRING) IN (SELECT id FROM {ids_cte}) {extra}
  GROUP BY 1"""

    return f"""
WITH
email_ids AS (
  SELECT DISTINCT CAST(campaign_id AS STRING) AS id FROM {_t('email_sends')} WHERE {janela_envio}
  UNION DISTINCT SELECT id FROM UNNEST(@email_ids) AS id
),
email_envios AS (
  SELECT CAST(campaign_id AS STRING) AS id, MIN(DATE(event_time, '{_TZ}')) AS data, COUNT(DISTINCT contact_id) AS n
  FROM {_t('email_sends')}
  WHERE {janela_larga} AND CAST(campaign_id AS STRING) IN (SELECT id FROM email_ids)
  GROUP BY 1
),
email_aberturas AS ({contagem('email_opens', 'campaign_id', 'email_ids')}),
email_cliques AS ({contagem('email_clicks', 'campaign_id', 'email_ids')}),
email_bounces AS ({contagem('email_bounces', 'campaign_id', 'email_ids')}),
email_optout AS ({contagem('email_unsubscribes', 'campaign_id', 'email_ids')}),
email_nomes AS (
  SELECT CAST(campaign_id AS STRING) AS id,
    ARRAY_AGG(STRUCT(name, subject) ORDER BY event_time DESC LIMIT 1)[OFFSET(0)] AS c
  FROM {_t('email_campaigns_v2')}
  WHERE CAST(campaign_id AS STRING) IN (SELECT id FROM email_ids)
  GROUP BY 1
),
sms_ids AS (
  SELECT DISTINCT CAST(campaign_id AS STRING) AS id FROM {_t('sms_sends')} WHERE {janela_envio}
  UNION DISTINCT SELECT id FROM UNNEST(@sms_ids) AS id
),
sms_envios AS (
  SELECT CAST(campaign_id AS STRING) AS id, MIN(DATE(event_time, '{_TZ}')) AS data, COUNT(DISTINCT contact_id) AS n
  FROM {_t('sms_sends')}
  WHERE {janela_larga} AND CAST(campaign_id AS STRING) IN (SELECT id FROM sms_ids)
  GROUP BY 1
),
sms_entregues AS ({contagem('sms_send_reports', 'campaign_id', 'sms_ids',
                            "AND UPPER(TRIM(COALESCE(CAST(status AS STRING), ''))) = 'ACCEPTED'")}),
sms_cliques AS ({contagem('sms_clicks', 'campaign_id', 'sms_ids',
                          "AND LOWER(COALESCE(CAST(is_dry_run AS STRING), 'false')) NOT IN ('true', '1')")}),
sms_optout AS (
  SELECT CAST(campaign_id AS STRING) AS id, COUNT(DISTINCT contact_id) AS n
  FROM {_t('sms_unsubscribes')}
  WHERE {janela_larga} AND CAST(campaign_id AS STRING) IN (SELECT id FROM sms_ids)
  GROUP BY 1
),
sms_nomes AS (
  SELECT CAST(campaign_id AS STRING) AS id, ARRAY_AGG(name IGNORE NULLS ORDER BY event_time DESC LIMIT 1)[SAFE_OFFSET(0)] AS nome
  FROM {_t('sms_campaigns')}
  WHERE CAST(campaign_id AS STRING) IN (SELECT id FROM sms_ids)
  GROUP BY 1
),
wa_ids AS (
  SELECT DISTINCT CAST(message_id AS STRING) AS id FROM {_t('conversation_sends')}
  WHERE DATE(event_time, '{_TZ}') BETWEEN @start AND @end
  UNION DISTINCT SELECT id FROM UNNEST(@wa_ids) AS id
),
wa_envios AS (
  SELECT CAST(message_id AS STRING) AS id, MIN(DATE(event_time, '{_TZ}')) AS data, COUNT(DISTINCT conversation_id) AS n
  FROM {_t('conversation_sends')}
  WHERE DATE(event_time) BETWEEN DATE_SUB(@start, INTERVAL 45 DAY) AND DATE_ADD(@end, INTERVAL 15 DAY)
    AND CAST(message_id AS STRING) IN (SELECT id FROM wa_ids)
  GROUP BY 1
),
wa_entregues AS (
  SELECT CAST(message_id AS STRING) AS id, COUNT(DISTINCT conversation_id) AS n
  FROM {_t('conversation_deliveries')}
  WHERE DATE(event_time) BETWEEN DATE_SUB(@start, INTERVAL 45 DAY) AND DATE_ADD(@end, INTERVAL 15 DAY)
    AND CAST(message_id AS STRING) IN (SELECT id FROM wa_ids) AND UPPER(CAST(status AS STRING)) = 'DELIVERED'
  GROUP BY 1
),
wa_lidas AS (
  SELECT CAST(message_id AS STRING) AS id, COUNT(DISTINCT conversation_id) AS n
  FROM {_t('conversation_opens')}
  WHERE DATE(event_time) BETWEEN DATE_SUB(@start, INTERVAL 45 DAY) AND DATE_ADD(@end, INTERVAL 15 DAY)
    AND CAST(message_id AS STRING) IN (SELECT id FROM wa_ids)
  GROUP BY 1
),
wa_nomes AS (
  SELECT CAST(message_id AS STRING) AS id,
    ARRAY_AGG(STRUCT(name, channel) ORDER BY event_time DESC LIMIT 1)[OFFSET(0)] AS c
  FROM {_t('conversation_messages')}
  WHERE CAST(message_id AS STRING) IN (SELECT id FROM wa_ids)
  GROUP BY 1
),
wp_ids AS (
  SELECT DISTINCT CAST(campaign_id AS STRING) AS id FROM {_t('web_push_sends')} WHERE {janela_envio}
  UNION DISTINCT SELECT id FROM UNNEST(@wp_ids) AS id
),
wp_envios AS (
  SELECT CAST(campaign_id AS STRING) AS id, MIN(DATE(event_time, '{_TZ}')) AS data, COUNT(DISTINCT contact_id) AS n
  FROM {_t('web_push_sends')}
  WHERE {janela_larga} AND CAST(campaign_id AS STRING) IN (SELECT id FROM wp_ids)
  GROUP BY 1
),
wp_cliques AS ({contagem('web_push_clicks', 'campaign_id', 'wp_ids')})

SELECT 'email' AS canal, i.id, n.c.name AS nome, n.c.subject AS assunto, e.data,
  e.n AS envios, e.n - IFNULL(b.n, 0) AS entregues, a.n AS aberturas, c.n AS cliques, o.n AS optout
FROM email_ids i
LEFT JOIN email_envios e USING (id) LEFT JOIN email_bounces b USING (id) LEFT JOIN email_aberturas a USING (id)
LEFT JOIN email_cliques c USING (id) LEFT JOIN email_optout o USING (id) LEFT JOIN email_nomes n USING (id)
UNION ALL
SELECT 'sms', i.id, n.nome, CAST(NULL AS STRING), e.data,
  e.n, d.n, CAST(NULL AS INT64), c.n, o.n
FROM sms_ids i
LEFT JOIN sms_envios e USING (id) LEFT JOIN sms_entregues d USING (id) LEFT JOIN sms_cliques c USING (id)
LEFT JOIN sms_optout o USING (id) LEFT JOIN sms_nomes n USING (id)
UNION ALL
SELECT IF(UPPER(n.c.channel) = 'RCS', 'rcs', 'whatsapp_nativo'), i.id, n.c.name, CAST(NULL AS STRING), e.data,
  e.n, d.n, l.n, CAST(NULL AS INT64), CAST(NULL AS INT64)
FROM wa_ids i
LEFT JOIN wa_envios e USING (id) LEFT JOIN wa_entregues d USING (id) LEFT JOIN wa_lidas l USING (id)
LEFT JOIN wa_nomes n USING (id)
UNION ALL
SELECT 'web_push', i.id, CAST(NULL AS STRING), CAST(NULL AS STRING), e.data,
  e.n, e.n, CAST(NULL AS INT64), c.n, CAST(NULL AS INT64)
FROM wp_ids i
LEFT JOIN wp_envios e USING (id) LEFT JOIN wp_cliques c USING (id)
""".strip()


def _build_omni_metricas_sql() -> str:
    """Uma linha por template do Omnichat. Mesma janela de toques do calculo
    NPI ([inicio - janela, fim]), pra pegar o disparo que gerou a receita."""
    omni_table = f"`{BASE_VENDAS_BQ_PROJECT}.apuracao_npi26.dados_omni`"
    flag = "LOWER(CAST({c} AS STRING)) IN ('1', 'true')"
    return f"""
SELECT
  template_title AS id,
  MIN(DATE(campaign_message_created_at)) AS data,
  COUNT(DISTINCT campaign_message_id) AS envios,
  COUNT(DISTINCT phone) AS audiencia,
  COUNT(DISTINCT IF({flag.format(c='delivered')}, campaign_message_id, NULL)) AS entregues,
  COUNT(DISTINCT IF({flag.format(c='read')}, campaign_message_id, NULL)) AS aberturas,
  COUNT(DISTINCT IF({flag.format(c='click')}, campaign_message_id, NULL)) AS cliques
FROM {omni_table}
WHERE template_title IN UNNEST(@template_titles)
  AND DATE(campaign_message_created_at) BETWEEN DATE_SUB(@start, INTERVAL @janela_dias DAY) AND @end
GROUP BY template_title
""".strip()


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or not b:
        return None
    return a / b


def montar_relatorio(periodos: list[dict[str, Any]], template_titles: list[str], janela_dias: int) -> dict[str, Any]:
    start = min(p["start_date"] for p in periodos)
    end = max(p["end_date"] for p in periodos)

    # 1) Receita por disparo - mesmo calculo da aba NPI, periodo a periodo.
    receita: dict[tuple[str, str], dict[str, Any]] = {}
    canal_totais: dict[str, float] = {}
    for p in periodos:
        calc = calcular_npi_canal(p["start_date"], p["end_date"], template_titles, janela_dias)
        for canal, valor in calc["canal_totais"].items():
            canal_totais[canal] = round(canal_totais.get(canal, 0.0) + valor, 2)
        for d in calc["disparos"]:
            key = (_canal_de(d["canal"]), d["disparo_id"])
            acc = receita.setdefault(key, {
                "receita": 0.0, "receita_apple": 0.0, "receita_sem_detalhe": 0.0,
                "unidades_apple": 0.0, "unidades_outros": 0.0, "pedidos": set(),
            })
            for campo in ("receita", "receita_apple", "receita_sem_detalhe", "unidades_apple", "unidades_outros"):
                acc[campo] += d[campo]
            acc["pedidos"] |= d["pedidos"]

    def ids_com_receita(canal: str) -> list[str]:
        return sorted(i for (c, i) in receita if c == canal and i)

    # 2) Metricas por disparo.
    metricas = run_bigquery_records(
        _build_emarsys_metricas_sql(),
        EMARSYS_OPEN_DATA_PROJECT_ID,
        location=EMARSYS_OPEN_DATA_LOCATION or None,
        timeout=120,
        params=[
            bigquery.ScalarQueryParameter("start", "DATE", start),
            bigquery.ScalarQueryParameter("end", "DATE", end),
            bigquery.ArrayQueryParameter("email_ids", "STRING", ids_com_receita("email")),
            bigquery.ArrayQueryParameter("sms_ids", "STRING", ids_com_receita("sms")),
            bigquery.ArrayQueryParameter(
                "wa_ids", "STRING", sorted(set(ids_com_receita("whatsapp_nativo")) | set(ids_com_receita("rcs"))),
            ),
            bigquery.ArrayQueryParameter("wp_ids", "STRING", ids_com_receita("web_push")),
        ],
    )
    if template_titles:
        omni = run_bigquery_records(
            _build_omni_metricas_sql(),
            BASE_VENDAS_BQ_PROJECT,
            location=EMARSYS_OPEN_DATA_LOCATION or None,
            timeout=60,
            params=[
                bigquery.ArrayQueryParameter("template_titles", "STRING", template_titles),
                bigquery.ScalarQueryParameter("start", "DATE", start),
                bigquery.ScalarQueryParameter("end", "DATE", end),
                bigquery.ScalarQueryParameter("janela_dias", "INT64", janela_dias),
            ],
        )
        for r in omni:
            metricas.append({**r, "canal": "whatsapp_omni", "nome": r["id"], "assunto": None, "optout": None})

    # 3) Junta metricas + receita (disparo com receita mas sem metrica - ex
    # canal que a Emarsys credita mas nao exporta envio - tambem vira linha).
    por_chave = {(r["canal"], str(r["id"])): r for r in metricas}
    for key in receita:
        por_chave.setdefault(key, {"canal": key[0], "id": key[1]})

    linhas = []
    for (canal, disparo_id), m in por_chave.items():
        r = receita.get((canal, disparo_id), {})
        formato = FORMATO.get(canal, canal)
        envios = m.get("envios")
        entregues = m.get("entregues")
        aberturas = m.get("aberturas")
        cliques = m.get("cliques")
        optout = m.get("optout")
        receita_total = r.get("receita", 0.0)
        receita_apple = r.get("receita_apple", 0.0)
        receita_outros = receita_total - receita_apple - r.get("receita_sem_detalhe", 0.0)
        investimento = (envios or 0) * CUSTO_POR_ENVIO.get(formato, 0.0)
        pedidos = len(r.get("pedidos", ()))
        data = m.get("data")

        contexto = []
        if r.get("receita_sem_detalhe"):
            contexto.append(f"R$ {r['receita_sem_detalhe']:.2f} de receita sem detalhe de produto (fora de T e V)")
        if not envios:
            contexto.append("Sem envio encontrado no período - só receita atribuída")

        linhas.append({
            "canal": canal,
            "disparo_id": disparo_id,
            "nome_campanha": m.get("nome") or (disparo_id if canal == "whatsapp_omni" else f"Campanha #{disparo_id}"),
            "A_parceiro": "iPlace",
            "B_data_disparo": data.isoformat() if isinstance(data, date) else data,
            "C_audiencia": None,
            "D_texto_assunto": m.get("assunto") or m.get("nome"),
            "E_asset": None,
            "F_destino": None,
            "G_sistema_operacional": None,
            "H_formato": formato,
            "I_tamanho_audiencia": m.get("audiencia", envios),
            "J_envios": envios,
            "K_entregues": entregues,
            "L_bounce": _div((envios or 0) - (entregues or 0), envios) if entregues is not None else None,
            "M_aberturas": aberturas,
            "N_open_rate": _div(aberturas, entregues),
            "O_cliques": cliques,
            "P_ctr": _div(cliques, aberturas),
            "Q_optout": _div(optout, entregues),
            "R_leads": None,
            "S_unidades_apple": round(r.get("unidades_apple", 0.0)),
            "T_receita_apple": round(receita_apple, 2),
            "U_unidades_nao_apple": round(r.get("unidades_outros", 0.0)),
            "V_receita_nao_apple": round(receita_outros, 2),
            "W_cpm": _div(investimento * 1000, envios),
            "X_cpc": _div(investimento, cliques),
            "Y_cpa": _div(investimento, pedidos),
            "Z_roas": _div(receita_apple + receita_outros, investimento),
            "AA_investimento": round(investimento, 2),
            "AB_contexto": "; ".join(contexto) or None,
            "pedidos_atribuidos": pedidos,
            "receita_atribuida": round(receita_total, 2),
        })

    linhas.sort(key=lambda l: (l["B_data_disparo"] or "9999", l["H_formato"], l["nome_campanha"]))

    # Conferencia com a aba NPI: soma das linhas por canal x canal_totais.
    conferencia = {}
    for canal, total in canal_totais.items():
        if canal == "sem_atribuicao":
            continue
        soma = round(sum(l["receita_atribuida"] for l in linhas if l["canal"] == _canal_de(canal)), 2)
        conferencia[canal] = {"aba_npi": total, "relatorio": soma, "confere": abs(soma - total) < 0.05}

    return {
        "inicio": start,
        "fim": end,
        "linhas": linhas,
        "conferencia_npi": conferencia,
        "sem_atribuicao": canal_totais.get("sem_atribuicao", 0.0),
    }


class RelatorioPayload(BaseModel):
    periodo_ids: list[int]
    template_titles: list[str] = []
    janela_dias: int = 7


@router.post("/npi")
def relatorio_npi(request: Request, payload: RelatorioPayload) -> dict[str, Any]:
    if getattr(getattr(request.state, "auth_user", None), "role", None) != "admin":
        raise HTTPException(status_code=403, detail="Apenas administradores podem gerar o relatorio da Apple")
    periodos = [p for p in npi_db.get_npi_periodos() if p["id"] in set(payload.periodo_ids)]
    if not periodos:
        raise HTTPException(status_code=400, detail="Escolha pelo menos um periodo NPI.")
    return montar_relatorio(periodos, payload.template_titles, payload.janela_dias)

"""Relatorio de funil de CRM usando Google Analytics Data API."""

from __future__ import annotations

from datetime import date
from typing import Any

from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    FilterExpressionList,
    Metric,
    RunReportRequest,
)

from backend.ga4_client import (
    _build_crm_filter,
    _get_ga4_client,
    _month_date_range,
    _resolve_property_resource,
)

CRM_FUNNEL_EVENTS = {
    "session_start": "sessions",
    "view_item": "product_view",
    "add_to_cart": "add_to_cart",
    "begin_checkout": "checkout",
    "purchase": "purchase",
}


def _safe_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def get_crm_funnel(property_id: str, year: int | None = None, month: int | None = None) -> dict[str, Any]:
    """
    Retorna funil de CRM para um mes/ano.

    year/month opcionais; quando ausentes usa o mes atual.
    """
    today = date.today()
    target_year = year if year is not None else today.year
    target_month = month if month is not None else today.month

    if target_month < 1 or target_month > 12:
        raise RuntimeError("Mes invalido. Use valores entre 1 e 12")
    if target_year < 2000 or target_year > 2100:
        raise RuntimeError("Ano invalido")

    property_resource = _resolve_property_resource(property_id)
    start_date, end_date = _month_date_range(target_year, target_month)

    event_filter = FilterExpression(
        filter=Filter(
            field_name="eventName",
            in_list_filter=Filter.InListFilter(values=list(CRM_FUNNEL_EVENTS.keys()), case_sensitive=False),
        )
    )

    request = RunReportRequest(
        property=property_resource,
        dimensions=[Dimension(name="eventName")],
        metrics=[Metric(name="eventCount")],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=FilterExpression(
            and_group=FilterExpressionList(expressions=[_build_crm_filter(), event_filter])
        ),
    )

    client = _get_ga4_client()
    try:
        response = client.run_report(request=request, timeout=30)
    except Exception as exc:
        error_type = exc.__class__.__name__
        raise RuntimeError(f"Falha ao consultar Google Analytics Data API [{error_type}]: {exc}") from exc

    funnel = {
        "sessions": 0,
        "product_view": 0,
        "add_to_cart": 0,
        "checkout": 0,
        "purchase": 0,
    }

    for row in response.rows:
        if not row.dimension_values or not row.metric_values:
            continue
        event_name = row.dimension_values[0].value
        metric_value = int(float(row.metric_values[0].value or 0))
        mapped_key = CRM_FUNNEL_EVENTS.get(event_name)
        if mapped_key:
            funnel[mapped_key] += metric_value

    sessions = float(funnel["sessions"])
    conversion_rates = {
        "view_rate": _safe_rate(funnel["product_view"], sessions),
        "cart_rate": _safe_rate(funnel["add_to_cart"], sessions),
        "checkout_rate": _safe_rate(funnel["checkout"], sessions),
        "purchase_rate": _safe_rate(funnel["purchase"], sessions),
    }

    return {
        **funnel,
        "conversion_rates": conversion_rates,
    }

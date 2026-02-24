"""Cliente GA4 para consultas via Google Analytics Data API."""

from __future__ import annotations

import calendar
import json
import os
from datetime import date, timedelta
from typing import Any

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    FilterExpressionList,
    Metric,
    RunReportRequest,
)
from google.oauth2.service_account import Credentials

GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT", "").strip()
CRM_REGEX = r"(?i).*(email|crm|sms|whatsapp|push).*"
GA4_TIMEOUT_SECONDS = 30


def _load_service_account_info() -> dict[str, Any]:
    if not GOOGLE_SERVICE_ACCOUNT:
        raise RuntimeError("Variavel GOOGLE_SERVICE_ACCOUNT nao configurada")

    try:
        return json.loads(GOOGLE_SERVICE_ACCOUNT)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT contem JSON invalido") from exc


def _get_ga4_client() -> BetaAnalyticsDataClient:
    service_account_info = _load_service_account_info()
    scopes = ["https://www.googleapis.com/auth/analytics.readonly"]
    credentials = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    return BetaAnalyticsDataClient(credentials=credentials)


def get_sessions_yesterday(property_id: str) -> dict[str, int]:
    """Retorna sessoes e usuarios de ontem para uma propriedade GA4."""
    if not property_id or not str(property_id).strip():
        raise RuntimeError("GA4 property_id nao informado")

    ga_property = str(property_id).strip()
    if ga_property.startswith("properties/"):
        property_resource = ga_property
    else:
        property_resource = f"properties/{ga_property}"

    client = _get_ga4_client()

    try:
        request = RunReportRequest(
            property=property_resource,
            date_ranges=[DateRange(start_date="yesterday", end_date="yesterday")],
            metrics=[Metric(name="sessions"), Metric(name="totalUsers")],
        )
        response = client.run_report(request=request, timeout=GA4_TIMEOUT_SECONDS)
    except Exception as exc:
        error_type = exc.__class__.__name__
        raise RuntimeError(f"Falha ao consultar Google Analytics Data API [{error_type}]: {exc}") from exc

    sessions = 0
    users = 0
    if response.rows:
        first_row = response.rows[0]
        if len(first_row.metric_values) >= 2:
            sessions = int(first_row.metric_values[0].value or 0)
            users = int(first_row.metric_values[1].value or 0)

    return {"sessions": sessions, "users": users}


def _resolve_property_resource(property_id: str) -> str:
    if not property_id or not str(property_id).strip():
        raise RuntimeError("GA4 property_id nao informado")

    ga_property = str(property_id).strip()
    if ga_property.startswith("properties/"):
        return ga_property
    return f"properties/{ga_property}"


def _month_date_range(target_year: int, target_month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(target_year, target_month)[1]
    start_date = date(target_year, target_month, 1).isoformat()
    end_date = date(target_year, target_month, last_day).isoformat()
    return start_date, end_date


def _build_crm_filter() -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name="sessionSourceMedium",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                value=CRM_REGEX,
            ),
        )
    )


def _build_first_user_crm_filter() -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name="firstUserSourceMedium",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                value=CRM_REGEX,
            ),
        )
    )


def _build_in_list_filter(field_name: str, values: list[str]) -> FilterExpression:
    return FilterExpression(
        filter=Filter(
            field_name=field_name,
            in_list_filter=Filter.InListFilter(values=values, case_sensitive=False),
        )
    )


def _date_list_yyyymmdd(start_date: str, end_date: str) -> list[str]:
    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    days = (end - start).days
    if days < 0:
        raise RuntimeError("Periodo invalido: start deve ser menor ou igual a end")
    return [(start + timedelta(days=i)).strftime("%Y%m%d") for i in range(days + 1)]


def _run_report(request: RunReportRequest, client: BetaAnalyticsDataClient):
    try:
        return client.run_report(request=request, timeout=GA4_TIMEOUT_SECONDS)
    except Exception as exc:
        error_type = exc.__class__.__name__
        raise RuntimeError(f"Falha ao consultar Google Analytics Data API [{error_type}]: {exc}") from exc


def _run_crm_report(
    client: BetaAnalyticsDataClient, property_resource: str, start_date: str, end_date: str
) -> dict[str, int | float]:
    request = RunReportRequest(
        property=property_resource,
        dimensions=[Dimension(name="sessionSourceMedium")],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="transactions"),
            Metric(name="purchaseRevenue"),
        ],
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimension_filter=_build_crm_filter(),
    )
    response = _run_report(request, client)

    sessions = 0
    users = 0
    transactions = 0
    purchase_revenue = 0.0

    for row in response.rows:
        metric_values = row.metric_values
        if len(metric_values) >= 4:
            sessions += int(metric_values[0].value or 0)
            users += int(metric_values[1].value or 0)
            transactions += int(metric_values[2].value or 0)
            purchase_revenue += float(metric_values[3].value or 0.0)

    return {
        "sessions": sessions,
        "totalUsers": users,
        "transactions": transactions,
        "purchaseRevenue": purchase_revenue,
    }


def _percentage_variation(current: int | float, previous: int | float) -> float | None:
    if previous == 0:
        if current == 0:
            return 0.0
        return None
    return round(((current - previous) / previous) * 100, 2)


def get_crm_monthly_report(property_id: str, year: int, month: int) -> dict[str, Any]:
    """Compara CRM do mes atual vs mesmo mes do ano anterior."""
    if month < 1 or month > 12:
        raise RuntimeError("Mes invalido. Use valores entre 1 e 12")
    if year < 2000 or year > 2100:
        raise RuntimeError("Ano invalido")

    property_resource = _resolve_property_resource(property_id)
    client = _get_ga4_client()

    current_start, current_end = _month_date_range(year, month)
    previous_start, previous_end = _month_date_range(year - 1, month)

    current_year = _run_crm_report(client, property_resource, current_start, current_end)
    last_year = _run_crm_report(client, property_resource, previous_start, previous_end)

    variation = {
        "sessions": _percentage_variation(current_year["sessions"], last_year["sessions"]),
        "totalUsers": _percentage_variation(current_year["totalUsers"], last_year["totalUsers"]),
        "transactions": _percentage_variation(current_year["transactions"], last_year["transactions"]),
        "purchaseRevenue": _percentage_variation(current_year["purchaseRevenue"], last_year["purchaseRevenue"]),
    }

    return {
        "current_year": current_year,
        "last_year": last_year,
        "variation": variation,
    }


def _validate_iso_date(date_text: str) -> str:
    try:
        return date.fromisoformat(date_text).isoformat()
    except ValueError as exc:
        raise RuntimeError("Data invalida. Use o formato YYYY-MM-DD") from exc


def get_crm_assisted_conversions(property_id: str, start_date: str, end_date: str) -> dict[str, int | float]:
    """
    Estima conversoes assistidas por CRM.

    Observacao: GA4 Data API nao expoe jornada individual completa no endpoint run_report.
    Esta implementacao usa um proxy de assistencia:
    - usuarios/sessoes CRM por sessionSourceMedium
    - conversoes/receita de usuarios com firstUserSourceMedium CRM em sessoes nao-CRM
    """
    start = _validate_iso_date(start_date)
    end = _validate_iso_date(end_date)
    property_resource = _resolve_property_resource(property_id)
    client = _get_ga4_client()

    # Consulta principal de CRM com dimensoes solicitadas.
    crm_request = RunReportRequest(
        property=property_resource,
        dimensions=[
            Dimension(name="sessionSourceMedium"),
            Dimension(name="date"),
            Dimension(name="sessionCampaignName"),
        ],
        metrics=[
            Metric(name="sessions"),
            Metric(name="totalUsers"),
            Metric(name="conversions"),
            Metric(name="purchaseRevenue"),
        ],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimension_filter=_build_crm_filter(),
    )
    crm_response = _run_report(crm_request, client)

    crm_sessions = 0
    # totalUsers em linhas dimensionadas pode duplicar usuarios; usamos max por linha como proxy conservador.
    crm_users = 0
    for row in crm_response.rows:
        values = row.metric_values
        if len(values) >= 2:
            crm_sessions += int(values[0].value or 0)
            crm_users = max(crm_users, int(values[1].value or 0))

    # Assistencia: usuarios de origem CRM convertendo em sessoes nao CRM.
    assisted_filter = FilterExpression(
        and_group=FilterExpressionList(
            expressions=[
                _build_first_user_crm_filter(),
                FilterExpression(not_expression=_build_crm_filter()),
            ]
        )
    )
    assisted_request = RunReportRequest(
        property=property_resource,
        dimensions=[Dimension(name="sessionSourceMedium"), Dimension(name="date"), Dimension(name="sessionCampaignName")],
        metrics=[Metric(name="conversions"), Metric(name="purchaseRevenue")],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimension_filter=assisted_filter,
    )
    assisted_response = _run_report(assisted_request, client)

    assisted_purchases = 0
    assisted_revenue = 0.0
    for row in assisted_response.rows:
        values = row.metric_values
        if len(values) >= 2:
            assisted_purchases += int(values[0].value or 0)
            assisted_revenue += float(values[1].value or 0.0)

    return {
        "crm_sessions": crm_sessions,
        "crm_users": crm_users,
        "assisted_purchases": assisted_purchases,
        "assisted_revenue": round(assisted_revenue, 2),
    }


def get_crm_ltv(property_id: str, start_date: str, end_date: str) -> dict[str, int | float]:
    """
    Calcula LTV da coorte CRM com firstSessionDate no periodo.
    """
    start = _validate_iso_date(start_date)
    end = _validate_iso_date(end_date)
    today_date = date.today()
    start_date_obj = date.fromisoformat(start)
    today = today_date.isoformat()

    # Periodo totalmente no futuro: retorna sem dados em vez de erro da API.
    if start_date_obj > today_date:
        return {
            "crm_new_users": 0,
            "total_revenue_from_crm_users": 0.0,
            "crm_ltv": 0.0,
        }
    property_resource = _resolve_property_resource(property_id)
    client = _get_ga4_client()

    cohort_filter = FilterExpression(
        and_group=FilterExpressionList(
            expressions=[
                _build_first_user_crm_filter(),
                _build_in_list_filter("firstSessionDate", _date_list_yyyymmdd(start, end)),
            ]
        )
    )

    # Novos usuarios CRM na janela de aquisicao.
    acquired_request = RunReportRequest(
        property=property_resource,
        metrics=[Metric(name="totalUsers")],
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimension_filter=cohort_filter,
    )
    acquired_response = _run_report(acquired_request, client)
    crm_new_users = 0
    if acquired_response.rows and acquired_response.rows[0].metric_values:
        crm_new_users = int(acquired_response.rows[0].metric_values[0].value or 0)

    # Receita total dessa coorte desde a aquisicao ate hoje.
    revenue_request = RunReportRequest(
        property=property_resource,
        metrics=[Metric(name="purchaseRevenue")],
        date_ranges=[DateRange(start_date=start, end_date=today)],
        dimension_filter=cohort_filter,
    )
    revenue_response = _run_report(revenue_request, client)
    total_revenue = 0.0
    if revenue_response.rows and revenue_response.rows[0].metric_values:
        total_revenue = float(revenue_response.rows[0].metric_values[0].value or 0.0)

    crm_ltv = 0.0
    if crm_new_users > 0:
        crm_ltv = total_revenue / crm_new_users

    return {
        "crm_new_users": crm_new_users,
        "total_revenue_from_crm_users": round(total_revenue, 2),
        "crm_ltv": round(crm_ltv, 2),
    }

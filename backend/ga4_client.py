"""Cliente GA4 para consultas via Google Analytics Data API."""

from __future__ import annotations

import calendar
import json
import os
from datetime import date
from typing import Any

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Filter,
    FilterExpression,
    Metric,
    RunReportRequest,
)
from google.oauth2.service_account import Credentials

GOOGLE_SERVICE_ACCOUNT = os.getenv("GOOGLE_SERVICE_ACCOUNT", "").strip()


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
        response = client.run_report(request=request)
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
            string_filter=Filter.StringFilter(match_type=Filter.StringFilter.MatchType.FULL_REGEXP, value="(?i).*(email|crm|sms|whatsapp|push).*"),
        )
    )


def _run_crm_report(
    client: BetaAnalyticsDataClient, property_resource: str, start_date: str, end_date: str
) -> dict[str, int | float]:
    try:
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
        response = client.run_report(request=request)
    except Exception as exc:
        error_type = exc.__class__.__name__
        raise RuntimeError(f"Falha ao consultar Google Analytics Data API [{error_type}]: {exc}") from exc

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

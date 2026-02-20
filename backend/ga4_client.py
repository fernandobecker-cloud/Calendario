"""Cliente GA4 para consultas via Google Analytics Data API."""

from __future__ import annotations

import json
import os
from typing import Any

from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest
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
        raise RuntimeError("Falha ao consultar Google Analytics Data API") from exc

    sessions = 0
    users = 0
    if response.rows:
        first_row = response.rows[0]
        if len(first_row.metric_values) >= 2:
            sessions = int(first_row.metric_values[0].value or 0)
            users = int(first_row.metric_values[1].value or 0)

    return {"sessions": sessions, "users": users}

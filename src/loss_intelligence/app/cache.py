"""Cached dashboard data access.

Every cached function takes the database target name instead of an engine so
Streamlit can hash the arguments. The engine itself is cached separately.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import streamlit as st
from sqlalchemy import Engine

from loss_intelligence.app import repository
from loss_intelligence.config import get_settings
from loss_intelligence.db.engine import create_engine_for

TTL_SECONDS = 60


@st.cache_resource(show_spinner=False)
def engine(database: str) -> Engine:
    return create_engine_for(get_settings(), database)  # type: ignore[arg-type]


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def cohort_bounds(database: str) -> tuple[date | None, date | None]:
    return repository.cohort_bounds(engine(database))


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def data_freshness(database: str) -> dict[str, Any]:
    return repository.data_freshness(engine(database))


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def overview(
    database: str,
    start_date: date | None,
    end_date: date | None,
    minimum_volume: int,
    confidence: float,
    maturity_days: int,
) -> dict[str, Any]:
    return repository.overview(
        engine(database),
        start_date,
        end_date,
        minimum_volume=minimum_volume,
        confidence=confidence,
        maturity_days=maturity_days,
    )


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def daily_metrics(
    database: str,
    start_date: date | None,
    end_date: date | None,
    minimum_volume: int,
    confidence: float,
) -> list[dict[str, Any]]:
    return repository.daily_metrics(
        engine(database),
        start_date,
        end_date,
        minimum_volume=minimum_volume,
        confidence=confidence,
    )


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def hotspots(
    database: str,
    scope_type: str,
    start_date: date | None,
    end_date: date | None,
    minimum_volume: int,
    confidence: float,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    return repository.hotspots(
        engine(database),
        scope_type,
        start_date,
        end_date,
        minimum_volume=minimum_volume,
        confidence=confidence,
        limit=limit,
    )


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def loss_by_currency(
    database: str,
    start_date: date | None,
    end_date: date | None,
) -> list[dict[str, Any]]:
    return repository.loss_by_currency(engine(database), start_date, end_date)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def data_quality(
    database: str,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    return repository.data_quality(engine(database), start_date, end_date)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def operational_counts(database: str) -> dict[str, int]:
    return repository.operational_counts(engine(database))


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def alert_filter_options(database: str) -> dict[str, Any]:
    return repository.alert_filter_options(engine(database))


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def list_alerts(
    database: str,
    statuses: tuple[str, ...] | None,
    priorities: tuple[str, ...] | None,
    alert_types: tuple[str, ...] | None,
    generated_start: date | None,
    generated_end: date | None,
    search: str | None,
    limit: int | None,
) -> list[dict[str, Any]]:
    return repository.list_alerts(
        engine(database),
        statuses=statuses,
        priorities=priorities,
        alert_types=alert_types,
        generated_start=generated_start,
        generated_end=generated_end,
        search=search,
        limit=limit,
    )


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def get_alert(database: str, alert_id: UUID) -> dict[str, Any] | None:
    return repository.get_alert(engine(database), alert_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def alert_evidence(database: str, alert_id: UUID) -> list[dict[str, Any]]:
    return repository.alert_evidence(engine(database), alert_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def alerts_without_active_investigation(
    database: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    return repository.alerts_without_active_investigation(engine(database), limit=limit)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def shipment_search(
    database: str,
    query: str | None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return repository.shipment_search(engine(database), query, limit=limit)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def shipment_detail(database: str, shipment_id: UUID) -> dict[str, Any] | None:
    return repository.shipment_detail(engine(database), shipment_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def shipment_events(database: str, shipment_id: UUID) -> list[dict[str, Any]]:
    return repository.shipment_events(engine(database), shipment_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def shipment_incidents(database: str, shipment_id: UUID) -> list[dict[str, Any]]:
    return repository.shipment_incidents(engine(database), shipment_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def shipment_alerts(database: str, shipment_id: UUID) -> list[dict[str, Any]]:
    return repository.shipment_alerts(engine(database), shipment_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def investigation_filter_options(database: str) -> dict[str, Any]:
    return repository.investigation_filter_options(engine(database))


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def list_investigations(
    database: str,
    statuses: tuple[str, ...] | None,
    outcomes: tuple[str, ...] | None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return repository.list_investigations(
        engine(database),
        statuses=statuses,
        outcomes=outcomes,
        limit=limit,
    )


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def investigation_detail(database: str, investigation_id: UUID) -> dict[str, Any] | None:
    return repository.investigation_detail(engine(database), investigation_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def investigation_audit(database: str, investigation_id: UUID) -> list[dict[str, Any]]:
    return repository.investigation_audit(engine(database), investigation_id)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def returns_summary(
    database: str,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    return repository.returns_summary(engine(database), start_date, end_date)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def detection_runs(database: str, limit: int = 50) -> list[dict[str, Any]]:
    return repository.detection_runs(engine(database), limit=limit)


@st.cache_data(ttl=TTL_SECONDS, show_spinner=False)
def evaluation_summary(
    database: str,
    detection_run_id: UUID | None,
    k: int,
) -> dict[str, Any]:
    return repository.evaluation_summary(
        engine(database),
        detection_run_id=detection_run_id,
        k=k,
    )


def clear_data_cache() -> None:
    st.cache_data.clear()

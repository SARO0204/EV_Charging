from datetime import datetime, timedelta, timezone
from math import floor

from ..models import (
    Charger,
    ChargingSession,
    QueuePrediction,
    Reservation,
)
from ..models.schemas import DataSource, ReservationStatus
from .data_service import (
    get_charger_by_id,
    get_charging_sessions_for_charger,
    get_reservations_for_charger,
)


_FORECAST_HORIZON = timedelta(minutes=15)
_ARRIVAL_HISTORY_WINDOW = timedelta(minutes=60)
_SESSION_HISTORY_WINDOW = timedelta(hours=24)


class InsufficientQueuePredictionDataError(RuntimeError):
    pass


def _calculate_queue_prediction(
    charger_id: str,
    charger: Charger,
    sessions: list[ChargingSession],
    reservations: list[Reservation],
    prediction_timestamp: datetime,
) -> QueuePrediction:
    if prediction_timestamp.tzinfo is None or prediction_timestamp.utcoffset() is None:
        raise ValueError("prediction_timestamp must be timezone-aware")

    forecast_at = prediction_timestamp + _FORECAST_HORIZON
    recent_session_cutoff = prediction_timestamp - _SESSION_HISTORY_WINDOW
    arrival_cutoff = prediction_timestamp - _ARRIVAL_HISTORY_WINDOW
    completed_sessions = [
        session
        for session in sessions
        if session.status.value == "completed"
        and session.charging_started_at is not None
        and session.charging_ended_at is not None
        and recent_session_cutoff <= session.charging_ended_at <= prediction_timestamp
        and session.charging_ended_at > session.charging_started_at
    ]
    completed_durations = [
        (session.charging_ended_at - session.charging_started_at).total_seconds()
        / 60
        for session in completed_sessions
    ]
    if not completed_durations:
        raise InsufficientQueuePredictionDataError(
            "Queue prediction requires at least one completed charging session "
            "with valid start and end times from the last 24 hours."
        )

    recent_arrivals = [
        session
        for session in sessions
        if arrival_cutoff <= session.arrived_at <= prediction_timestamp
    ]
    upcoming_reservations = [
        reservation
        for reservation in reservations
        if reservation.status
        in (ReservationStatus.PROPOSED, ReservationStatus.CONFIRMED)
        and prediction_timestamp < reservation.slot_start <= forecast_at
    ]

    total_connectors = sum(connector.total_count for connector in charger.connectors)
    available_connectors = sum(
        connector.available_count for connector in charger.connectors
    )
    active_sessions = charger.grid.active_session_count
    serviceable_connectors = min(
        total_connectors, available_connectors + active_sessions
    )
    if serviceable_connectors <= 0:
        raise InsufficientQueuePredictionDataError(
            "Queue prediction requires at least one available or active charger connector."
        )

    average_observed_session_minutes = sum(completed_durations) / len(
        completed_durations
    )
    charging_power = max(connector.power_kw for connector in charger.connectors)
    recorded_energy = [
        session.energy_delivered_kwh
        for session in completed_sessions
        if session.energy_delivered_kwh is not None
        and session.energy_delivered_kwh > 0
    ]
    power_based_duration = (
        (sum(recorded_energy) / len(recorded_energy)) / charging_power * 60
        if recorded_energy
        else None
    )
    estimated_session_minutes = max(
        average_observed_session_minutes,
        power_based_duration or 0,
    )
    current_queue = charger.queue.current_count
    observed_arrival_rate = len(recent_arrivals) / _ARRIVAL_HISTORY_WINDOW.total_seconds()
    expected_arrivals = observed_arrival_rate * _FORECAST_HORIZON.total_seconds()
    reservation_arrivals = len(upcoming_reservations)
    expected_departures = min(
        current_queue + expected_arrivals + reservation_arrivals,
        serviceable_connectors
        * _FORECAST_HORIZON.total_seconds()
        / (estimated_session_minutes * 60),
    )
    expected_queue = max(
        0,
        current_queue + expected_arrivals + reservation_arrivals - expected_departures,
    )
    predicted_queue = floor(expected_queue + 0.5)
    predicted_wait = round(
        predicted_queue * estimated_session_minutes / serviceable_connectors,
        1,
    )
    historical_sources = sorted(
        {session.data_source for session in completed_sessions + recent_arrivals},
        key=lambda source: source.value,
    )
    source_labels = ", ".join(source.value for source in historical_sources)
    explanation = (
        "Baseline estimate (not a trained ML prediction) for the next 15 minutes: "
        f"{current_queue} observed queued EVs + {expected_arrivals:.2f} arrivals "
        f"projected from {len(recent_arrivals)} session arrivals in the last 60 minutes "
        f"+ {reservation_arrivals} proposed/confirmed reservations in the forecast "
        f"window - {expected_departures:.2f} estimated queue departures = "
        f"{predicted_queue} predicted queued EVs. Departure capacity uses "
        f"{serviceable_connectors} serviceable connectors ({available_connectors} "
        f"available and {active_sessions} active), and {estimated_session_minutes:.1f} "
        f"estimated session minutes from {len(completed_durations)} completed sessions "
        f"(observed mean {average_observed_session_minutes:.1f} minutes). Maximum listed "
        f"connector power is {charging_power:g} kW. "
        + (
            f"Recorded energy implies a {power_based_duration:.1f}-minute idealized "
            "duration lower bound; the estimate does not go below observed duration. "
            if power_based_duration is not None
            else "No recorded session energy was available to adjust duration for power. "
        )
        + f"Historical session sources: {source_labels}."
    )

    return QueuePrediction(
        charger_id=charger_id,
        current_queue_count=current_queue,
        current_queue_observed_at=charger.queue.observed_at,
        predicted_queue_count=predicted_queue,
        predicted_wait_minutes=predicted_wait,
        prediction_timestamp=prediction_timestamp,
        forecast_at=forecast_at,
        forecast_horizon_minutes=int(_FORECAST_HORIZON.total_seconds() / 60),
        prediction_method="observed_session_baseline",
        historical_session_count=len(completed_durations),
        historical_data_sources=historical_sources,
        explanation=explanation,
    )


def predict_queue_for_charger(charger_id: str, prediction_timestamp=None):
    charger_record = get_charger_by_id(charger_id)
    if charger_record is None:
        return None

    document_id, charger = charger_record
    sessions = get_charging_sessions_for_charger(document_id)
    reservations = get_reservations_for_charger(document_id)
    timestamp = prediction_timestamp or datetime.now(timezone.utc)
    return _calculate_queue_prediction(
        document_id,
        charger,
        sessions,
        reservations,
        timestamp,
    )
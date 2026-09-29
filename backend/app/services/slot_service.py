from datetime import datetime, timedelta, timezone
from math import ceil

from ..models import (
    Charger,
    ChargingSession,
    EV,
    EVSlotRecommendation,
    GridIntelligenceResult,
    Reservation,
    ReservationCreateRequest,
    SlotChargingDetails,
    SlotOption,
    SlotPrioritySummary,
)
from ..models.schemas import ChargingSessionStatus, ReservationStatus
from .data_service import (
    ReservationChargerNotFoundError,
    ReservationConflictError,
    cancel_reservation_by_id,
    create_reservation_record,
    get_charger_by_id,
    get_charging_sessions_for_charger,
    get_ev_by_id,
    get_reservation_by_id,
    get_reservations_for_charger,
)
from .grid_intelligence_service import calculate_grid_intelligence
from .queue_prediction_service import predict_queue_for_charger
from .recommendation_service import recommend_charger_for_ev


_SEARCH_WINDOW = timedelta(hours=2)
_SLOT_INTERVAL = timedelta(minutes=15)
_MAX_ALTERNATIVES = 4
_CANCELLABLE_STATUSES = {
    ReservationStatus.PROPOSED,
    ReservationStatus.CONFIRMED,
}


class NoChargingNeedError(ValueError):
    pass


class NoConnectorCapacityError(ValueError):
    pass


class NoPracticalSlotError(ValueError):
    pass


class InvalidReservationStateError(ValueError):
    pass


class EVNotFoundError(LookupError):
    pass


class ChargerNotFoundError(LookupError):
    pass


def calculate_energy_required_kwh(ev: EV) -> float:
    charge_gap = max(0, ev.required_charge_percent - ev.battery_percent)
    if charge_gap <= 0:
        raise NoChargingNeedError(
            "The EV battery already meets or exceeds its required charge level."
        )
    return ev.vehicle.battery_capacity_kwh * charge_gap / 100


def calculate_charging_duration_minutes(
    energy_required_kwh: float,
    suitable_charging_power_kw: float,
) -> int:
    if energy_required_kwh <= 0:
        raise NoChargingNeedError("Energy required must be greater than zero.")
    if suitable_charging_power_kw <= 0:
        raise NoConnectorCapacityError(
            "Suitable charging power is unavailable for this EV and charger."
        )
    return ceil(energy_required_kwh / suitable_charging_power_kw * 60)


def _serviceable_connector_capacity(charger: Charger) -> int:
    total_connectors = sum(connector.total_count for connector in charger.connectors)
    available_connectors = sum(
        connector.available_count for connector in charger.connectors
    )
    active_sessions = charger.grid.active_session_count
    return min(total_connectors, available_connectors + active_sessions)


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime):
    return start_a < end_b and end_a > start_b


def _active_session_count_at(sessions: list[ChargingSession], now: datetime) -> int:
    return sum(
        session.status == ChargingSessionStatus.CHARGING
        and (session.charging_started_at or session.arrived_at) <= now
        and (session.charging_ended_at is None or session.charging_ended_at > now)
        for session in sessions
    )


def _occupied_connectors(
    slot_start: datetime,
    slot_end: datetime,
    now: datetime,
    charger: Charger,
    reservations: list[Reservation],
    sessions: list[ChargingSession],
) -> int:
    reserved = sum(
        reservation.status in _CANCELLABLE_STATUSES
        and _overlaps(
            reservation.slot_start,
            reservation.slot_end,
            slot_start,
            slot_end,
        )
        for reservation in reservations
    )
    charging = 0
    for session in sessions:
        if session.status != ChargingSessionStatus.CHARGING:
            continue
        session_start = session.charging_started_at or session.arrived_at
        session_end = session.charging_ended_at or slot_end
        charging += _overlaps(session_start, session_end, slot_start, slot_end)

    tracked_active = _active_session_count_at(sessions, now)
    untracked_active = max(0, charger.grid.active_session_count - tracked_active)
    return reserved + charging + untracked_active


def _ceil_to_slot_boundary(value: datetime) -> datetime:
    interval_seconds = int(_SLOT_INTERVAL.total_seconds())
    rounded_timestamp = ceil(value.timestamp() / interval_seconds) * interval_seconds
    return datetime.fromtimestamp(rounded_timestamp, tz=value.tzinfo)


def _slot_weights(priority_score: float) -> tuple[float, float, float]:
    priority_fraction = min(100, max(0, priority_score)) / 100
    wait_weight = 70 + 20 * priority_fraction
    grid_weight = 30 - 20 * priority_fraction
    maximum_wait = 120 - 90 * priority_fraction
    return wait_weight, grid_weight, maximum_wait


def _evaluate_slot(
    start: datetime,
    duration_minutes: int,
    now: datetime,
    priority_score: float,
    grid: GridIntelligenceResult,
    occupied_connectors: int,
    connector_capacity: int,
) -> SlotOption:
    waiting_minutes = max(0, (start - now).total_seconds() / 60)
    wait_weight, grid_weight, maximum_wait = _slot_weights(priority_score)
    priority_suitability = max(
        0,
        min(100, 100 * (1 - waiting_minutes / maximum_wait)),
    )
    grid_suitability = 100 - grid.grid_risk_score
    score = round(
        (priority_suitability * wait_weight + grid_suitability * grid_weight) / 100,
        2,
    )
    return SlotOption(
        start=start,
        end=start + timedelta(minutes=duration_minutes),
        waiting_minutes=round(waiting_minutes, 1),
        charging_duration_minutes=duration_minutes,
        priority_suitability_score=round(priority_suitability, 2),
        grid_suitability_score=round(grid_suitability, 2),
        occupied_connectors=occupied_connectors,
        serviceable_connector_capacity=connector_capacity,
        score=score,
    )


def _find_slots(
    charger: Charger,
    queue_wait_minutes: float,
    charging_duration_minutes: int,
    priority_score: float,
    grid: GridIntelligenceResult,
    reservations: list[Reservation],
    sessions: list[ChargingSession],
    now: datetime,
) -> list[SlotOption]:
    connector_capacity = _serviceable_connector_capacity(charger)
    if connector_capacity <= 0:
        raise NoConnectorCapacityError(
            "The charger has no available or active serviceable connector capacity."
        )

    wait_weight, grid_weight, maximum_wait = _slot_weights(priority_score)
    del wait_weight, grid_weight
    first_start = _ceil_to_slot_boundary(
        now + timedelta(minutes=queue_wait_minutes)
    )
    if (first_start - now).total_seconds() / 60 > maximum_wait:
        raise NoPracticalSlotError(
            "The predicted queue wait exceeds the maximum wait permitted by this EV's priority."
        )

    search_end = now + _SEARCH_WINDOW
    candidates = []
    for offset in range(int(_SEARCH_WINDOW / _SLOT_INTERVAL) + 1):
        start = first_start + offset * _SLOT_INTERVAL
        if start > search_end:
            break
        waiting_minutes = (start - now).total_seconds() / 60
        if waiting_minutes > maximum_wait:
            break
        end = start + timedelta(minutes=charging_duration_minutes)
        occupied = _occupied_connectors(
            start,
            end,
            now,
            charger,
            reservations,
            sessions,
        )
        if occupied >= connector_capacity:
            continue
        candidates.append(
            _evaluate_slot(
                start,
                charging_duration_minutes,
                now,
                priority_score,
                grid,
                occupied,
                connector_capacity,
            )
        )

    if not candidates:
        raise NoPracticalSlotError(
            "No conflict-free connector slot is available within the bounded search window."
        )
    return sorted(candidates, key=lambda slot: (slot.score * -1, slot.start))


def recommend_slot_for_ev(ev_id: str, ev: EV, now: datetime | None = None):
    calculated_at = now or datetime.now(timezone.utc)
    recommendation = recommend_charger_for_ev(ev_id, ev, calculated_at)
    charger_id = recommendation.recommendation.charger_id
    charger_record = get_charger_by_id(charger_id)
    if charger_record is None:
        raise ChargerNotFoundError(f"Recommended charger '{charger_id}' was not found.")
    _, charger = charger_record

    queue = predict_queue_for_charger(
        charger_id,
        prediction_timestamp=calculated_at,
    )
    if queue is None:
        raise ChargerNotFoundError(
            f"Recommended charger '{charger_id}' is no longer available."
        )
    grid = calculate_grid_intelligence(charger_id, charger, calculated_at)
    energy_required = calculate_energy_required_kwh(ev)
    suitable_power = recommendation.recommendation.suitable_charging_power_kw
    duration = calculate_charging_duration_minutes(energy_required, suitable_power)
    reservations = get_reservations_for_charger(charger_id)
    sessions = get_charging_sessions_for_charger(charger_id)
    slots = _find_slots(
        charger,
        queue.predicted_wait_minutes,
        duration,
        recommendation.priority.score,
        grid,
        reservations,
        sessions,
        calculated_at,
    )
    selected = slots[0]
    priority_fraction = recommendation.priority.score / 100
    maximum_wait = 120 - 90 * priority_fraction
    explanation = (
        f"Phase 10 selected {charger.station_name}. This slot starts "
        f"{selected.waiting_minutes:.1f} minutes from calculation time, after the "
        f"Phase 7 predicted queue wait of {queue.predicted_wait_minutes:.1f} minutes. "
        f"The EV needs {energy_required:.2f} kWh; at {suitable_power:g} kW suitable "
        f"charging power, estimated charging duration is {duration} minutes. The slot "
        f"is conflict-free against proposed/confirmed reservations and active sessions "
        f"within {selected.serviceable_connector_capacity} serviceable connectors. "
        f"Priority {recommendation.priority.level.value} ({recommendation.priority.score:.2f}) "
        f"sets a {maximum_wait:.1f}-minute maximum wait and adjusts the wait/grid score "
        f"weights. Grid context is {grid.grid_status.value} with risk "
        f"{grid.grid_risk_score:.2f}/100. That Phase 9 projection is applied as static "
        f"context to every slot; no time-specific future grid load is available."
    )
    return EVSlotRecommendation(
        ev_id=ev_id,
        charger_id=charger_id,
        station_name=charger.station_name,
        priority=SlotPrioritySummary(
            score=recommendation.priority.score,
            level=recommendation.priority.level,
        ),
        slot=selected,
        charging=SlotChargingDetails(
            energy_required_kwh=round(energy_required, 2),
            charging_power_kw=suitable_power,
        ),
        grid_status=grid.grid_status,
        grid_risk_score=grid.grid_risk_score,
        explanation=explanation,
        alternatives=slots[1 : _MAX_ALTERNATIVES + 1],
    )


def _validate_reservation_capacity(
    charger: Charger,
    reservations: list[Reservation],
    sessions: list[ChargingSession],
    slot_start: datetime,
    slot_end: datetime,
    now: datetime,
) -> str | None:
    capacity = _serviceable_connector_capacity(charger)
    if capacity <= 0:
        return "The charger has no available or active serviceable connector capacity."
    occupied = _occupied_connectors(
        slot_start,
        slot_end,
        now,
        charger,
        reservations,
        sessions,
    )
    if occupied >= capacity:
        return (
            f"The requested slot conflicts with {occupied} occupied connectors; "
            f"serviceable capacity is {capacity}."
        )
    return None


def create_reservation(
    request: ReservationCreateRequest,
    now: datetime | None = None,
) -> tuple[str, Reservation]:
    timestamp = now or datetime.now(timezone.utc)
    ev_record = get_ev_by_id(request.ev_id)
    if ev_record is None:
        raise EVNotFoundError(f"EV '{request.ev_id}' was not found.")
    _, ev = ev_record
    charger_record = get_charger_by_id(request.charger_id)
    if charger_record is None:
        raise ChargerNotFoundError(f"Charger '{request.charger_id}' was not found.")
    _, charger = charger_record

    energy_required = calculate_energy_required_kwh(ev)
    available_connectors = [
        connector
        for connector in charger.connectors
        if connector.available_count > 0
    ]
    if not available_connectors:
        raise NoConnectorCapacityError("The charger has no available connectors.")
    available_power = max(connector.power_kw for connector in available_connectors)
    suitable_power = (
        min(available_power, ev.vehicle.max_charge_rate_kw)
        if ev.vehicle.max_charge_rate_kw is not None
        else available_power
    )
    required_duration = calculate_charging_duration_minutes(
        energy_required,
        suitable_power,
    )
    requested_duration = (
        request.slot_end - request.slot_start
    ).total_seconds() / 60
    if requested_duration < required_duration:
        raise NoPracticalSlotError(
            f"The requested slot is shorter than the estimated {required_duration}-minute charging duration."
        )
    if request.slot_start <= timestamp:
        raise NoPracticalSlotError("Reservation slots must start in the future.")

    queue = predict_queue_for_charger(
        request.charger_id,
        prediction_timestamp=timestamp,
    )
    if queue is None:
        raise ChargerNotFoundError(
            f"Charger '{request.charger_id}' is no longer available."
        )
    if request.slot_start < timestamp + timedelta(minutes=queue.predicted_wait_minutes):
        raise NoPracticalSlotError(
            "The requested slot starts before the predicted queue wait has elapsed."
        )

    reservations = get_reservations_for_charger(request.charger_id)
    sessions = get_charging_sessions_for_charger(request.charger_id)
    conflict = _validate_reservation_capacity(
        charger,
        reservations,
        sessions,
        request.slot_start,
        request.slot_end,
        timestamp,
    )
    if conflict:
        raise ReservationConflictError(conflict)

    reservation = Reservation(
        ev_id=request.ev_id,
        charger_id=request.charger_id,
        slot_start=request.slot_start,
        slot_end=request.slot_end,
        status=ReservationStatus.CONFIRMED,
        allocation_history=[],
        created_at=timestamp,
        updated_at=timestamp,
    )

    def validate_transaction(charger_data, current_reservations, current_sessions):
        return _validate_reservation_capacity(
            charger_data,
            current_reservations,
            current_sessions,
            request.slot_start,
            request.slot_end,
            timestamp,
        )

    return create_reservation_record(reservation, validate_transaction)


def get_reservation(reservation_id: str):
    return get_reservation_by_id(reservation_id)


def cancel_reservation(reservation_id: str, now: datetime | None = None):
    result = cancel_reservation_by_id(
        reservation_id,
        now or datetime.now(timezone.utc),
    )
    if result is None:
        raise LookupError(f"Reservation '{reservation_id}' was not found.")
    _, reservation, cancelled = result
    if not cancelled:
        raise InvalidReservationStateError(
            f"Reservation in '{reservation.status.value}' status cannot be cancelled."
        )
    return result[0], reservation
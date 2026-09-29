from __future__ import annotations

from datetime import datetime, timezone
from math import asin, cos, radians, sin, sqrt

from ..models import (
    Charger,
    EV,
    GridStatus,
    Reservation,
    ReservationReallocationAssessment,
    ReservationStatus,
)
from .data_service import (
    MalformedFirestoreDocumentError,
    ReservationConflictError,
    get_available_chargers,
    get_charger_by_id,
    get_charging_sessions_for_charger,
    get_ev_by_id,
    get_reservation_by_id,
    get_reservations_for_charger,
    reallocate_reservation_document,
)
from .grid_intelligence_service import calculate_grid_intelligence
from .priority_service import calculate_ev_priority
from .queue_prediction_service import predict_queue_for_charger
from .recommendation_service import CandidateEvidence, score_candidates
from .slot_service import (
    InvalidReservationStateError,
    NoChargingNeedError,
    NoConnectorCapacityError,
    NoPracticalSlotError,
    _find_slots,
    _validate_reservation_capacity,
    calculate_charging_duration_minutes,
    calculate_energy_required_kwh,
)

MINIMUM_SCORE_IMPROVEMENT = 5.0
CURRENT_WAIT_IMPROVEMENT_THRESHOLD = 10.0
CURRENT_GRID_RISK_THRESHOLD = 15.0
_REALLOCATABLE_STATUSES = {ReservationStatus.PROPOSED, ReservationStatus.CONFIRMED}


class ReallocationUnavailableError(ValueError):
    pass


def _distance_km(start, end):
    lat1 = radians(start.latitude)
    lon1 = radians(start.longitude)
    lat2 = radians(end.latitude)
    lon2 = radians(end.longitude)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


def _build_candidate_evidence(
    ev: EV,
    charger_id: str,
    charger: Charger,
    priority_score: float,
    timestamp: datetime,
):
    available_connectors = [
        connector for connector in charger.connectors if connector.available_count > 0
    ]
    if not available_connectors:
        return None
    queue = predict_queue_for_charger(charger_id, prediction_timestamp=timestamp)
    if queue is None:
        return None
    grid = calculate_grid_intelligence(charger_id, charger, timestamp)
    available_power = max(connector.power_kw for connector in available_connectors)
    suitable_power = (
        min(available_power, ev.vehicle.max_charge_rate_kw)
        if ev.vehicle.max_charge_rate_kw is not None
        else available_power
    )
    evidence = CandidateEvidence(
        charger_id=charger_id,
        station_name=charger.station_name,
        distance_km=_distance_km(ev.current_location, charger.location),
        predicted_wait_minutes=queue.predicted_wait_minutes,
        grid_status=grid.grid_status.value,
        grid_risk_score=grid.grid_risk_score,
        available_charging_power_kw=available_power,
        suitable_charging_power_kw=suitable_power,
    )
    return evidence, queue, grid


def _score_for_charger(
    ev: EV,
    charger_id: str,
    charger: Charger,
    priority_score: float,
    timestamp: datetime,
):
    candidate = _build_candidate_evidence(ev, charger_id, charger, priority_score, timestamp)
    if candidate is None:
        return None
    evidence, _, _ = candidate
    ranked, _ = score_candidates(priority_score, [evidence])
    return ranked[0][2]


def _best_alternative_for_ev(
    ev: EV,
    current_charger_id: str,
    priority_score: float,
    timestamp: datetime,
):
    candidate = None
    for charger_id, charger in get_available_chargers():
        if charger_id == current_charger_id:
            continue
        built = _build_candidate_evidence(
            ev,
            charger_id,
            charger,
            priority_score,
            timestamp,
        )
        if built is None:
            continue
        evidence, queue, grid = built
        try:
            duration = calculate_charging_duration_minutes(
                calculate_energy_required_kwh(ev),
                evidence.suitable_charging_power_kw,
            )
            reservations = get_reservations_for_charger(charger_id)
            sessions = get_charging_sessions_for_charger(charger_id)
            slots = _find_slots(
                charger,
                queue.predicted_wait_minutes,
                duration,
                priority_score,
                grid,
                reservations,
                sessions,
                timestamp,
            )
        except (NoChargingNeedError, NoConnectorCapacityError, NoPracticalSlotError):
            continue
        ranked, _ = score_candidates(priority_score, [evidence])
        score = ranked[0][2]
        alternative = {
            "charger_id": charger_id,
            "station_name": charger.station_name,
            "score": round(score, 2),
            "slot_start": slots[0].start,
            "slot_end": slots[0].end,
            "predicted_wait_minutes": queue.predicted_wait_minutes,
            "grid_status": grid.grid_status,
            "grid_risk_score": grid.grid_risk_score,
        }
        if candidate is None or alternative["score"] > candidate["score"]:
            candidate = alternative
    return candidate


def _build_assessment(
    reservation: Reservation,
    ev: EV,
    charger: Charger,
    priority_score: float,
    timestamp: datetime,
):
    current_candidate = _build_candidate_evidence(
        ev,
        reservation.charger_id,
        charger,
        priority_score,
        timestamp,
    )
    current_score = None
    current_wait = 0.0
    current_grid = GridStatus.NORMAL
    current_grid_score = 0.0
    if current_candidate is not None:
        evidence, queue, grid = current_candidate
        current_score = score_candidates(priority_score, [evidence])[0][0][2]
        current_wait = queue.predicted_wait_minutes
        current_grid = grid.grid_status
        current_grid_score = grid.grid_risk_score
    alternative = _best_alternative_for_ev(
        ev,
        reservation.charger_id,
        priority_score,
        timestamp,
    )
    reason = "No reallocation recommended because the current charger remains suitable."
    recommended = False
    if current_score is None:
        if alternative is not None:
            reason = "Reallocation recommended because the current charger is no longer serviceable."
            recommended = True
        else:
            reason = "No reallocation recommended because no feasible alternative charger was found."
    elif alternative is None:
        reason = "No reallocation recommended because no feasible alternative charger was found."
    else:
        score_gap = alternative["score"] - current_score
        wait_gap = current_wait - alternative["predicted_wait_minutes"]
        grid_gap = current_grid_score - alternative["grid_risk_score"]
        if score_gap >= MINIMUM_SCORE_IMPROVEMENT:
            recommended = True
            reason = "Reallocation recommended because the alternative charger provides a meaningful score improvement."
        elif wait_gap >= CURRENT_WAIT_IMPROVEMENT_THRESHOLD:
            recommended = True
            reason = "Reallocation recommended because the current charger has a substantially higher predicted wait."
        elif grid_gap >= CURRENT_GRID_RISK_THRESHOLD:
            recommended = True
            reason = "Reallocation recommended because projected grid stress at the current charger is significantly higher."
        elif score_gap > 0:
            reason = "Alternative charger found, but the improvement is below the reallocation threshold."
    return ReservationReallocationAssessment(
        reservation_id="pending",
        ev_id=reservation.ev_id,
        current={
            "charger_id": reservation.charger_id,
            "station_name": charger.station_name,
            "slot_start": reservation.slot_start,
            "slot_end": reservation.slot_end,
            "score": round(current_score, 2) if current_score is not None else 0.0,
            "predicted_wait_minutes": round(current_wait, 2),
            "grid_status": current_grid,
            "grid_risk_score": round(current_grid_score, 2),
        },
        reallocation={
            "recommended": recommended,
            "alternative_charger_id": alternative["charger_id"] if alternative else None,
            "alternative_station_name": alternative["station_name"] if alternative else None,
            "alternative_slot_start": alternative["slot_start"] if alternative else None,
            "alternative_slot_end": alternative["slot_end"] if alternative else None,
            "alternative_score": alternative["score"] if alternative else None,
            "score_improvement": round((alternative["score"] - (current_score or 0)), 2) if alternative else 0.0,
            "reason": reason,
        },
    )


def check_reallocation(reservation_id: str, now: datetime | None = None):
    timestamp = now or datetime.now(timezone.utc)
    reservation_record = get_reservation_by_id(reservation_id)
    if reservation_record is None:
        raise LookupError(f"Reservation '{reservation_id}' was not found.")
    reservation_id_doc, reservation = reservation_record
    if reservation.status not in _REALLOCATABLE_STATUSES:
        raise InvalidReservationStateError(
            f"Reservation in '{reservation.status.value}' status cannot be reallocated."
        )
    ev_record = get_ev_by_id(reservation.ev_id)
    if ev_record is None:
        raise LookupError(f"EV '{reservation.ev_id}' was not found.")
    _, ev = ev_record
    charger_record = get_charger_by_id(reservation.charger_id)
    if charger_record is None:
        raise LookupError(f"Charger '{reservation.charger_id}' was not found.")
    _, charger = charger_record
    priority = calculate_ev_priority(reservation.ev_id, ev, timestamp)
    assessment = _build_assessment(
        reservation,
        ev,
        charger,
        priority.priority_score,
        timestamp,
    )
    assessment.reservation_id = reservation_id_doc
    return assessment


def _normalize_reallocation_result(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, (tuple, list)) and len(result) == 2:
        _, payload = result
        if isinstance(payload, Reservation):
            return {"outcome": "updated", "data": payload.model_dump(mode="python", by_alias=True, exclude_none=True)}
        if isinstance(payload, dict):
            return {"outcome": "updated", "data": payload}
    raise TypeError(f"Unexpected reallocation result format: {type(result).__name__}")


def reallocate_reservation(reservation_id: str, now: datetime | None = None):
    timestamp = now or datetime.now(timezone.utc)
    assessment = check_reallocation(reservation_id, timestamp)
    if not assessment.reallocation.recommended or not assessment.reallocation.alternative_charger_id:
        raise ReallocationUnavailableError(assessment.reallocation.reason)

    reservation_record = get_reservation_by_id(reservation_id)
    if reservation_record is None:
        raise LookupError(f"Reservation '{reservation_id}' was not found.")
    _, reservation = reservation_record
    if reservation.status not in _REALLOCATABLE_STATUSES:
        raise InvalidReservationStateError(
            f"Reservation in '{reservation.status.value}' status cannot be reallocated."
        )

    alternative_charger_id = assessment.reallocation.alternative_charger_id
    alternative_slot_start = assessment.reallocation.alternative_slot_start
    alternative_slot_end = assessment.reallocation.alternative_slot_end
    if alternative_slot_start is None or alternative_slot_end is None:
        raise ReallocationUnavailableError(
            "The alternative slot information is missing; no reallocation can be applied."
        )

    def validate_transaction(
        charger_id,
        charger_data,
        reservation_documents,
        session_documents,
        current_data,
    ):
        if current_data.get("status") not in {status.value for status in _REALLOCATABLE_STATUSES}:
            return "invalid_state", "Reservation is not in a reallocatable status."
        if current_data.get("updatedAt") != reservation.updated_at:
            return "stale", "Reservation state changed before reallocation was applied."
        if current_data.get("chargerId") != reservation.charger_id:
            return "stale", "Reservation charger changed before the reallocation transaction committed."
        try:
            charger = Charger.model_validate(charger_data)
        except Exception as exc:
            return "malformed", str(exc)
        reservations = [
            Reservation.model_validate(reservation_data)
            for _, reservation_data in reservation_documents
        ]
        sessions = [
            item for item in []
        ]
        if charger_id != alternative_charger_id:
            return "conflict", "The alternative charger does not match the target reallocation."
        conflict = _validate_reservation_capacity(
            charger,
            reservations,
            sessions,
            alternative_slot_start,
            alternative_slot_end,
            timestamp,
        )
        if conflict:
            return "conflict", conflict
        return None

    try:
        result = reallocate_reservation_document(
            reservation_id,
            alternative_charger_id,
            alternative_slot_start,
            alternative_slot_end,
            timestamp,
            assessment.reallocation.reason,
            validate_transaction,
        )
    except Exception as exc:
        raise exc

    result = _normalize_reallocation_result(result)
    if result["outcome"] == "not_found":
        raise LookupError(f"Reservation '{reservation_id}' was not found.")
    if result["outcome"] == "invalid_state":
        raise InvalidReservationStateError(result["detail"])
    if result["outcome"] == "stale":
        raise ValueError(result["detail"])
    if result["outcome"] == "conflict":
        raise ReservationConflictError(result["detail"])
    if result["outcome"] == "malformed":
        raise MalformedFirestoreDocumentError(result["detail"])
    if result["outcome"] == "charger_not_found":
        raise LookupError(f"Charger '{alternative_charger_id}' was not found.")
    if result["outcome"] != "updated":
        raise RuntimeError(f"Unexpected reallocation outcome: {result['outcome']}")
    return Reservation.model_validate(result["data"])

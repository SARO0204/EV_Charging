from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import (
    EmergencyActivation,
    EmergencyAlternative,
    EmergencyRecommendationDetail,
    EmergencyRecommendationResult,
    EmergencyReachability,
    EmergencyScoreBreakdown,
    EmergencyWeights,
    GridStatus,
    PriorityLevel,
)
from .data_service import get_available_chargers, get_ev_by_id
from .grid_intelligence_service import InvalidGridDataError, calculate_grid_intelligence
from .priority_service import calculate_ev_priority
from .queue_prediction_service import InsufficientQueuePredictionDataError, predict_queue_for_charger
from .ranking_service import _distance_km

_EMERGENCY_WAIT_WEIGHT = 45.0
_EMERGENCY_POWER_WEIGHT = 30.0
_EMERGENCY_GRID_WEIGHT = 20.0
_EMERGENCY_DISTANCE_WEIGHT = 5.0


class NoEmergencyRecommendationCandidatesError(RuntimeError):
    pass


@dataclass(frozen=True)
class _EmergencyCandidate:
    charger_id: str
    station_name: str
    distance_km: float
    predicted_wait_minutes: float
    grid_status: GridStatus
    grid_risk_score: float
    available_charging_power_kw: float
    suitable_charging_power_kw: float


def _distance_score(distance_km: float) -> float:
    return round(max(0.0, min(100.0, (1 - distance_km / 50.0) * 100.0)), 2)


def _relative_score(values: list[float], *, higher_is_better: bool) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return [100.0] * len(values)
    span = maximum - minimum
    if higher_is_better:
        return [round((value - minimum) / span * 100.0, 2) for value in values]
    return [round((maximum - value) / span * 100.0, 2) for value in values]


def calculate_emergency_recommendation(
    ev_id: str,
    ev,
    calculated_at: datetime | None = None,
):
    timestamp = calculated_at or datetime.now(timezone.utc)
    priority = calculate_ev_priority(ev_id, ev, timestamp)
    weights = EmergencyWeights(
        wait=_EMERGENCY_WAIT_WEIGHT,
        charging_power=_EMERGENCY_POWER_WEIGHT,
        grid=_EMERGENCY_GRID_WEIGHT,
        distance=_EMERGENCY_DISTANCE_WEIGHT,
    )
    reachability = EmergencyReachability(
        verified=False,
        reason="Physical charger reachability cannot be verified from the available vehicle/route data.",
    )
    score_breakdown = EmergencyScoreBreakdown(
        wait_score=0.0,
        charging_power_score=0.0,
        grid_score=0.0,
        distance_score=0.0,
    )

    if priority.priority_level != PriorityLevel.CRITICAL:
        return EmergencyRecommendationResult(
            ev_id=ev_id,
            emergency=EmergencyActivation(
                active=False,
                reason="Emergency mode is not required for this EV.",
                battery_percent=ev.battery_percent,
                priority_score=priority.priority_score,
                priority_level=priority.priority_level,
            ),
            recommendation=None,
            reachability=reachability,
            score_breakdown=score_breakdown,
            weights=weights,
            alternatives=[],
        )

    candidates = []
    for charger_id, charger in get_available_chargers():
        available_connectors = [
            connector for connector in charger.connectors if connector.available_count > 0
        ]
        if not available_connectors:
            continue

        try:
            queue_prediction = predict_queue_for_charger(charger_id, prediction_timestamp=timestamp)
        except InsufficientQueuePredictionDataError:
            continue
        if queue_prediction is None:
            continue

        try:
            grid = calculate_grid_intelligence(charger_id, charger, timestamp)
        except InvalidGridDataError:
            continue

        available_power = max(connector.power_kw for connector in available_connectors)
        suitable_power = (
            min(available_power, ev.vehicle.max_charge_rate_kw)
            if ev.vehicle.max_charge_rate_kw is not None
            else available_power
        )
        candidates.append(
            _EmergencyCandidate(
                charger_id=charger_id,
                station_name=charger.station_name,
                distance_km=_distance_km(ev.current_location, charger.location),
                predicted_wait_minutes=queue_prediction.predicted_wait_minutes,
                grid_status=grid.grid_status,
                grid_risk_score=grid.grid_risk_score,
                available_charging_power_kw=available_power,
                suitable_charging_power_kw=suitable_power,
            )
        )

    if not candidates:
        raise NoEmergencyRecommendationCandidatesError(
            "No serviceable emergency charger candidates could be evaluated for this critical-priority EV."
        )

    wait_scores = _relative_score(
        [candidate.predicted_wait_minutes for candidate in candidates],
        higher_is_better=False,
    )
    power_scores = _relative_score(
        [candidate.suitable_charging_power_kw for candidate in candidates],
        higher_is_better=True,
    )
    grid_scores = [max(0.0, 100.0 - candidate.grid_risk_score) for candidate in candidates]
    distance_scores = [_distance_score(candidate.distance_km) for candidate in candidates]

    ranked = []
    for candidate, wait_score, power_score, grid_score, distance_score in zip(
        candidates, wait_scores, power_scores, grid_scores, distance_scores
    ):
        final_score = round(
            (
                wait_score * weights.wait
                + power_score * weights.charging_power
                + grid_score * weights.grid
                + distance_score * weights.distance
            )
            / 100.0,
            2,
        )
        ranked.append(
            (
                final_score,
                candidate,
                wait_score,
                power_score,
                grid_score,
                distance_score,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].predicted_wait_minutes,
            item[1].charger_id,
        )
    )
    best_score, best_candidate, best_wait, best_power, best_grid, best_distance = ranked[0]
    wait_reason = "Recommended because this charger has the lowest predicted waiting time among the evaluated serviceable chargers."
    power_reason = (
        "Charging power is suitable for the EV's maximum charge rate."
        if ev.vehicle.max_charge_rate_kw is not None
        else "Charging power matches the available charger output for this EV."
    )
    if best_candidate.grid_status in {GridStatus.HIGH, GridStatus.OVERLOADED}:
        grid_reason = (
            f"Projected grid stress is {best_candidate.grid_status.value}, but the charger remains a candidate because emergency charging urgency is high."
        )
    else:
        grid_reason = "Projected grid stress remains acceptable within the emergency decision context."

    explanation = " ".join(
        [
            wait_reason,
            power_reason,
            grid_reason,
            "Physical charger reachability cannot be verified from the available vehicle/route data.",
        ]
    )

    recommendation = EmergencyRecommendationDetail(
        charger_id=best_candidate.charger_id,
        station_name=best_candidate.station_name,
        score=best_score,
        predicted_wait_minutes=best_candidate.predicted_wait_minutes,
        distance_km=round(best_candidate.distance_km, 2),
        grid_status=best_candidate.grid_status,
        grid_risk_score=best_candidate.grid_risk_score,
        available_charging_power_kw=best_candidate.available_charging_power_kw,
        explanation=explanation,
    )

    alternatives = [
        EmergencyAlternative(
            charger_id=candidate.charger_id,
            station_name=candidate.station_name,
            score=score,
            predicted_wait_minutes=candidate.predicted_wait_minutes,
            distance_km=round(candidate.distance_km, 2),
            grid_status=candidate.grid_status,
            reason=(
                f"Score {score:.2f}/100 with {candidate.predicted_wait_minutes:.1f} minutes predicted wait and "
                f"{candidate.grid_status.value} grid status."
            ),
        )
        for score, candidate, _, _, _, _ in ranked[1:6]
    ]

    return EmergencyRecommendationResult(
        ev_id=ev_id,
        emergency=EmergencyActivation(
            active=True,
            reason="Emergency mode is active because the EV has CRITICAL charging priority.",
            battery_percent=ev.battery_percent,
            priority_score=priority.priority_score,
            priority_level=priority.priority_level,
        ),
        recommendation=recommendation,
        reachability=reachability,
        score_breakdown=EmergencyScoreBreakdown(
            wait_score=round(best_wait, 2),
            charging_power_score=round(best_power, 2),
            grid_score=round(best_grid, 2),
            distance_score=round(best_distance, 2),
        ),
        weights=weights,
        alternatives=alternatives,
    )

from dataclasses import dataclass
from datetime import datetime, timezone

from ..models import (
    Charger,
    EV,
    EVChargerRecommendation,
    ExcludedRecommendationCandidate,
    GridIntelligenceResult,
    PriorityLevel,
    QueuePrediction,
    RecommendationAlternative,
    RecommendationPrioritySummary,
    RecommendationScoreBreakdown,
    RecommendationWeights,
    RecommendedCharger,
)
from .data_service import get_available_chargers
from .grid_intelligence_service import (
    InvalidGridDataError,
    calculate_grid_intelligence,
)
from .priority_service import calculate_ev_priority
from .queue_prediction_service import (
    InsufficientQueuePredictionDataError,
    predict_queue_for_charger,
)
from .ranking_service import _DISTANCE_SCALE_KM, _distance_km


_MAX_ALTERNATIVES = 5
_MAX_EXCLUDED_CANDIDATES = 5


class NoRecommendationCandidatesError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateEvidence:
    charger_id: str
    station_name: str
    distance_km: float
    predicted_wait_minutes: float
    grid_status: str
    grid_risk_score: float
    available_charging_power_kw: float
    suitable_charging_power_kw: float


def recommendation_weights(priority_score: float) -> RecommendationWeights:
    """Move weight from distance/power toward wait/grid as EV priority rises.

    At priority 0 the weights are 40/25/20/15. At priority 100 they are
    20/40/30/10. The linear transfer preserves a 100% total at every score.
    """
    priority_fraction = min(100, max(0, priority_score)) / 100
    distance = round(40 - 20 * priority_fraction, 2)
    wait = round(25 + 15 * priority_fraction, 2)
    grid = round(20 + 10 * priority_fraction, 2)
    charging_power = round(100 - distance - wait - grid, 2)
    return RecommendationWeights(
        distance=distance,
        wait=wait,
        grid=grid,
        charging_power=charging_power,
    )


def _distance_score(distance_km: float) -> float:
    return round(max(0, 1 - distance_km / _DISTANCE_SCALE_KM) * 100, 2)


def _relative_scores(values: list[float], higher_is_better: bool) -> list[float]:
    if not values:
        return []
    minimum = min(values)
    maximum = max(values)
    if minimum == maximum:
        return [100.0] * len(values)
    span = maximum - minimum
    if higher_is_better:
        return [round((value - minimum) / span * 100, 2) for value in values]
    return [round((maximum - value) / span * 100, 2) for value in values]


def _candidate_reason(candidate: CandidateEvidence, score: float) -> str:
    return (
        f"Score {score:.2f}; predicted wait {candidate.predicted_wait_minutes:.1f} "
        f"minutes; projected grid status {candidate.grid_status}; geographic distance "
        f"{candidate.distance_km:.2f} km."
    )


def _weighting_explanation(priority_score: float) -> str:
    return (
        f"Weights use EV priority {priority_score:.2f}/100: distance starts at 40% "
        "and falls linearly by up to 20 percentage points; wait starts at 25% and "
        "rises by up to 15 points; grid starts at 20% and rises by up to 10 points; "
        "charging power supplies the remaining weight (15% down to 10%). The four "
        "weights always total 100%. Distance uses Phase 6's 50 km straight-line "
        "scale; wait and suitable power are normalized relative to evaluated "
        "candidates; grid score is 100 minus Phase 9 grid risk. Available power is "
        "capped at the EV's maximum charge rate when that value exists."
    )


def score_candidates(
    priority_score: float,
    candidates: list[CandidateEvidence],
):
    weights = recommendation_weights(priority_score)
    wait_scores = _relative_scores(
        [candidate.predicted_wait_minutes for candidate in candidates],
        higher_is_better=False,
    )
    power_scores = _relative_scores(
        [candidate.suitable_charging_power_kw for candidate in candidates],
        higher_is_better=True,
    )

    scored = []
    for candidate, wait_score, power_score in zip(
        candidates, wait_scores, power_scores
    ):
        breakdown = RecommendationScoreBreakdown(
            distance_score=_distance_score(candidate.distance_km),
            wait_score=wait_score,
            grid_score=round(100 - candidate.grid_risk_score, 2),
            charging_power_score=power_score,
        )
        final_score = round(
            (
                breakdown.distance_score * weights.distance
                + breakdown.wait_score * weights.wait
                + breakdown.grid_score * weights.grid
                + breakdown.charging_power_score * weights.charging_power
            )
            / 100,
            2,
        )
        scored.append((candidate, breakdown, final_score))

    return sorted(scored, key=lambda item: (-item[2], item[0].charger_id)), weights


def _priority_summary(priority):
    return RecommendationPrioritySummary(
        score=priority.priority_score,
        level=priority.priority_level,
        explanation=priority.explanation,
    )


def recommend_charger_for_ev(
    ev_id: str,
    ev: EV,
    calculated_at: datetime | None = None,
) -> EVChargerRecommendation:
    timestamp = calculated_at or datetime.now(timezone.utc)
    priority = calculate_ev_priority(ev_id, ev, timestamp)
    chargers = get_available_chargers()
    if not chargers:
        raise NoRecommendationCandidatesError(
            "No available charger candidates have serviceable connectors."
        )

    candidate_evidence = []
    exclusions = []
    for charger_id, charger in chargers:
        available_connectors = [
            connector
            for connector in charger.connectors
            if connector.available_count > 0
        ]
        if not available_connectors:
            exclusions.append(
                ExcludedRecommendationCandidate(
                    charger_id=charger_id,
                    reason="No available connector.",
                )
            )
            continue

        try:
            queue_prediction: QueuePrediction | None = predict_queue_for_charger(
                charger_id,
                prediction_timestamp=timestamp,
            )
        except InsufficientQueuePredictionDataError as exc:
            exclusions.append(
                ExcludedRecommendationCandidate(
                    charger_id=charger_id,
                    reason=f"Queue prediction unavailable: {exc}",
                )
            )
            continue
        if queue_prediction is None:
            exclusions.append(
                ExcludedRecommendationCandidate(
                    charger_id=charger_id,
                    reason="Queue prediction unavailable because the charger no longer exists.",
                )
            )
            continue

        try:
            grid_intelligence: GridIntelligenceResult = calculate_grid_intelligence(
                charger_id,
                charger,
                timestamp,
            )
        except InvalidGridDataError as exc:
            exclusions.append(
                ExcludedRecommendationCandidate(
                    charger_id=charger_id,
                    reason=f"Grid intelligence unavailable: {exc}",
                )
            )
            continue

        available_power = max(connector.power_kw for connector in available_connectors)
        vehicle_max_power = ev.vehicle.max_charge_rate_kw
        suitable_power = (
            min(available_power, vehicle_max_power)
            if vehicle_max_power is not None
            else available_power
        )
        candidate_evidence.append(
            CandidateEvidence(
                charger_id=charger_id,
                station_name=charger.station_name,
                distance_km=_distance_km(ev.current_location, charger.location),
                predicted_wait_minutes=queue_prediction.predicted_wait_minutes,
                grid_status=grid_intelligence.grid_status.value,
                grid_risk_score=grid_intelligence.grid_risk_score,
                available_charging_power_kw=available_power,
                suitable_charging_power_kw=suitable_power,
            )
        )

    if not candidate_evidence:
        reason_summary = "; ".join(
            f"{item.charger_id}: {item.reason}"
            for item in sorted(exclusions, key=lambda item: item.charger_id)[
                :_MAX_EXCLUDED_CANDIDATES
            ]
        )
        raise NoRecommendationCandidatesError(
            "No intelligent recommendation could be produced from the available "
            f"evidence. {reason_summary}"
        )

    ranked, weights = score_candidates(priority.priority_score, candidate_evidence)
    recommended, breakdown, final_score = ranked[0]
    urgency_weighting = (
        "Waiting time and projected grid stress received increased weight for this "
        f"{priority.priority_level.value} priority EV."
        if priority.priority_score >= 50
        else "Distance remains the largest factor for this lower-priority EV."
    )
    recommendation_explanation = (
        f"Selected as the highest-scoring evaluated candidate ({final_score:.2f}/100): "
        f"{recommended.distance_km:.2f} km straight-line geographic distance, "
        f"{recommended.predicted_wait_minutes:.1f} minutes predicted wait, "
        f"{recommended.grid_status} projected grid status (risk "
        f"{recommended.grid_risk_score:.2f}/100), and "
        f"{recommended.available_charging_power_kw:g} kW maximum available connector "
        f"power ({recommended.suitable_charging_power_kw:g} kW suitable power used "
        f"for scoring). EV priority is {priority.priority_level.value} "
        f"({priority.priority_score:.2f}/100). {urgency_weighting}"
    )
    alternative_results = [
        RecommendationAlternative(
            charger_id=candidate.charger_id,
            station_name=candidate.station_name,
            score=score,
            predicted_wait_minutes=candidate.predicted_wait_minutes,
            grid_status=candidate.grid_status,
            reason=_candidate_reason(candidate, score),
        )
        for candidate, _, score in ranked[1 : _MAX_ALTERNATIVES + 1]
    ]
    ordered_exclusions = sorted(exclusions, key=lambda item: item.charger_id)

    return EVChargerRecommendation(
        ev_id=ev_id,
        priority=_priority_summary(priority),
        recommendation=RecommendedCharger(
            charger_id=recommended.charger_id,
            station_name=recommended.station_name,
            score=final_score,
            distance_km=round(recommended.distance_km, 2),
            predicted_wait_minutes=recommended.predicted_wait_minutes,
            grid_status=recommended.grid_status,
            grid_risk_score=recommended.grid_risk_score,
            available_charging_power_kw=recommended.available_charging_power_kw,
            suitable_charging_power_kw=recommended.suitable_charging_power_kw,
            explanation=recommendation_explanation,
        ),
        score_breakdown=breakdown,
        weights=weights,
        weighting_explanation=_weighting_explanation(priority.priority_score),
        alternatives=alternative_results,
        excluded_candidates=ordered_exclusions[:_MAX_EXCLUDED_CANDIDATES],
        excluded_candidate_count=len(ordered_exclusions),
    )
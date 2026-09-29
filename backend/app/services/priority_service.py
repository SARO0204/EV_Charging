from datetime import datetime, timezone

from ..models import EV, EVPriorityResult, PriorityFactor, PriorityLevel


_BASE_WEIGHTS = {
    "batteryUrgency": 0.40,
    "requiredChargeGap": 0.35,
    "existingUrgency": 0.25,
}


def _priority_level(score: float) -> PriorityLevel:
    if score >= 80:
        return PriorityLevel.CRITICAL
    if score >= 50:
        return PriorityLevel.HIGH
    if score >= 25:
        return PriorityLevel.MEDIUM
    return PriorityLevel.LOW


def calculate_ev_priority(
    ev_id: str,
    ev: EV,
    calculated_at: datetime | None = None,
) -> EVPriorityResult:
    """Weight battery state 40%, charge gap 35%, and saved urgency 25%.

    Battery and requested charge define immediate need; saved urgency is secondary
    because it may overlap with those same inputs.
    """
    available_factors = [
        (
            "batteryUrgency",
            ev.battery_percent,
            100 - ev.battery_percent,
            "battery",
        ),
        (
            "requiredChargeGap",
            max(0, ev.required_charge_percent - ev.battery_percent),
            max(0, ev.required_charge_percent - ev.battery_percent),
            "charge gap",
        ),
    ]
    if ev.urgency is not None:
        available_factors.append(
            (
                "existingUrgency",
                ev.urgency.score,
                ev.urgency.score,
                "saved urgency",
            )
        )

    available_weight = sum(_BASE_WEIGHTS[name] for name, *_ in available_factors)
    factors = {}
    score = 0.0
    explanations = []
    for name, value, factor_score, label in available_factors:
        weight = _BASE_WEIGHTS[name] / available_weight
        contribution = round(factor_score * weight, 2)
        score += contribution
        factors[name] = PriorityFactor(
            value=round(value, 2),
            score=round(factor_score, 2),
            weight=round(weight, 4),
            contribution=round(contribution, 2),
        )
        if name == "batteryUrgency":
            explanations.append(
                f"battery at {ev.battery_percent:g}% scores {factor_score:.1f}/100"
            )
        elif name == "requiredChargeGap":
            explanations.append(
                f"the requested charge gap is {value:g} percentage points "
                f"and scores {factor_score:.1f}/100"
            )
        else:
            explanations.append(
                f"the existing urgency score is {factor_score:.1f}/100"
            )

    priority_score = round(min(100, max(0, score)), 2)
    if ev.urgency is None:
        explanations.append(
            "no saved urgency score was available, so its weight was redistributed "
            "across the available factors"
        )
    explanations.append(
        "destination-range pressure was excluded because a reliable route-distance "
        "requirement is not present in the EV data"
    )

    return EVPriorityResult(
        ev_id=ev_id,
        priority_score=priority_score,
        priority_level=_priority_level(priority_score),
        factors=factors,
        explanation="Priority is based on " + "; ".join(explanations) + ".",
        calculated_at=calculated_at or datetime.now(timezone.utc),
    )
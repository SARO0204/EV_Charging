from datetime import datetime, timezone

from ..models import Charger, GridIntelligenceResult, GridStatus


_WATCH_THRESHOLD_PERCENT = 70.0
_HIGH_THRESHOLD_PERCENT = 85.0
_OVERLOADED_THRESHOLD_PERCENT = 100.0


class InvalidGridDataError(ValueError):
    pass


def _grid_status(projected_utilization_percent: float) -> GridStatus:
    if projected_utilization_percent >= _OVERLOADED_THRESHOLD_PERCENT:
        return GridStatus.OVERLOADED
    if projected_utilization_percent >= _HIGH_THRESHOLD_PERCENT:
        return GridStatus.HIGH
    if projected_utilization_percent >= _WATCH_THRESHOLD_PERCENT:
        return GridStatus.WATCH
    return GridStatus.NORMAL


def calculate_grid_intelligence(
    charger_id: str,
    charger: Charger,
    calculated_at: datetime | None = None,
) -> GridIntelligenceResult:
    grid = charger.grid
    if grid.capacity_kw <= 0:
        raise InvalidGridDataError("Grid capacity must be greater than zero.")

    current_utilization = grid.current_load_kw / grid.capacity_kw * 100
    projected_utilization = grid.predicted_peak_load_kw / grid.capacity_kw * 100
    current_headroom = grid.capacity_kw - grid.current_load_kw
    projected_headroom = grid.capacity_kw - grid.predicted_peak_load_kw
    risk_score = round(min(100, max(0, projected_utilization)), 2)
    status = _grid_status(projected_utilization)
    explanation = (
        f"Current load is {grid.current_load_kw:g} kW of {grid.capacity_kw:g} kW "
        f"capacity ({current_utilization:.2f}%), with {current_headroom:.2f} kW "
        f"current headroom. The charger data source supplies a projected peak of "
        f"{grid.predicted_peak_load_kw:g} kW ({projected_utilization:.2f}%), leaving "
        f"{projected_headroom:.2f} kW projected headroom. Status is {status.value} "
        f"based on projected utilization; the grid risk score is the projected "
        f"utilization clamped to 0-100 ({risk_score:.2f}). Expected incoming demand "
        f"is {grid.expected_incoming_demand_kw:g} kW and is contextual only; it is not "
        f"converted into an EV count. The projected peak is supplied data, not an "
        f"ML prediction ({charger.data_source.value})."
    )

    return GridIntelligenceResult(
        charger_id=charger_id,
        current_load_kw=grid.current_load_kw,
        capacity_kw=grid.capacity_kw,
        current_utilization_percent=round(current_utilization, 2),
        current_headroom_kw=round(current_headroom, 2),
        expected_incoming_demand_kw=grid.expected_incoming_demand_kw,
        predicted_peak_load_kw=grid.predicted_peak_load_kw,
        projected_peak_utilization_percent=round(projected_utilization, 2),
        projected_headroom_kw=round(projected_headroom, 2),
        grid_risk_score=risk_score,
        grid_status=status,
        calculated_at=calculated_at or datetime.now(timezone.utc),
        explanation=explanation,
    )
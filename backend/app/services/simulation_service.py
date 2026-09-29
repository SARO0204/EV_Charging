from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from ..models import (
    Charger,
    EV,
    SimulationImpact,
    SimulationInput,
    SimulationMetrics,
    SimulationRequest,
    SimulationResults,
    SimulationRunResult,
    StationSimulationResult,
    StationSimulationSnapshot,
)
from .data_service import get_available_chargers
from .grid_intelligence_service import calculate_grid_intelligence
from .priority_service import calculate_ev_priority
from .ranking_service import _distance_km
from .recommendation_service import CandidateEvidence, score_candidates

MAX_INCOMING_EV_COUNT = 200
MAX_WINDOW_MINUTES = 720


class SimulationValidationError(ValueError):
    pass


class NoSimulationChargerDataError(ValueError):
    pass


def _validate_simulation_inputs(incoming_ev_count: int, window_minutes: int):
    if not isinstance(incoming_ev_count, int):
        raise SimulationValidationError("incoming_ev_count must be an integer.")
    if incoming_ev_count < 1:
        raise SimulationValidationError("incoming_ev_count must be at least 1.")
    if incoming_ev_count > MAX_INCOMING_EV_COUNT:
        raise SimulationValidationError(
            f"incoming_ev_count must be less than or equal to {MAX_INCOMING_EV_COUNT}."
        )
    if not isinstance(window_minutes, int):
        raise SimulationValidationError("window_minutes must be an integer.")
    if window_minutes <= 0:
        raise SimulationValidationError("window_minutes must be greater than 0.")
    if window_minutes > MAX_WINDOW_MINUTES:
        raise SimulationValidationError(
            f"window_minutes must be less than or equal to {MAX_WINDOW_MINUTES}."
        )


def _synthetic_ev(index: int, base_time: datetime):
    battery = 10 + ((index * 17) % 55)
    required = 70 + ((index * 11) % 22)
    if required <= battery:
        required = min(95, battery + 22)
    max_charge_rate = 12 + (index % 4) * 10
    return EV.model_validate(
        {
            "batteryPercent": battery,
            "requiredChargePercent": required,
            "currentLocation": {
                "latitude": 13.0 + ((index % 3) - 1) * 0.015,
                "longitude": 80.0 + ((index % 4) - 1) * 0.012,
            },
            "destination": {"latitude": 13.1, "longitude": 80.1},
            "vehicle": {
                "batteryCapacityKwh": 75,
                "maxChargeRateKw": max_charge_rate,
            },
            "inputSource": "simulated",
            "createdAt": base_time,
            "updatedAt": base_time,
        }
    )


def _serviceable_chargers(charger_pool):
    workable = []
    for charger_id, charger in charger_pool:
        if any(connector.total_count > 0 and connector.available_count > 0 for connector in charger.connectors):
            workable.append((charger_id, charger))
    if not workable:
        raise NoSimulationChargerDataError("No serviceable charger candidates are available for simulation.")
    return workable


def _charger_total_capacity(charger: Charger) -> int:
    return sum(connector.total_count for connector in charger.connectors)


def _charger_max_power(charger: Charger) -> float:
    return max(connector.power_kw for connector in charger.connectors)


def _estimate_duration_minutes(ev: EV, charger: Charger, power_kw: float | None = None) -> float:
    power = power_kw or _charger_max_power(charger)
    if ev.vehicle.max_charge_rate_kw is not None:
        power = min(power, ev.vehicle.max_charge_rate_kw)
    if power <= 0:
        power = 1.0
    energy_required_kwh = max(
        1.0,
        ((ev.required_charge_percent - ev.battery_percent) / 100.0) * ev.vehicle.battery_capacity_kwh,
    )
    return max(10.0, (energy_required_kwh / power) * 60.0)


def _earliest_slot(events, total_connectors: int, arrival_time: datetime, duration_minutes: float):
    current = arrival_time
    window = duration_minutes * 60
    while True:
        overlapping = [
            event
            for event in events
            if event["start"] < (current + timedelta(minutes=duration_minutes))
            and event["end"] > current
        ]
        if len(overlapping) < total_connectors:
            start = current
            end = current + timedelta(minutes=duration_minutes)
            return start, end
        next_end = min(event["end"] for event in overlapping)
        current = next_end
        if current >= arrival_time + timedelta(minutes=window):
            return current, current + timedelta(minutes=duration_minutes)


def _candidate_wait_minutes(charger: Charger) -> float:
    return max(0.0, float(charger.queue.current_count) * 5.0)


def _build_gridflow_candidates(ev: EV, charger_pool):
    priority = calculate_ev_priority(f"sim-{ev.vehicle.battery_capacity_kwh}", ev)
    candidates = []
    for charger_id, charger in charger_pool:
        available_connectors = [
            connector for connector in charger.connectors if connector.available_count > 0
        ]
        if not available_connectors:
            continue
        grid = calculate_grid_intelligence(charger_id, charger)
        available_power = max(connector.power_kw for connector in available_connectors)
        suitable_power = (
            min(available_power, ev.vehicle.max_charge_rate_kw)
            if ev.vehicle.max_charge_rate_kw is not None
            else available_power
        )
        candidates.append(
            CandidateEvidence(
                charger_id=charger_id,
                station_name=charger.station_name,
                distance_km=_distance_km(ev.current_location, charger.location),
                predicted_wait_minutes=_candidate_wait_minutes(charger),
                grid_status=grid.grid_status.value,
                grid_risk_score=grid.grid_risk_score,
                available_charging_power_kw=available_power,
                suitable_charging_power_kw=suitable_power,
            )
        )
    if not candidates:
        return None, priority
    ranked, _ = score_candidates(priority.priority_score, candidates)
    return ranked, priority


def _simulate_one_policy(policy_name: str, evs, charger_pool, window_minutes):
    charger_lookup = {charger_id: charger for charger_id, charger in charger_pool}
    charger_events = {charger_id: [] for charger_id, _ in charger_pool}
    assigned_events = []
    unassigned_count = 0

    for index, ev in enumerate(evs):
        arrival = datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)
        arrival += timedelta(minutes=(window_minutes * (index + 1)) / max(1, len(evs)))
        if policy_name == "baseline":
            eligible = []
            for charger_id, charger in charger_pool:
                total_capacity = _charger_total_capacity(charger)
                if total_capacity <= 0:
                    continue
                if len(charger_events[charger_id]) >= total_capacity:
                    continue
                eligible.append((charger_id, charger))
            if not eligible:
                unassigned_count += 1
                continue
            charger_id, charger = min(
                eligible,
                key=lambda item: _distance_km(ev.current_location, item[1].location),
            )
        else:
            ranked, _ = _build_gridflow_candidates(ev, charger_pool)
            if ranked is None:
                unassigned_count += 1
                continue
            charger_id = ranked[0][0].charger_id
            charger = charger_lookup[charger_id]

        total_connectors = _charger_total_capacity(charger)
        if total_connectors <= 0:
            unassigned_count += 1
            continue

        power = max(connector.power_kw for connector in charger.connectors)
        suitable_power = (
            min(power, ev.vehicle.max_charge_rate_kw)
            if ev.vehicle.max_charge_rate_kw is not None
            else power
        )
        duration_minutes = _estimate_duration_minutes(ev, charger, suitable_power)
        start_time, end_time = _earliest_slot(
            charger_events[charger_id],
            total_connectors,
            arrival,
            duration_minutes,
        )
        wait_minutes = max(0.0, (start_time - arrival).total_seconds() / 60.0)
        if start_time > arrival:
            queue_wait = max(0.0, wait_minutes)
        else:
            queue_wait = 0.0
        event = {
            "ev_id": f"sim-{index}",
            "charger_id": charger_id,
            "start": start_time,
            "end": end_time,
            "queue_wait": queue_wait,
            "duration_minutes": duration_minutes,
            "power_kw": suitable_power,
        }
        charger_events[charger_id].append(event)
        assigned_events.append(event)

    station_results = []
    for charger_id, charger in charger_pool:
        events = charger_events[charger_id]
        queue_count = len(events)
        wait_total = sum(event["queue_wait"] for event in events)
        times = sorted({point for event in events for point in (event["start"], event["end"])})
        peak_load_kw = 0.0
        for index, current_time in enumerate(times[:-1]):
            next_time = times[index + 1]
            if next_time <= current_time:
                continue
            active_power = sum(
                event["power_kw"]
                for event in events
                if event["start"] <= current_time and event["end"] > current_time
            )
            peak_load_kw = max(peak_load_kw, active_power)
        peak_util = (peak_load_kw / max(1.0, charger.grid.capacity_kw)) * 100.0 if charger.grid.capacity_kw else 0.0
        station_results.append(
            StationSimulationResult(
                charger_id=charger_id,
                station_name=charger.station_name,
                baseline=StationSimulationSnapshot(
                    queue=queue_count,
                    wait_minutes=round(wait_total, 2),
                    peak_load_kw=round(peak_load_kw, 2),
                    peak_utilization_percent=round(peak_util, 2),
                ) if policy_name == "baseline" else StationSimulationSnapshot(queue=0, wait_minutes=0.0, peak_load_kw=0.0, peak_utilization_percent=0.0),
                grid_flow=StationSimulationSnapshot(
                    queue=queue_count,
                    wait_minutes=round(wait_total, 2),
                    peak_load_kw=round(peak_load_kw, 2),
                    peak_utilization_percent=round(peak_util, 2),
                ) if policy_name == "gridflow" else StationSimulationSnapshot(queue=0, wait_minutes=0.0, peak_load_kw=0.0, peak_utilization_percent=0.0),
            )
        )

    total_wait = sum(event["queue_wait"] for event in assigned_events)
    avg_wait = total_wait / max(1, len(assigned_events))
    max_wait = max((event["queue_wait"] for event in assigned_events), default=0.0)
    peak_grid_utilization = max(
        (
            (sum(
                event["power_kw"]
                for event in charger_events[charger_id]
                if event["start"] <= time and event["end"] > time
            ) / max(1.0, charger_lookup[charger_id].grid.capacity_kw)) * 100.0
            for charger_id in charger_lookup
            for time in [
                point
                for event in charger_events[charger_id]
                for point in (event["start"], event["end"])
            ]
        ),
        default=0.0,
    )
    overloaded_count = sum(
        1
        for charger_id, charger in charger_pool
        if max(
            (
                (
                    sum(
                        event["power_kw"]
                        for event in charger_events[charger_id]
                        if event["start"] <= time and event["end"] > time
                    )
                    / max(1.0, charger.grid.capacity_kw)
                )
                * 100.0
                for time in [
                    point
                    for event in charger_events[charger_id]
                    for point in (event["start"], event["end"])
                ]
            ),
            default=0.0,
        )
        > 100
    )
    metrics = SimulationMetrics(
        average_wait_minutes=round(avg_wait, 2),
        maximum_wait_minutes=round(max_wait, 2),
        peak_grid_utilization_percent=round(peak_grid_utilization, 2),
        overloaded_station_count=overloaded_count,
        unassigned_ev_count=unassigned_count,
        assigned_ev_count=len(assigned_events),
    )
    return metrics, station_results


def run_simulation(incoming_ev_count: int, window_minutes: int, chargers=None):
    _validate_simulation_inputs(incoming_ev_count, window_minutes)
    charger_pool = chargers if chargers is not None else get_available_chargers()
    if not charger_pool:
        raise NoSimulationChargerDataError("No charger data is available for simulation.")
    charger_pool = _serviceable_chargers(charger_pool)
    evs = [_synthetic_ev(index, datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)) for index in range(incoming_ev_count)]

    baseline_metrics, baseline_stations = _simulate_one_policy("baseline", evs, charger_pool, window_minutes)
    gridflow_metrics, gridflow_stations = _simulate_one_policy("gridflow", evs, charger_pool, window_minutes)

    baseline_stations_by_id = {item.charger_id: item for item in baseline_stations}
    gridflow_stations_by_id = {item.charger_id: item for item in gridflow_stations}
    combined = []
    for charger_id, charger in charger_pool:
        baseline_item = baseline_stations_by_id.get(charger_id)
        gridflow_item = gridflow_stations_by_id.get(charger_id)
        combined.append(
            StationSimulationResult(
                charger_id=charger_id,
                station_name=charger.station_name,
                baseline=baseline_item.baseline if baseline_item else StationSimulationSnapshot(queue=0, wait_minutes=0.0, peak_load_kw=0.0, peak_utilization_percent=0.0),
                grid_flow=gridflow_item.grid_flow if gridflow_item else StationSimulationSnapshot(queue=0, wait_minutes=0.0, peak_load_kw=0.0, peak_utilization_percent=0.0),
            )
        )

    wait_improvement = 0.0
    if baseline_metrics.average_wait_minutes > 0:
        wait_improvement = round(
            ((baseline_metrics.average_wait_minutes - gridflow_metrics.average_wait_minutes) / baseline_metrics.average_wait_minutes) * 100.0,
            2,
        )
    peak_change = 0.0
    if baseline_metrics.peak_grid_utilization_percent > 0:
        peak_change = round(
            ((baseline_metrics.peak_grid_utilization_percent - gridflow_metrics.peak_grid_utilization_percent) / baseline_metrics.peak_grid_utilization_percent) * 100.0,
            2,
        )
    impact = SimulationImpact(
        wait_improvement_percent=wait_improvement,
        peak_grid_utilization_change_percent=peak_change,
        overload_reduction=baseline_metrics.overloaded_station_count - gridflow_metrics.overloaded_station_count,
        unassigned_ev_reduction=baseline_metrics.unassigned_ev_count - gridflow_metrics.unassigned_ev_count,
    )
    input_model = SimulationInput(
        incoming_ev_count=incoming_ev_count,
        window_minutes=window_minutes,
    )
    result = SimulationRunResult(
        simulation_id=f"sim-{uuid4().hex}",
        input=input_model,
        baseline=baseline_metrics,
        grid_flow=gridflow_metrics,
        impact=impact,
        stations=combined,
    )
    return result

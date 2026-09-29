from __future__ import annotations

from collections.abc import Iterable

from .data_service import (
    get_charging_sessions_for_charger,
    list_chargers,
    list_evs,
    list_simulation_runs,
)
from .emergency_service import (
    NoEmergencyRecommendationCandidatesError,
    calculate_emergency_recommendation,
)
from .grid_intelligence_service import InvalidGridDataError, calculate_grid_intelligence
from .priority_service import calculate_ev_priority
from .queue_prediction_service import (
    InsufficientQueuePredictionDataError,
    predict_queue_for_charger,
)


def _charger_operational_state(charger, sessions: Iterable[object]) -> str:
    active_sessions = [
        session for session in sessions if getattr(session, "status", None) is not None and session.status.value == "charging"
    ]
    waiting_sessions = [
        session for session in sessions if getattr(session, "status", None) is not None and session.status.value == "waiting"
    ]
    queue_count = charger.queue.current_count
    if active_sessions:
        return "charging"
    if waiting_sessions or queue_count > 0:
        return "waiting"
    if any(connector.available_count > 0 for connector in charger.connectors):
        return "available"
    return "offline"


def _serialize_charger(charger_id: str, charger, sessions):
    try:
        grid = calculate_grid_intelligence(charger_id, charger)
    except InvalidGridDataError:
        grid = None

    try:
        prediction = predict_queue_for_charger(charger_id)
    except (InsufficientQueuePredictionDataError, InvalidGridDataError, ValueError):
        prediction = None

    available_capacity_kw = round(
        sum(
            connector.available_count * connector.power_kw
            for connector in charger.connectors
        ),
        2,
    )
    total_capacity_kw = round(
        sum(
            connector.total_count * connector.power_kw
            for connector in charger.connectors
        ),
        2,
    )
    operational_state = _charger_operational_state(charger, sessions)
    return {
        "id": charger_id,
        "station_name": charger.station_name,
        "current_queue": charger.queue.current_count,
        "predicted_wait_minutes": round(prediction.predicted_wait_minutes, 2) if prediction else 0.0,
        "predicted_queue": prediction.predicted_queue_count if prediction else 0,
        "current_grid_utilization_percent": round(grid.current_utilization_percent, 2) if grid else 0.0,
        "projected_peak_grid_utilization_percent": round(grid.projected_peak_utilization_percent, 2) if grid else 0.0,
        "grid_status": grid.grid_status.value if grid else "NORMAL",
        "grid_risk_score": round(grid.grid_risk_score, 2) if grid else 0.0,
        "available_charging_capacity_kw": available_capacity_kw,
        "total_charging_capacity_kw": total_capacity_kw,
        "available_connectors": sum(connector.available_count for connector in charger.connectors),
        "total_connectors": sum(connector.total_count for connector in charger.connectors),
        "operational_state": operational_state,
        "current_load_kw": round(charger.grid.current_load_kw, 2),
        "capacity_kw": round(charger.grid.capacity_kw, 2),
        "projected_peak_load_kw": round(charger.grid.predicted_peak_load_kw, 2),
        "current_headroom_kw": round(charger.grid.capacity_kw - charger.grid.current_load_kw, 2),
        "projected_headroom_kw": round(charger.grid.capacity_kw - charger.grid.predicted_peak_load_kw, 2),
    }


def _serialize_ev(ev_id: str, ev):
    priority = calculate_ev_priority(ev_id, ev)
    emergency_status = "not_available"
    try:
        emergency = calculate_emergency_recommendation(ev_id, ev)
        if emergency.emergency.active:
            emergency_status = "critical"
        else:
            emergency_status = "standard"
    except (NoEmergencyRecommendationCandidatesError, ValueError):
        emergency_status = "not_available"

    current_charger = None
    if ev.current_recommendation is not None:
        current_charger = ev.current_recommendation.charger_id

    return {
        "id": ev_id,
        "battery_percent": round(ev.battery_percent, 2),
        "priority_score": round(priority.priority_score, 2),
        "priority_level": priority.priority_level.value,
        "current_charger": current_charger,
        "current_recommendation": ev.current_recommendation.model_dump(by_alias=True, mode="json") if ev.current_recommendation else None,
        "emergency_status": emergency_status,
    }


def _latest_simulation_result():
    runs = list_simulation_runs()
    if not runs:
        return {"available": False, "message": "No simulation run available."}

    latest = max(runs, key=lambda item: item[1].created_at)
    _document_id, simulation_run = latest
    result = {
        "available": True,
        "simulation_id": _document_id,
        "incoming_ev_count": simulation_run.input.incoming_ev_count,
        "window_minutes": simulation_run.input.window_minutes,
        "baseline_average_wait_minutes": round(simulation_run.results.baseline.average_wait_minutes, 2),
        "gridflow_average_wait_minutes": round(simulation_run.results.grid_flow.average_wait_minutes, 2),
        "baseline_peak_utilization_percent": round(simulation_run.results.baseline.peak_grid_utilization_percent, 2),
        "gridflow_peak_utilization_percent": round(simulation_run.results.grid_flow.peak_grid_utilization_percent, 2),
        "overloaded_station_count": simulation_run.results.baseline.overloaded_station_count,
        "unassigned_ev_count": simulation_run.results.baseline.unassigned_ev_count,
        "wait_improvement_percent": round(simulation_run.results.baseline.average_wait_minutes - simulation_run.results.grid_flow.average_wait_minutes, 2),
    }
    return {"available": True, "message": "Simulation summary available.", "result": result}


def build_dashboard_overview():
    chargers = list_chargers()
    evs = list_evs()

    all_sessions = []
    for charger_id, charger in chargers:
        all_sessions.extend(get_charging_sessions_for_charger(charger_id))

    charging_ev_count = sum(
        1
        for session in all_sessions
        if getattr(session, "status", None) is not None and session.status.value == "charging"
    )
    waiting_ev_count = sum(
        1
        for session in all_sessions
        if getattr(session, "status", None) is not None and session.status.value == "waiting"
    )

    charger_rows = []
    total_utilization = 0.0
    congested_charger_count = 0
    avg_predicted_wait = 0.0
    for charger_id, charger in chargers:
        sessions = get_charging_sessions_for_charger(charger_id)
        serializer = _serialize_charger(charger_id, charger, sessions)
        charger_rows.append(serializer)
        try:
            grid = calculate_grid_intelligence(charger_id, charger)
            total_utilization += grid.current_utilization_percent
            if grid.grid_status.value in {"HIGH", "OVERLOADED"}:
                congested_charger_count += 1
            if serializer["predicted_wait_minutes"] > 0:
                avg_predicted_wait += serializer["predicted_wait_minutes"]
        except InvalidGridDataError:
            continue

    if charger_rows:
        avg_predicted_wait = round(avg_predicted_wait / len(charger_rows), 2)
        total_utilization = round(total_utilization / len(charger_rows), 2)

    ev_rows = [_serialize_ev(ev_id, ev) for ev_id, ev in evs]

    return {
        "overview": {
            "connected_ev_count": len(evs),
            "charging_ev_count": charging_ev_count,
            "waiting_ev_count": waiting_ev_count,
            "average_predicted_wait_minutes": avg_predicted_wait,
            "congested_charger_count": congested_charger_count,
            "overall_grid_utilization_percent": total_utilization,
        },
        "chargers": charger_rows,
        "evs": ev_rows,
        "grid": charger_rows,
        "simulation": _latest_simulation_result(),
    }

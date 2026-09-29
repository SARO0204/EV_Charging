from fastapi import APIRouter, HTTPException, Path

from ..models import (
    EVChargerRecommendation,
    EVPriorityResult,
    EVSlotRecommendation,
    EmergencyRecommendationResult,
)
from ..services.data_service import get_ev_by_id
from ..services.emergency_service import (
    NoEmergencyRecommendationCandidatesError,
    calculate_emergency_recommendation,
)
from ..services.priority_service import calculate_ev_priority
from ..services.recommendation_service import (
    NoRecommendationCandidatesError,
    recommend_charger_for_ev,
)
from ..services.slot_service import (
    ChargerNotFoundError,
    NoChargingNeedError,
    NoConnectorCapacityError,
    NoPracticalSlotError,
    recommend_slot_for_ev,
)


router = APIRouter(prefix="/api/ev", tags=["EV"])


@router.get("/{ev_id}")
def read_ev(ev_id: str = Path(min_length=1, pattern=r"^[^/]+$")):
    record = get_ev_by_id(ev_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EV was not found.")

    document_id, ev = record
    return {"id": document_id, **ev.model_dump(by_alias=True, mode="json")}


@router.get(
    "/{ev_id}/priority",
    response_model=EVPriorityResult,
)
def read_ev_priority(ev_id: str = Path(min_length=1, pattern=r"^[^/]+$")):
    record = get_ev_by_id(ev_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EV was not found.")

    document_id, ev = record
    return calculate_ev_priority(document_id, ev)


@router.get(
    "/{ev_id}/recommendation",
    response_model=EVChargerRecommendation,
)
def read_ev_recommendation(ev_id: str = Path(min_length=1, pattern=r"^[^/]+$")):
    record = get_ev_by_id(ev_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EV was not found.")

    document_id, ev = record
    try:
        return recommend_charger_for_ev(document_id, ev)
    except NoRecommendationCandidatesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{ev_id}/slot-recommendation",
    response_model=EVSlotRecommendation,
)
def read_ev_slot_recommendation(
    ev_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    record = get_ev_by_id(ev_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EV was not found.")

    document_id, ev = record
    try:
        return recommend_slot_for_ev(document_id, ev)
    except ChargerNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        NoChargingNeedError,
        NoConnectorCapacityError,
        NoPracticalSlotError,
        NoRecommendationCandidatesError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/{ev_id}/emergency",
    response_model=EmergencyRecommendationResult,
    operation_id="read_ev_emergency_v1",
)
def read_ev_emergency(
    ev_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    record = get_ev_by_id(ev_id)
    if record is None:
        raise HTTPException(status_code=404, detail="EV was not found.")

    document_id, ev = record
    try:
        return calculate_emergency_recommendation(document_id, ev)
    except NoEmergencyRecommendationCandidatesError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
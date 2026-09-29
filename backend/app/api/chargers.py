from fastapi import APIRouter, HTTPException, Path

from ..services.data_service import get_available_chargers, get_charger_by_id
from ..services.grid_intelligence_service import calculate_grid_intelligence
from ..models import GridIntelligenceResult


router = APIRouter(prefix="/api/chargers", tags=["Chargers"])


@router.get("")
def read_available_chargers():
    chargers = get_available_chargers()
    items = [
        {"id": charger_id, **charger.model_dump(by_alias=True, mode="json")}
        for charger_id, charger in chargers
    ]
    return {"items": items, "count": len(items)}


@router.get("/{charger_id}")
def read_charger(charger_id: str = Path(min_length=1, pattern=r"^[^/]+$")):
    record = get_charger_by_id(charger_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Charger was not found.")

    document_id, charger = record
    return {"id": document_id, **charger.model_dump(by_alias=True, mode="json")}


@router.get(
    "/{charger_id}/grid",
    response_model=GridIntelligenceResult,
)
def read_charger_grid(charger_id: str = Path(min_length=1, pattern=r"^[^/]+$")):
    record = get_charger_by_id(charger_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Charger was not found.")

    document_id, charger = record
    return calculate_grid_intelligence(document_id, charger)
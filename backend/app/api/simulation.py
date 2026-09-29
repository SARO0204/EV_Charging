from fastapi import APIRouter, HTTPException

from ..models import SimulationRequest, SimulationRunResult
from ..services.data_service import InvalidDocumentIdError, get_available_chargers
from ..services.simulation_service import NoSimulationChargerDataError, run_simulation

router = APIRouter(prefix="/api/simulation", tags=["Simulation"])


@router.post("/run", response_model=SimulationRunResult)
def run_simulation_route(request: SimulationRequest):
    try:
        charger_pool = get_available_chargers()
        return run_simulation(
            request.incoming_ev_count,
            request.window_minutes,
            chargers=charger_pool,
        )
    except (InvalidDocumentIdError, NoSimulationChargerDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

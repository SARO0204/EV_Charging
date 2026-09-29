from fastapi import APIRouter

from ..services.dashboard_service import build_dashboard_overview

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


@router.get("/overview", operation_id="read_dashboard_overview")
def read_dashboard_overview():
    return build_dashboard_overview()

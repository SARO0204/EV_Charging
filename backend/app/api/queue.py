from fastapi import APIRouter, HTTPException, Path

from ..models import QueuePrediction
from ..services.queue_prediction_service import predict_queue_for_charger


router = APIRouter(prefix="/api/queue", tags=["Queue"])


@router.get(
    "/{charger_id}/prediction",
    response_model=QueuePrediction,
)
def read_queue_prediction(
    charger_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    prediction = predict_queue_for_charger(charger_id)
    if prediction is None:
        raise HTTPException(status_code=404, detail="Charger was not found.")
    return prediction
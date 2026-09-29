from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path

from ..models import (
    ReservationCreateRequest,
    ReservationReallocationAssessment,
    ReservationRecord,
)
from ..services.data_service import (
    InvalidDocumentIdError,
    MalformedFirestoreDocumentError,
    ReservationChargerNotFoundError,
    ReservationConflictError,
)
from ..services.reallocation_service import (
    ReallocationUnavailableError,
    check_reallocation,
    reallocate_reservation,
)
from ..services.slot_service import (
    ChargerNotFoundError,
    EVNotFoundError,
    InvalidReservationStateError,
    NoChargingNeedError,
    NoConnectorCapacityError,
    NoPracticalSlotError,
    cancel_reservation,
    create_reservation,
    get_reservation,
)


router = APIRouter(prefix="/api/reservations", tags=["Reservations"])


def _reservation_response(record):
    reservation_id, reservation = record
    return ReservationRecord(
        id=reservation_id,
        **reservation.model_dump(),
    )


@router.post("", response_model=ReservationRecord, status_code=201)
def create_reservation_route(request: ReservationCreateRequest):
    try:
        record = create_reservation(request)
    except (
        EVNotFoundError,
        ChargerNotFoundError,
        ReservationChargerNotFoundError,
    ) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        InvalidDocumentIdError,
        NoChargingNeedError,
        NoConnectorCapacityError,
        NoPracticalSlotError,
        ReservationConflictError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalformedFirestoreDocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _reservation_response(record)


@router.get("/{reservation_id}", response_model=ReservationRecord)
def read_reservation(
    reservation_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    try:
        record = get_reservation(reservation_id)
    except InvalidDocumentIdError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Reservation was not found.")
    return _reservation_response(record)


@router.patch("/{reservation_id}/cancel", response_model=ReservationRecord)
def cancel_reservation_route(
    reservation_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    try:
        record = cancel_reservation(reservation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDocumentIdError, InvalidReservationStateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _reservation_response(record)


@router.get(
    "/{reservation_id}/reallocation-check",
    response_model=ReservationReallocationAssessment,
    operation_id="read_reservation_reallocation_check_v1",
)
def read_reservation_reallocation_check(
    reservation_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    try:
        return check_reallocation(reservation_id, datetime.now(timezone.utc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDocumentIdError, InvalidReservationStateError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalformedFirestoreDocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/{reservation_id}/reallocate",
    response_model=ReservationReallocationAssessment,
    operation_id="apply_reservation_reallocation_v1",
)
def apply_reservation_reallocation(
    reservation_id: str = Path(min_length=1, pattern=r"^[^/]+$"),
):
    try:
        return reallocate_reservation(reservation_id, datetime.now(timezone.utc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (InvalidDocumentIdError, InvalidReservationStateError, ReallocationUnavailableError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except MalformedFirestoreDocumentError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
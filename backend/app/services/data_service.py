from pydantic import ValidationError

from ..models import Charger, ChargingSession, EV, Reservation, SimulationRun
from .data_errors import (
    FirestoreMalformedReservationDataError,
    FirestoreReservationChargerNotFoundError,
    FirestoreReservationConflictError,
)
from .data_provider import get_data_provider


class InvalidDocumentIdError(ValueError):
    pass


class MalformedFirestoreDocumentError(RuntimeError):
    pass


class ReservationConflictError(ValueError):
    pass


class ReservationChargerNotFoundError(LookupError):
    pass


def _validate_document_id(document_id):
    if (
        not isinstance(document_id, str)
        or not document_id.strip()
        or document_id != document_id.strip()
        or "/" in document_id
    ):
        raise InvalidDocumentIdError(
            "Document IDs must be non-empty and cannot contain slashes or surrounding whitespace."
        )


def _parse_document(collection_name, document_id, data, model):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise MalformedFirestoreDocumentError(
            f"Document '{document_id}' in '{collection_name}' does not match the expected schema."
        ) from exc


def list_evs():
    return [
        (document_id, _parse_document("evs", document_id, data, EV))
        for document_id, data in get_data_provider().list_ev_documents()
    ]


def get_ev_by_id(ev_id):
    _validate_document_id(ev_id)
    document = get_data_provider().get_ev_document(ev_id)
    if document is None:
        return None
    document_id, data = document
    return document_id, _parse_document("evs", document_id, data, EV)


def list_chargers():
    return [
        (document_id, _parse_document("chargers", document_id, data, Charger))
        for document_id, data in get_data_provider().list_charger_documents()
    ]


def get_available_chargers():
    chargers = []
    for document_id, data in get_data_provider().list_charger_documents():
        charger = _parse_document("chargers", document_id, data, Charger)
        if any(connector.available_count > 0 for connector in charger.connectors):
            chargers.append((document_id, charger))
    return chargers


def get_charger_by_id(charger_id):
    _validate_document_id(charger_id)
    document = get_data_provider().get_charger_document(charger_id)
    if document is None:
        return None
    document_id, data = document
    return document_id, _parse_document("chargers", document_id, data, Charger)


def get_charging_sessions_for_charger(charger_id):
    _validate_document_id(charger_id)
    return [
        _parse_document("charging_sessions", document_id, data, ChargingSession)
        for document_id, data in get_data_provider().list_charging_session_documents(charger_id)
    ]


def get_reservations_for_charger(charger_id):
    _validate_document_id(charger_id)
    return [
        _parse_document("reservations", document_id, data, Reservation)
        for document_id, data in get_data_provider().list_reservation_documents(charger_id)
    ]


def get_reservation_by_id(reservation_id):
    _validate_document_id(reservation_id)
    document = get_data_provider().get_reservation_document(reservation_id)
    if document is None:
        return None
    document_id, data = document
    return document_id, _parse_document(
        "reservations", document_id, data, Reservation
    )


def list_simulation_runs():
    return [
        (document_id, _parse_document("simulation_runs", document_id, data, SimulationRun))
        for document_id, data in get_data_provider().list_simulation_run_documents()
    ]


def create_reservation_record(reservation, allocation_validator):
    def validate_transaction_documents(
        charger_id,
        charger_data,
        reservation_documents,
        session_documents,
    ):
        try:
            charger = _parse_document("chargers", charger_id, charger_data, Charger)
            reservations = [
                _parse_document("reservations", document_id, data, Reservation)
                for document_id, data in reservation_documents
            ]
            sessions = [
                _parse_document(
                    "charging_sessions", document_id, data, ChargingSession
                )
                for document_id, data in session_documents
            ]
        except MalformedFirestoreDocumentError as exc:
            return "malformed", str(exc)

        conflict = allocation_validator(charger, reservations, sessions)
        if conflict:
            return "conflict", conflict
        return None

    try:
        reservation_id = get_data_provider().create_reservation_document(
            reservation.model_dump(by_alias=True, mode="python"),
            validate_transaction_documents,
        )
    except FirestoreReservationConflictError as exc:
        raise ReservationConflictError(str(exc)) from exc
    except FirestoreReservationChargerNotFoundError as exc:
        raise ReservationChargerNotFoundError(str(exc)) from exc
    except FirestoreMalformedReservationDataError as exc:
        raise MalformedFirestoreDocumentError(str(exc)) from exc
    return reservation_id, reservation


def cancel_reservation_by_id(reservation_id, updated_at):
    _validate_document_id(reservation_id)
    result = get_data_provider().cancel_reservation_document(
        reservation_id,
        updated_at,
        cancellable_statuses=["proposed", "confirmed"],
    )
    if result["outcome"] == "not_found":
        return None
    reservation = _parse_document(
        "reservations",
        reservation_id,
        result["data"],
        Reservation,
    )
    return reservation_id, reservation, result["outcome"] == "cancelled"


def reallocate_reservation_document(*args, **kwargs):
    return get_data_provider().reallocate_reservation_document(*args, **kwargs)

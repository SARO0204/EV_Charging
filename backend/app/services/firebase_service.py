import os
from collections.abc import Mapping
from pathlib import Path

from .data_errors import (
    FirebaseConfigurationError,
    FirestoreMalformedReservationDataError,
    FirestoreReadError,
    FirestoreReservationChargerNotFoundError,
    FirestoreReservationConflictError,
    FirestoreStaleReservationStateError,
    FirestoreWriteError,
)

import firebase_admin
from google.cloud.firestore_v1 import GeoPoint as FirestoreGeoPoint
from firebase_admin import credentials, firestore


def get_firestore_client():
    project_id = os.getenv("FIREBASE_PROJECT_ID")
    if not project_id:
        raise FirebaseConfigurationError(
            "Firebase is not configured. Set FIREBASE_PROJECT_ID and provide "
            "Application Default Credentials or GOOGLE_APPLICATION_CREDENTIALS."
        )

    credential_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if credential_path:
        credential_file = Path(credential_path).expanduser()
        if not credential_file.is_file():
            raise FirebaseConfigurationError(
                "GOOGLE_APPLICATION_CREDENTIALS must point to an existing "
                "service-account JSON file."
            )
    else:
        credential_file = None

    try:
        app = firebase_admin.get_app()
    except ValueError:
        try:
            credential = (
                credentials.Certificate(str(credential_file))
                if credential_file
                else None
            )
            app = firebase_admin.initialize_app(
                credential,
                options={"projectId": project_id},
            )
        except Exception as exc:
            raise FirebaseConfigurationError(
                "Firebase initialization failed. Check FIREBASE_PROJECT_ID and "
                "the configured service-account file or Application Default Credentials."
            ) from exc

    try:
        return firestore.client(app=app)
    except Exception as exc:
        raise FirebaseConfigurationError(
            "Could not create the Firestore client. Check the Firebase credentials "
            "and project configuration."
        ) from exc


def check_firestore_connection():
    client = get_firestore_client()
    try:
        next(client.collections(), None)
    except Exception as exc:
        raise FirebaseConfigurationError(
            "Firestore connection check failed. Verify the credentials, Firestore "
            "API, network access, and project permissions."
        ) from exc
    return True


def _read_firestore(collection_name, read_operation):
    try:
        return read_operation(get_firestore_client().collection(collection_name))
    except FirebaseConfigurationError:
        raise
    except Exception as exc:
        raise FirestoreReadError(
            f"Could not read documents from the {collection_name} collection."
        ) from exc


def _document_data(snapshot):
    if not snapshot.exists:
        return None
    return snapshot.id, _normalize_firestore_value(snapshot.to_dict() or {})


def _normalize_firestore_value(value):
    if isinstance(value, FirestoreGeoPoint):
        return {"latitude": value.latitude, "longitude": value.longitude}
    if isinstance(value, Mapping):
        return {
            key: _normalize_firestore_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_normalize_firestore_value(item) for item in value]
    return value


def get_ev_document(ev_id):
    return _read_firestore(
        "evs",
        lambda collection: _document_data(collection.document(ev_id).get()),
    )


def list_ev_documents():
    return _read_firestore(
        "evs",
        lambda collection: [
            (
                document.id,
                _normalize_firestore_value(document.to_dict() or {}),
            )
            for document in collection.stream()
        ],
    )


def list_charger_documents():
    return _read_firestore(
        "chargers",
        lambda collection: [
            (
                document.id,
                _normalize_firestore_value(document.to_dict() or {}),
            )
            for document in collection.stream()
        ],
    )


def list_simulation_run_documents():
    return _read_firestore(
        "simulation_runs",
        lambda collection: [
            (
                document.id,
                _normalize_firestore_value(document.to_dict() or {}),
            )
            for document in collection.stream()
        ],
    )


def list_charging_session_documents(charger_id):
    return _read_firestore(
        "charging_sessions",
        lambda collection: [
            (
                document.id,
                _normalize_firestore_value(document.to_dict() or {}),
            )
            for document in collection.where(
                "chargerId", "==", charger_id
            ).stream()
        ],
    )


def list_reservation_documents(charger_id):
    return _read_firestore(
        "reservations",
        lambda collection: [
            (
                document.id,
                _normalize_firestore_value(document.to_dict() or {}),
            )
            for document in collection.where(
                "chargerId", "==", charger_id
            ).stream()
        ],
    )


def get_charger_document(charger_id):
    return _read_firestore(
        "chargers",
        lambda collection: _document_data(
            collection.document(charger_id).get()
        ),
    )


def get_reservation_document(reservation_id):
    return _read_firestore(
        "reservations",
        lambda collection: _document_data(
            collection.document(reservation_id).get()
        ),
    )


def create_reservation_document(reservation_data, allocation_validator):
    client = get_firestore_client()
    reservations = client.collection("reservations")
    reservation_ref = reservations.document()
    charger_id = reservation_data["chargerId"]
    charger_ref = client.collection("chargers").document(charger_id)
    existing_reservations = reservations.where("chargerId", "==", charger_id)
    existing_sessions = client.collection("charging_sessions").where(
        "chargerId", "==", charger_id
    )

    @firestore.transactional
    def create_in_transaction(transaction):
        charger_snapshot = next(transaction.get(charger_ref), None)
        if charger_snapshot is None or not charger_snapshot.exists:
            return {"outcome": "charger_not_found"}

        reservation_snapshots = list(transaction.get(existing_reservations))
        session_snapshots = list(transaction.get(existing_sessions))
        outcome = allocation_validator(
            charger_snapshot.id,
            _normalize_firestore_value(charger_snapshot.to_dict() or {}),
            [
                (snapshot.id, _normalize_firestore_value(snapshot.to_dict() or {}))
                for snapshot in reservation_snapshots
            ],
            [
                (snapshot.id, _normalize_firestore_value(snapshot.to_dict() or {}))
                for snapshot in session_snapshots
            ],
        )
        if outcome is not None:
            return {"outcome": outcome[0], "detail": outcome[1]}

        transaction.create(reservation_ref, reservation_data)
        return {"outcome": "created", "reservation_id": reservation_ref.id}

    try:
        result = create_in_transaction(client.transaction())
    except FirebaseConfigurationError:
        raise
    except Exception as exc:
        raise FirestoreWriteError(
            "Could not create the reservation in Firestore."
        ) from exc

    if result["outcome"] == "charger_not_found":
        raise FirestoreReservationChargerNotFoundError(
            f"Charger '{charger_id}' was not found during reservation allocation."
        )
    if result["outcome"] == "conflict":
        raise FirestoreReservationConflictError(result["detail"])
    if result["outcome"] == "malformed":
        raise FirestoreMalformedReservationDataError(result["detail"])
    return result["reservation_id"]


def cancel_reservation_document(
    reservation_id,
    updated_at,
    cancellable_statuses,
):
    client = get_firestore_client()
    reservation_ref = client.collection("reservations").document(reservation_id)

    @firestore.transactional
    def cancel_in_transaction(transaction):
        snapshot = next(transaction.get(reservation_ref), None)
        if snapshot is None or not snapshot.exists:
            return {"outcome": "not_found"}

        data = snapshot.to_dict() or {}
        if data.get("status") not in cancellable_statuses:
            return {
                "outcome": "invalid_state",
                "data": _normalize_firestore_value(data),
            }

        transaction.update(
            reservation_ref,
            {"status": "cancelled", "updatedAt": updated_at},
        )
        data.update({"status": "cancelled", "updatedAt": updated_at})
        return {"outcome": "cancelled", "data": _normalize_firestore_value(data)}

    try:
        return cancel_in_transaction(client.transaction())
    except FirebaseConfigurationError:
        raise
    except Exception as exc:
        raise FirestoreWriteError(
            "Could not update the reservation in Firestore."
        ) from exc


def reallocate_reservation_document(
    reservation_id,
    new_charger_id,
    new_slot_start,
    new_slot_end,
    updated_at,
    change_reason,
    allocation_validator,
):
    client = get_firestore_client()
    reservation_ref = client.collection("reservations").document(reservation_id)
    charger_ref = client.collection("chargers").document(new_charger_id)
    reservation_collection = client.collection("reservations")
    session_collection = client.collection("charging_sessions")

    @firestore.transactional
    def reallocate_in_transaction(transaction):
        reservation_snapshot = next(transaction.get(reservation_ref), None)
        if reservation_snapshot is None or not reservation_snapshot.exists:
            return {"outcome": "not_found"}

        reservation_data = _normalize_firestore_value(reservation_snapshot.to_dict() or {})
        if reservation_data.get("status") not in {"proposed", "confirmed"}:
            return {"outcome": "invalid_state", "detail": "Reservation is not in a reallocatable status."}

        charger_snapshot = next(transaction.get(charger_ref), None)
        if charger_snapshot is None or not charger_snapshot.exists:
            return {"outcome": "charger_not_found"}

        reservation_documents = [
            (snapshot.id, _normalize_firestore_value(snapshot.to_dict() or {}))
            for snapshot in transaction.get(
                reservation_collection.where("chargerId", "==", new_charger_id)
            )
        ]
        session_documents = [
            (snapshot.id, _normalize_firestore_value(snapshot.to_dict() or {}))
            for snapshot in transaction.get(
                session_collection.where("chargerId", "==", new_charger_id)
            )
        ]

        outcome = allocation_validator(
            new_charger_id,
            _normalize_firestore_value(charger_snapshot.to_dict() or {}),
            reservation_documents,
            session_documents,
            reservation_data,
        )
        if outcome is not None:
            return {"outcome": outcome[0], "detail": outcome[1]}

        history = list(reservation_data.get("allocationHistory", []))
        history.append(
            {
                "chargerId": reservation_data.get("chargerId"),
                "slotStart": reservation_data.get("slotStart"),
                "slotEnd": reservation_data.get("slotEnd"),
                "changeReason": change_reason,
                "changedAt": updated_at,
            }
        )
        updated_data = dict(reservation_data)
        updated_data.update(
            {
                "chargerId": new_charger_id,
                "slotStart": new_slot_start,
                "slotEnd": new_slot_end,
                "updatedAt": updated_at,
                "allocationHistory": history,
            }
        )
        transaction.update(
            reservation_ref,
            {
                "chargerId": new_charger_id,
                "slotStart": new_slot_start,
                "slotEnd": new_slot_end,
                "updatedAt": updated_at,
                "allocationHistory": history,
            },
        )
        return {"outcome": "updated", "data": _normalize_firestore_value(updated_data)}

    try:
        return reallocate_in_transaction(client.transaction())
    except FirebaseConfigurationError:
        raise
    except Exception as exc:
        raise FirestoreWriteError(
            "Could not reallocate the reservation in Firestore."
        ) from exc
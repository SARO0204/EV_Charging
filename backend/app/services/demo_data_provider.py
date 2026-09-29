import copy
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from .data_errors import (
    FirestoreMalformedReservationDataError,
    FirestoreReservationChargerNotFoundError,
    FirestoreReservationConflictError,
)


class DemoDataConfigurationError(RuntimeError):
    pass


_TIME_MARKER = re.compile(r"^@(now|ago|ahead)(?::(\d+))?$")


def _resolve_fixture_value(value, now):
    if isinstance(value, dict):
        return {key: _resolve_fixture_value(item, now) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_fixture_value(item, now) for item in value]
    if isinstance(value, str):
        match = _TIME_MARKER.fullmatch(value)
        if match:
            direction, seconds = match.groups()
            offset = int(seconds or 0)
            if direction == "ago":
                return now - timedelta(seconds=offset)
            if direction == "ahead":
                return now + timedelta(seconds=offset)
            return now
    return value


class DemoDataProvider:
    """Fixture-backed, process-local data source for controlled demonstrations."""

    def __init__(self, fixture_path):
        self._lock = threading.RLock()
        try:
            with Path(fixture_path).expanduser().open(encoding="utf-8") as fixture_file:
                fixture = json.load(fixture_file)
        except (OSError, json.JSONDecodeError) as exc:
            raise DemoDataConfigurationError(
                f"Could not load the GridFlow demo data fixture at '{fixture_path}'."
            ) from exc

        now = datetime.now(timezone.utc)
        self._collections = _resolve_fixture_value(fixture, now)
        if not isinstance(self._collections, dict):
            raise DemoDataConfigurationError("The demo data fixture must be a JSON object.")
        for collection_name in (
            "evs",
            "chargers",
            "charging_sessions",
            "reservations",
            "simulation_runs",
        ):
            collection = self._collections.setdefault(collection_name, {})
            if not isinstance(collection, dict):
                raise DemoDataConfigurationError(
                    f"The '{collection_name}' demo collection must be an object."
                )
        self._reservation_sequence = len(self._collections["reservations"]) + 1

    def _list(self, collection_name, predicate=lambda _document_id, _data: True):
        with self._lock:
            return [
                (document_id, copy.deepcopy(data))
                for document_id, data in self._collections[collection_name].items()
                if predicate(document_id, data)
            ]

    def _get(self, collection_name, document_id):
        with self._lock:
            data = self._collections[collection_name].get(document_id)
            return (document_id, copy.deepcopy(data)) if data is not None else None

    def get_ev_document(self, ev_id):
        return self._get("evs", ev_id)

    def list_ev_documents(self):
        return self._list("evs")

    def list_charger_documents(self):
        return self._list("chargers")

    def list_simulation_run_documents(self):
        return self._list("simulation_runs")

    def list_charging_session_documents(self, charger_id):
        return self._list(
            "charging_sessions", lambda _id, data: data.get("chargerId") == charger_id
        )

    def list_reservation_documents(self, charger_id):
        return self._list(
            "reservations", lambda _id, data: data.get("chargerId") == charger_id
        )

    def get_charger_document(self, charger_id):
        return self._get("chargers", charger_id)

    def get_reservation_document(self, reservation_id):
        return self._get("reservations", reservation_id)

    def create_reservation_document(self, reservation_data, allocation_validator):
        with self._lock:
            charger_id = reservation_data["chargerId"]
            charger_data = self._collections["chargers"].get(charger_id)
            if charger_data is None:
                raise FirestoreReservationChargerNotFoundError(
                    f"Charger '{charger_id}' was not found during reservation allocation."
                )
            reservations = self.list_reservation_documents(charger_id)
            sessions = self.list_charging_session_documents(charger_id)
            outcome = allocation_validator(charger_id, copy.deepcopy(charger_data), reservations, sessions)
            if outcome is not None:
                if outcome[0] == "malformed":
                    raise FirestoreMalformedReservationDataError(outcome[1])
                raise FirestoreReservationConflictError(outcome[1])

            reservation_id = f"demo-reservation-{self._reservation_sequence}"
            self._reservation_sequence += 1
            self._collections["reservations"][reservation_id] = copy.deepcopy(
                reservation_data
            )
            return reservation_id

    def cancel_reservation_document(self, reservation_id, updated_at, cancellable_statuses):
        with self._lock:
            data = self._collections["reservations"].get(reservation_id)
            if data is None:
                return {"outcome": "not_found"}
            updated_data = copy.deepcopy(data)
            if updated_data.get("status") not in cancellable_statuses:
                return {"outcome": "invalid_state", "data": updated_data}
            updated_data.update({"status": "cancelled", "updatedAt": updated_at})
            self._collections["reservations"][reservation_id] = updated_data
            return {"outcome": "cancelled", "data": copy.deepcopy(updated_data)}

    def reallocate_reservation_document(
        self,
        reservation_id,
        new_charger_id,
        new_slot_start,
        new_slot_end,
        updated_at,
        change_reason,
        allocation_validator,
    ):
        with self._lock:
            reservation_data = self._collections["reservations"].get(reservation_id)
            if reservation_data is None:
                return {"outcome": "not_found"}
            current_data = copy.deepcopy(reservation_data)
            if current_data.get("status") not in {"proposed", "confirmed"}:
                return {
                    "outcome": "invalid_state",
                    "detail": "Reservation is not in a reallocatable status.",
                }

            charger_data = self._collections["chargers"].get(new_charger_id)
            if charger_data is None:
                return {"outcome": "charger_not_found"}
            reservations = self.list_reservation_documents(new_charger_id)
            sessions = self.list_charging_session_documents(new_charger_id)
            outcome = allocation_validator(
                new_charger_id,
                copy.deepcopy(charger_data),
                reservations,
                sessions,
                current_data,
            )
            if outcome is not None:
                return {"outcome": outcome[0], "detail": outcome[1]}

            history = list(current_data.get("allocationHistory", []))
            history.append(
                {
                    "chargerId": current_data.get("chargerId"),
                    "slotStart": current_data.get("slotStart"),
                    "slotEnd": current_data.get("slotEnd"),
                    "changeReason": change_reason,
                    "changedAt": updated_at,
                }
            )
            updated_data = copy.deepcopy(current_data)
            updated_data.update(
                {
                    "chargerId": new_charger_id,
                    "slotStart": new_slot_start,
                    "slotEnd": new_slot_end,
                    "updatedAt": updated_at,
                    "allocationHistory": history,
                }
            )
            self._collections["reservations"][reservation_id] = updated_data
            return {"outcome": "updated", "data": copy.deepcopy(updated_data)}


@lru_cache(maxsize=4)
def _provider_for_path(fixture_path):
    return DemoDataProvider(fixture_path)


def get_demo_provider():
    fixture_path = os.getenv("GRIDFLOW_DEMO_DATA_FILE")
    if not fixture_path:
        fixture_path = Path(__file__).with_name("demo_data.json")
    return _provider_for_path(str(Path(fixture_path).expanduser().resolve()))
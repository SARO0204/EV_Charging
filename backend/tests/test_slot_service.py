import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.models import (
    Charger,
    ChargingSession,
    EV,
    EVChargerRecommendation,
    GridIntelligenceResult,
    GridStatus,
    PriorityLevel,
    RecommendationPrioritySummary,
    RecommendationScoreBreakdown,
    RecommendationWeights,
    RecommendedCharger,
    Reservation,
    ReservationCreateRequest,
)
from app.services.data_service import (
    InvalidDocumentIdError,
    MalformedFirestoreDocumentError,
    ReservationConflictError,
)
from app.services.firebase_service import FirebaseConfigurationError
from app.services.slot_service import (
    InvalidReservationStateError,
    NoChargingNeedError,
    NoConnectorCapacityError,
    NoPracticalSlotError,
    _find_slots,
    _serviceable_connector_capacity,
    _validate_reservation_capacity,
    calculate_charging_duration_minutes,
    calculate_energy_required_kwh,
    cancel_reservation,
    recommend_slot_for_ev,
)


NOW = datetime(2026, 9, 29, 11, 2, tzinfo=timezone.utc)


def make_ev(battery=40, required=70, max_power=50):
    vehicle = {"batteryCapacityKwh": 75}
    if max_power is not None:
        vehicle["maxChargeRateKw"] = max_power
    return EV.model_validate(
        {
            "batteryPercent": battery,
            "requiredChargePercent": required,
            "currentLocation": {"latitude": 13, "longitude": 80},
            "destination": {"latitude": 13.1, "longitude": 80.1},
            "vehicle": vehicle,
            "inputSource": "user_entered",
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    )


def make_charger(total=3, available=1, active=2, power=100):
    return Charger.model_validate(
        {
            "stationName": "Slot Test Station",
            "location": {"latitude": 13, "longitude": 80},
            "connectors": [
                {
                    "connectorType": "CCS",
                    "powerKw": power,
                    "totalCount": total,
                    "availableCount": available,
                }
            ],
            "queue": {"currentCount": 2, "observedAt": NOW},
            "grid": {
                "currentLoadKw": 50,
                "capacityKw": 100,
                "activeSessionCount": active,
                "expectedIncomingDemandKw": 5,
                "predictedPeakLoadKw": 70,
                "updatedAt": NOW,
            },
            "dataSource": "simulated",
            "updatedAt": NOW,
        }
    )


def make_grid(charger_id="charger-a"):
    return GridIntelligenceResult(
        charger_id=charger_id,
        current_load_kw=50,
        capacity_kw=100,
        current_utilization_percent=50,
        current_headroom_kw=50,
        expected_incoming_demand_kw=5,
        predicted_peak_load_kw=70,
        projected_peak_utilization_percent=70,
        projected_headroom_kw=30,
        grid_risk_score=70,
        grid_status=GridStatus.WATCH,
        calculated_at=NOW,
        explanation="In-memory grid context.",
    )


def make_recommendation(charger_id="charger-a"):
    return EVChargerRecommendation(
        ev_id="ev-1",
        priority=RecommendationPrioritySummary(
            score=50,
            level=PriorityLevel.HIGH,
            explanation="In-memory test priority.",
        ),
        recommendation=RecommendedCharger(
            charger_id=charger_id,
            station_name="Slot Test Station",
            score=80,
            distance_km=2,
            predicted_wait_minutes=5,
            grid_status=GridStatus.WATCH,
            grid_risk_score=70,
            available_charging_power_kw=100,
            suitable_charging_power_kw=50,
            explanation="In-memory recommendation test.",
        ),
        score_breakdown=RecommendationScoreBreakdown(
            distance_score=90,
            wait_score=80,
            grid_score=30,
            charging_power_score=100,
        ),
        weights=RecommendationWeights(
            distance=30,
            wait=32.5,
            grid=25,
            charging_power=12.5,
        ),
        weighting_explanation="In-memory weighting test.",
        alternatives=[],
        excluded_candidates=[],
        excluded_candidate_count=0,
    )


def make_reservation(start, end, status="confirmed", ev_id="other-ev"):
    return Reservation.model_validate(
        {
            "evId": ev_id,
            "chargerId": "charger-a",
            "slotStart": start,
            "slotEnd": end,
            "status": status,
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    )


class SlotCalculationTests(unittest.TestCase):
    def test_energy_requirement_and_duration(self):
        energy = calculate_energy_required_kwh(make_ev(40, 70))
        self.assertEqual(energy, 22.5)
        self.assertEqual(calculate_charging_duration_minutes(energy, 50), 27)

    def test_negative_charging_need_is_rejected(self):
        with self.assertRaises(NoChargingNeedError):
            calculate_energy_required_kwh(make_ev(80, 70))

    def test_missing_suitable_power_is_rejected(self):
        with self.assertRaises(NoConnectorCapacityError):
            calculate_charging_duration_minutes(10, 0)

    def test_multiple_connector_capacity_uses_available_plus_active(self):
        self.assertEqual(_serviceable_connector_capacity(make_charger(3, 1, 2)), 3)
        self.assertEqual(_serviceable_connector_capacity(make_charger(3, 1, 0)), 1)
        self.assertEqual(_serviceable_connector_capacity(make_charger(2, 2, 2)), 2)

    def test_existing_confirmed_reservations_respect_connector_capacity(self):
        charger = make_charger(3, 3, 0)
        start = NOW + timedelta(minutes=15)
        end = start + timedelta(minutes=30)
        existing = [
            make_reservation(start, end, ev_id="ev-2"),
            make_reservation(start, end, ev_id="ev-3"),
        ]
        self.assertIsNone(
            _validate_reservation_capacity(charger, existing, [], start, end, NOW)
        )
        existing.append(make_reservation(start, end, ev_id="ev-4"))
        self.assertIsNotNone(
            _validate_reservation_capacity(charger, existing, [], start, end, NOW)
        )

    def test_active_charging_session_occupies_connector_capacity(self):
        charger = make_charger(1, 0, 1)
        start = NOW + timedelta(minutes=15)
        end = start + timedelta(minutes=30)
        session = ChargingSession.model_validate(
            {
                "evId": "ev-active",
                "chargerId": "charger-a",
                "status": "charging",
                "arrivedAt": NOW - timedelta(minutes=10),
                "chargingStartedAt": NOW - timedelta(minutes=5),
                "dataSource": "simulated",
                "createdAt": NOW - timedelta(minutes=10),
                "updatedAt": NOW,
            }
        )
        self.assertIsNotNone(
            _validate_reservation_capacity(
                charger, [], [session], start, end, NOW
            )
        )

    def test_proposed_reservations_are_also_capacity_conflicts(self):
        charger = make_charger(1, 1, 0)
        start = NOW + timedelta(minutes=15)
        end = start + timedelta(minutes=30)
        proposed = [make_reservation(start, end, status="proposed")]
        self.assertIsNotNone(
            _validate_reservation_capacity(charger, proposed, [], start, end, NOW)
        )

    def test_higher_priority_tolerates_less_wait(self):
        charger = make_charger(1, 1, 0)
        blocked_start = datetime(2026, 9, 29, 11, 15, tzinfo=timezone.utc)
        reservations = [
            make_reservation(
                blocked_start,
                datetime(2026, 9, 29, 12, 15, tzinfo=timezone.utc),
            )
        ]
        low_priority_slots = _find_slots(
            charger, 0, 30, 0, make_grid(), reservations, [], NOW
        )
        self.assertEqual(
            low_priority_slots[0].start,
            datetime(2026, 9, 29, 12, 15, tzinfo=timezone.utc),
        )
        with self.assertRaises(NoPracticalSlotError):
            _find_slots(charger, 0, 30, 100, make_grid(), reservations, [], NOW)

    def test_phase_10_charger_is_used_and_get_does_not_write_reservation(self):
        charger = make_charger(1, 1, 0)
        with patch(
            "app.services.slot_service.recommend_charger_for_ev",
            return_value=make_recommendation("phase-10-charger"),
        ), patch(
            "app.services.slot_service.get_charger_by_id",
            return_value=("phase-10-charger", charger),
        ) as get_charger, patch(
            "app.services.slot_service.predict_queue_for_charger",
            return_value=type(
                "Queue", (), {"predicted_wait_minutes": 5}
            )(),
        ), patch(
            "app.services.slot_service.calculate_grid_intelligence",
            return_value=make_grid("phase-10-charger"),
        ), patch(
            "app.services.slot_service.get_reservations_for_charger", return_value=[]
        ), patch(
            "app.services.slot_service.get_charging_sessions_for_charger", return_value=[]
        ), patch(
            "app.services.slot_service.create_reservation_record"
        ) as create_record:
            result = recommend_slot_for_ev("ev-1", make_ev(), NOW)
        self.assertEqual(result.charger_id, "phase-10-charger")
        get_charger.assert_called_once_with("phase-10-charger")
        create_record.assert_not_called()

    def test_slot_request_requires_ordered_aware_times(self):
        with self.assertRaises(ValidationError):
            ReservationCreateRequest.model_validate(
                {
                    "evId": "ev-1",
                    "chargerId": "charger-a",
                    "slotStart": "2026-09-29T12:00:00Z",
                    "slotEnd": "2026-09-29T11:00:00Z",
                }
            )


class ReservationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_openapi_contains_the_phase_13_emergency_route(self):
        paths = set(app.openapi()["paths"])
        self.assertEqual(
            paths,
            {
                "/api/ev/{ev_id}",
                "/api/ev/{ev_id}/priority",
                "/api/ev/{ev_id}/recommendation",
                "/api/ev/{ev_id}/slot-recommendation",
                "/api/ev/{ev_id}/emergency",
                "/api/chargers",
                "/api/chargers/{charger_id}",
                "/api/chargers/{charger_id}/grid",
                "/api/queue/{charger_id}/prediction",
                "/api/reservations",
                "/api/reservations/{reservation_id}",
                "/api/reservations/{reservation_id}/cancel",
                "/api/reservations/{reservation_id}/reallocation-check",
                "/api/reservations/{reservation_id}/reallocate",
                "/api/simulation/run",
                "/api/dashboard/overview",
            },
        )

    def test_missing_firebase_does_not_fake_reservation_success(self):
        payload = {
            "evId": "ev-1",
            "chargerId": "charger-a",
            "slotStart": "2026-09-29T12:00:00Z",
            "slotEnd": "2026-09-29T12:30:00Z",
        }
        response = self.client.post("/api/reservations", json=payload)
        self.assertEqual(response.status_code, 503)

    def test_missing_firebase_blocks_reservation_read_and_cancel(self):
        self.assertEqual(
            self.client.get("/api/reservations/res-1").status_code,
            503,
        )
        self.assertEqual(
            self.client.patch("/api/reservations/res-1/cancel").status_code,
            503,
        )

    def test_missing_firebase_blocks_slot_recommendation_without_fake_slot(self):
        response = self.client.get("/api/ev/ev-1/slot-recommendation")
        self.assertEqual(response.status_code, 503)

    def test_get_slot_recommendation_does_not_create_reservation(self):
        with patch(
            "app.api.ev.get_ev_by_id", return_value=("ev-1", make_ev())
        ), patch(
            "app.api.ev.recommend_slot_for_ev",
            side_effect=NoPracticalSlotError("No slot in test."),
        ), patch("app.services.slot_service.create_reservation_record") as create_record:
            response = self.client.get("/api/ev/ev-1/slot-recommendation")
        self.assertEqual(response.status_code, 422)
        create_record.assert_not_called()

    def test_missing_reservation_returns_404(self):
        with patch("app.api.reservations.get_reservation", return_value=None):
            response = self.client.get("/api/reservations/missing")
        self.assertEqual(response.status_code, 404)

    def test_invalid_reservation_id_returns_422(self):
        response = self.client.get("/api/reservations/%20")
        self.assertEqual(response.status_code, 422)

    def test_cancelled_state_is_not_cancelled_twice(self):
        with patch(
            "app.api.reservations.cancel_reservation",
            side_effect=InvalidReservationStateError(
                "Reservation in 'cancelled' status cannot be cancelled."
            ),
        ):
            response = self.client.patch("/api/reservations/res-1/cancel")
        self.assertEqual(response.status_code, 422)

    def test_malformed_reservation_data_keeps_existing_error_behavior(self):
        with patch(
            "app.api.reservations.get_reservation",
            side_effect=MalformedFirestoreDocumentError("malformed reservation"),
        ):
            response = self.client.get("/api/reservations/res-1")
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
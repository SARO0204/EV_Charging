import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.models import Charger, EV, GridStatus, Reservation
from app.services.reallocation_service import (
    MINIMUM_SCORE_IMPROVEMENT,
    check_reallocation,
    reallocate_reservation,
)

NOW = datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)


def make_ev():
    return EV.model_validate(
        {
            "batteryPercent": 30,
            "requiredChargePercent": 80,
            "currentLocation": {"latitude": 13.0, "longitude": 80.0},
            "destination": {"latitude": 13.1, "longitude": 80.1},
            "vehicle": {"batteryCapacityKwh": 75, "maxChargeRateKw": 50},
            "inputSource": "user_entered",
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    )


def make_charger(charger_id, *, station_name="Station A", power=100, available=1):
    return charger_id, Charger.model_validate(
        {
            "stationName": station_name,
            "location": {"latitude": 13.0, "longitude": 80.0},
            "connectors": [
                {
                    "connectorType": "CCS",
                    "powerKw": power,
                    "totalCount": 1,
                    "availableCount": available,
                }
            ],
            "queue": {"currentCount": 1, "observedAt": NOW},
            "grid": {
                "currentLoadKw": 30,
                "capacityKw": 100,
                "activeSessionCount": 0,
                "expectedIncomingDemandKw": 10,
                "predictedPeakLoadKw": 60,
                "updatedAt": NOW,
            },
            "dataSource": "simulated",
            "updatedAt": NOW,
        }
    )


def make_reservation(charger_id="charger-a", status="confirmed"):
    return Reservation.model_validate(
        {
            "evId": "ev-1",
            "chargerId": charger_id,
            "slotStart": NOW + timedelta(minutes=30),
            "slotEnd": NOW + timedelta(minutes=60),
            "status": status,
            "createdAt": NOW,
            "updatedAt": NOW,
            "allocationHistory": [],
        }
    )


class ReallocationServiceTests(unittest.TestCase):
    def test_reallocation_check_is_read_only_when_current_charger_is_still_suitable(self):
        with patch("app.services.reallocation_service.get_reservation_by_id", return_value=("res-1", make_reservation())), patch(
            "app.services.reallocation_service.get_ev_by_id", return_value=("ev-1", make_ev())
        ), patch("app.services.reallocation_service.get_charger_by_id", return_value=make_charger("charger-a")), patch(
            "app.services.reallocation_service.predict_queue_for_charger", return_value=type("Queue", (), {"predicted_wait_minutes": 12})()
        ), patch("app.services.reallocation_service.calculate_grid_intelligence", return_value=type("Grid", (), {"grid_risk_score": 30, "grid_status": GridStatus.NORMAL})()), patch(
            "app.services.reallocation_service.get_available_chargers", return_value=[make_charger("charger-a")[0:2], make_charger("charger-b")[0:2]]
        ), patch("app.services.reallocation_service.get_reservations_for_charger", return_value=[]), patch(
            "app.services.reallocation_service.get_charging_sessions_for_charger", return_value=[]
        ), patch("app.services.reallocation_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 50, "priority_level": "HIGH"})()):
            assessment = check_reallocation("res-1", NOW)
        self.assertFalse(assessment.reallocation.recommended)
        self.assertEqual(assessment.reallocation.reason, "No reallocation recommended because the current charger remains suitable.")

    def test_reallocation_is_recommended_when_alternative_score_exceeds_threshold(self):
        current = make_reservation()
        with patch("app.services.reallocation_service.get_reservation_by_id", return_value=("res-1", current)), patch(
            "app.services.reallocation_service.get_ev_by_id", return_value=("ev-1", make_ev())
        ), patch("app.services.reallocation_service.get_charger_by_id", return_value=make_charger("charger-a")), patch(
            "app.services.reallocation_service.predict_queue_for_charger", side_effect=[type("Queue", (), {"predicted_wait_minutes": 35})(), type("Queue", (), {"predicted_wait_minutes": 10})()]
        ), patch("app.services.reallocation_service.calculate_grid_intelligence", side_effect=[type("Grid", (), {"grid_risk_score": 80, "grid_status": GridStatus.WATCH})(), type("Grid", (), {"grid_risk_score": 20, "grid_status": GridStatus.NORMAL})()]), patch(
            "app.services.reallocation_service.get_available_chargers", return_value=[make_charger("charger-a")[0:2], make_charger("charger-b")[0:2]]
        ), patch("app.services.reallocation_service.get_reservations_for_charger", return_value=[]), patch(
            "app.services.reallocation_service.get_charging_sessions_for_charger", return_value=[]
        ), patch("app.services.reallocation_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 50, "priority_level": "HIGH"})()):
            assessment = check_reallocation("res-1", NOW)
        self.assertTrue(assessment.reallocation.recommended)
        self.assertGreaterEqual(assessment.reallocation.score_improvement, MINIMUM_SCORE_IMPROVEMENT)

    def test_reallocate_updates_charger_slot_and_history(self):
        reservation = make_reservation("charger-a")
        with patch("app.services.reallocation_service.get_reservation_by_id", return_value=("res-1", reservation)), patch(
            "app.services.reallocation_service.get_ev_by_id", return_value=("ev-1", make_ev())
        ), patch("app.services.reallocation_service.get_charger_by_id", return_value=make_charger("charger-a")), patch(
            "app.services.reallocation_service.predict_queue_for_charger", side_effect=[type("Queue", (), {"predicted_wait_minutes": 40})(), type("Queue", (), {"predicted_wait_minutes": 8})()]
        ), patch("app.services.reallocation_service.calculate_grid_intelligence", side_effect=[type("Grid", (), {"grid_risk_score": 75, "grid_status": GridStatus.WATCH})(), type("Grid", (), {"grid_risk_score": 20, "grid_status": GridStatus.NORMAL})()]), patch(
            "app.services.reallocation_service.get_available_chargers", return_value=[make_charger("charger-a")[0:2], make_charger("charger-b")[0:2]]
        ), patch("app.services.reallocation_service.get_reservations_for_charger", return_value=[]), patch(
            "app.services.reallocation_service.get_charging_sessions_for_charger", return_value=[]
        ), patch("app.services.reallocation_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 50, "priority_level": "HIGH"})()), patch(
            "app.services.reallocation_service.reallocate_reservation_document",
            return_value=("res-1", Reservation.model_validate({
                "evId": "ev-1",
                "chargerId": "charger-b",
                "slotStart": NOW + timedelta(minutes=45),
                "slotEnd": NOW + timedelta(minutes=75),
                "status": "confirmed",
                "createdAt": NOW,
                "updatedAt": NOW + timedelta(minutes=1),
                "allocationHistory": [{
                    "chargerId": "charger-a",
                    "slotStart": NOW + timedelta(minutes=30),
                    "slotEnd": NOW + timedelta(minutes=60),
                    "changeReason": "Reallocation recommended because the alternative charger provides a meaningful score improvement.",
                    "changedAt": NOW + timedelta(minutes=1),
                }],
            }))
        ):
            result = reallocate_reservation("res-1", NOW)
        self.assertEqual(result.charger_id, "charger-b")
        self.assertEqual(result.allocation_history[0].charger_id, "charger-a")


class ReallocationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_reallocation_routes_are_exposed(self):
        paths = set(app.openapi()["paths"])
        self.assertIn("/api/reservations/{reservation_id}/reallocation-check", paths)
        self.assertIn("/api/reservations/{reservation_id}/reallocate", paths)


if __name__ == "__main__":
    unittest.main()

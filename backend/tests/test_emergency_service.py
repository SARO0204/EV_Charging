import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.models import Charger, EV, GridStatus, PriorityLevel
from app.services.emergency_service import calculate_emergency_recommendation

NOW = datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)


def make_ev(battery_percent=15, required_charge_percent=80, max_charge_rate_kw=50):
    return EV.model_validate(
        {
            "batteryPercent": battery_percent,
            "requiredChargePercent": required_charge_percent,
            "currentLocation": {"latitude": 13.0, "longitude": 80.0},
            "destination": {"latitude": 13.1, "longitude": 80.1},
            "vehicle": {
                "batteryCapacityKwh": 75,
                "maxChargeRateKw": max_charge_rate_kw,
            },
            "inputSource": "user_entered",
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    )


def make_charger(charger_id, *, station_name="Station A", power=100, available=1, grid_status=GridStatus.NORMAL, risk=20):
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


class EmergencyServiceTests(unittest.TestCase):
    def test_critical_ev_activates_emergency_mode(self):
        with patch("app.services.emergency_service.get_ev_by_id", return_value=("ev-1", make_ev(15))), patch(
            "app.services.emergency_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 86, "priority_level": PriorityLevel.CRITICAL})()
        ), patch("app.services.emergency_service.get_available_chargers", return_value=[make_charger("charger-a"), make_charger("charger-b")]), patch(
            "app.services.emergency_service.predict_queue_for_charger", side_effect=[type("Queue", (), {"predicted_wait_minutes": 12})(), type("Queue", (), {"predicted_wait_minutes": 18})()]
        ), patch("app.services.emergency_service.calculate_grid_intelligence", side_effect=[
            type("Grid", (), {"grid_risk_score": 20, "grid_status": GridStatus.NORMAL})(),
            type("Grid", (), {"grid_risk_score": 60, "grid_status": GridStatus.HIGH})(),
        ]):
            result = calculate_emergency_recommendation("ev-1", make_ev(15), NOW)

        self.assertTrue(result.emergency.active)
        self.assertEqual(result.emergency.reason, "Emergency mode is active because the EV has CRITICAL charging priority.")
        self.assertEqual(result.recommendation.charger_id, "charger-a")
        self.assertFalse(result.reachability.verified)

    def test_high_priority_ev_does_not_activate_emergency_mode(self):
        with patch("app.services.emergency_service.get_ev_by_id", return_value=("ev-1", make_ev(25))), patch(
            "app.services.emergency_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 60, "priority_level": PriorityLevel.HIGH})()
        ):
            result = calculate_emergency_recommendation("ev-1", make_ev(25), NOW)

        self.assertFalse(result.emergency.active)
        self.assertEqual(result.emergency.reason, "Emergency mode is not required for this EV.")
        self.assertIsNone(result.recommendation)

    def test_emergency_weights_sum_to_100(self):
        with patch("app.services.emergency_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 60, "priority_level": PriorityLevel.HIGH})()):
            result = calculate_emergency_recommendation("ev-1", make_ev(10), NOW)
        self.assertAlmostEqual(result.weights.wait + result.weights.charging_power + result.weights.grid + result.weights.distance, 100.0)

    def test_emergency_score_is_in_range_and_wait_is_preferred(self):
        with patch("app.services.emergency_service.get_ev_by_id", return_value=("ev-1", make_ev(12))), patch(
            "app.services.emergency_service.calculate_ev_priority", return_value=type("Priority", (), {"priority_score": 90, "priority_level": PriorityLevel.CRITICAL})()
        ), patch("app.services.emergency_service.get_available_chargers", return_value=[make_charger("charger-a"), make_charger("charger-b")]), patch(
            "app.services.emergency_service.predict_queue_for_charger", side_effect=[type("Queue", (), {"predicted_wait_minutes": 30})(), type("Queue", (), {"predicted_wait_minutes": 10})()]
        ), patch("app.services.emergency_service.calculate_grid_intelligence", side_effect=[
            type("Grid", (), {"grid_risk_score": 20, "grid_status": GridStatus.NORMAL})(),
            type("Grid", (), {"grid_risk_score": 20, "grid_status": GridStatus.NORMAL})(),
        ]):
            result = calculate_emergency_recommendation("ev-1", make_ev(12), NOW)

        self.assertGreaterEqual(result.recommendation.score, 0)
        self.assertLessEqual(result.recommendation.score, 100)
        self.assertEqual(result.recommendation.charger_id, "charger-b")

    def test_emergency_route_missing_ev_returns_404(self):
        client = TestClient(app)
        with patch("app.api.ev.get_ev_by_id", return_value=None):
            response = client.get("/api/ev/missing/emergency")
            self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.services.firebase_service import FirebaseConfigurationError


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_dashboard_route_exists_and_is_unique(self):
        paths = app.openapi()["paths"]
        self.assertIn("/api/dashboard/overview", paths)
        operation_ids = []
        for methods in paths.values():
            for method in methods.values():
                operation_ids.append(method.get("operationId"))
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

    def test_dashboard_route_returns_payload(self):
        payload = {
            "overview": {"connected_ev_count": 2, "charging_ev_count": 1},
            "chargers": [{"id": "charger-a", "station_name": "Station A"}],
            "evs": [{"id": "ev-1", "battery_percent": 35.0}],
            "grid": [{"id": "charger-a", "grid_status": "NORMAL"}],
            "simulation": {"available": False, "message": "No simulation run available."},
        }
        with patch("app.api.dashboard.build_dashboard_overview", return_value=payload):
            response = self.client.get("/api/dashboard/overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["overview"]["connected_ev_count"], 2)

    def test_dashboard_route_surfaces_firebase_error(self):
        with patch(
            "app.api.dashboard.build_dashboard_overview",
            side_effect=FirebaseConfigurationError("Firebase is not configured."),
        ):
            response = self.client.get("/api/dashboard/overview")
        self.assertEqual(response.status_code, 503)
        self.assertIn("Firebase is not configured", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()

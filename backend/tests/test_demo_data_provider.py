import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app


class DemoDataProviderApiTests(unittest.TestCase):
    def test_demo_provider_serves_existing_intelligence_without_firebase(self):
        demo_environment = {
            "GRIDFLOW_DATA_PROVIDER": "demo",
            "FIREBASE_PROJECT_ID": "",
            "GOOGLE_APPLICATION_CREDENTIALS": "",
        }
        with patch.dict(os.environ, demo_environment, clear=False):
            client = TestClient(app)
            dashboard = client.get("/api/dashboard/overview")
            queue = client.get("/api/queue/charger-marina/prediction")
            recommendation = client.get("/api/ev/ev-critical/recommendation")
            emergency = client.get("/api/ev/ev-critical/emergency")
            slot_start = datetime.now(timezone.utc) + timedelta(hours=2)
            reservation = client.post(
                "/api/reservations",
                json={
                    "evId": "ev-critical",
                    "chargerId": "charger-airport",
                    "slotStart": slot_start.isoformat(),
                    "slotEnd": (slot_start + timedelta(minutes=45)).isoformat(),
                },
            )
            cancellation = (
                client.patch(f"/api/reservations/{reservation.json()['id']}/cancel")
                if reservation.status_code == 201
                else None
            )

        self.assertEqual(dashboard.status_code, 200)
        dashboard_data = dashboard.json()
        self.assertEqual(dashboard_data["overview"]["connected_ev_count"], 3)
        self.assertTrue(dashboard_data["simulation"]["available"])
        self.assertTrue(
            any(
                row["projected_peak_grid_utilization_percent"] > 100
                for row in dashboard_data["chargers"]
            )
        )
        self.assertEqual(queue.status_code, 200)
        self.assertGreater(queue.json()["predictedWaitMinutes"], 0)
        self.assertEqual(recommendation.status_code, 200)
        self.assertEqual(emergency.status_code, 200)
        self.assertIsNotNone(reservation)
        self.assertEqual(reservation.status_code, 201)
        self.assertEqual(cancellation.status_code, 200)
        self.assertEqual(cancellation.json()["status"], "cancelled")


if __name__ == "__main__":
    unittest.main()
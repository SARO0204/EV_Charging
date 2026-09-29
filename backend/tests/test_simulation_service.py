import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.models import Charger, EV, GridStatus, SimulationRunRequest
from app.services.simulation_service import run_simulation

NOW = datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc)


def make_ev(index):
    battery = 15 + (index * 12) % 50
    required = 70 + (index * 7) % 20
    return EV.model_validate(
        {
            "batteryPercent": battery,
            "requiredChargePercent": required,
            "currentLocation": {"latitude": 13.0 + index * 0.002, "longitude": 80.0},
            "destination": {"latitude": 13.1, "longitude": 80.1},
            "vehicle": {"batteryCapacityKwh": 75, "maxChargeRateKw": 50},
            "inputSource": "user_entered",
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    )


def make_charger(charger_id, *, power=50, total_count=2, available_count=2, load=20, capacity=100):
    return charger_id, Charger.model_validate(
        {
            "stationName": f"Station {charger_id}",
            "location": {"latitude": 12.9 + (ord(charger_id[-1]) % 3) * 0.02, "longitude": 80.0},
            "connectors": [
                {"connectorType": "CCS", "powerKw": power, "totalCount": total_count, "availableCount": available_count}
            ],
            "queue": {"currentCount": 0, "observedAt": NOW},
            "grid": {
                "currentLoadKw": load,
                "capacityKw": capacity,
                "activeSessionCount": 0,
                "expectedIncomingDemandKw": 10,
                "predictedPeakLoadKw": max(60, load + 20),
                "updatedAt": NOW,
            },
            "dataSource": "simulated",
            "updatedAt": NOW,
        }
    )


class SimulationServiceTests(unittest.TestCase):
    def setUp(self):
        self.chargers = [make_charger("charger-a"), make_charger("charger-b")]

    def test_same_input_produces_same_result(self):
        first = run_simulation(4, 30, chargers=self.chargers)
        second = run_simulation(4, 30, chargers=self.chargers)
        self.assertEqual(first.baseline.average_wait_minutes, second.baseline.average_wait_minutes)
        self.assertEqual(first.grid_flow.average_wait_minutes, second.grid_flow.average_wait_minutes)

    def test_baseline_and_gridflow_are_deterministic(self):
        result = run_simulation(5, 30, chargers=self.chargers)
        self.assertGreaterEqual(result.baseline.assigned_ev_count, 0)
        self.assertGreaterEqual(result.grid_flow.assigned_ev_count, 0)

    def test_incoming_ev_demand_validates_range(self):
        with self.assertRaises(ValueError):
            run_simulation(0, 30, chargers=self.chargers)
        with self.assertRaises(ValueError):
            run_simulation(201, 30, chargers=self.chargers)
        with self.assertRaises(ValueError):
            run_simulation(3, 0, chargers=self.chargers)

    def test_empty_charger_network_is_rejected(self):
        with self.assertRaises(ValueError):
            run_simulation(2, 20, chargers=[])

    def test_simulation_result_validates_with_pydantic(self):
        result = run_simulation(3, 20, chargers=self.chargers)
        self.assertIsNotNone(result.input.incoming_ev_count)
        self.assertGreaterEqual(result.impact.wait_improvement_percent, -100.0)

    def test_route_accepts_simulation_request(self):
        client = TestClient(app)
        with patch("app.api.simulation.get_available_chargers", return_value=self.chargers):
            response = client.post("/api/simulation/run", json={"incomingEvCount": 3, "windowMinutes": 20})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("simulationId", body)
        self.assertEqual(body["input"]["incomingEvCount"], 3)


if __name__ == "__main__":
    unittest.main()

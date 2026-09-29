import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.main import app
from app.models import (
    Charger,
    EV,
    EVPriorityResult,
    GridIntelligenceResult,
    GridStatus,
    PriorityLevel,
    QueuePrediction,
)
from app.services.data_service import MalformedFirestoreDocumentError
from app.services.firebase_service import FirebaseConfigurationError
from app.services.grid_intelligence_service import InvalidGridDataError
from app.services.priority_service import calculate_ev_priority
from app.services.queue_prediction_service import InsufficientQueuePredictionDataError
from app.services.recommendation_service import (
    CandidateEvidence,
    NoRecommendationCandidatesError,
    recommend_charger_for_ev,
    recommendation_weights,
    score_candidates,
)


NOW = datetime(2026, 9, 29, 18, tzinfo=timezone.utc)


def make_ev(priority_battery=50, required_charge=80, max_charge_rate=None):
    vehicle = {"batteryCapacityKwh": 75}
    if max_charge_rate is not None:
        vehicle["maxChargeRateKw"] = max_charge_rate
    return EV.model_validate(
        {
            "batteryPercent": priority_battery,
            "requiredChargePercent": required_charge,
            "currentLocation": {"latitude": 13.08, "longitude": 80.27},
            "destination": {"latitude": 13.06, "longitude": 80.23},
            "vehicle": vehicle,
            "inputSource": "user_entered",
            "createdAt": NOW,
            "updatedAt": NOW,
        }
    )


def make_charger(
    charger_id,
    *,
    latitude=13.08,
    longitude=80.27,
    power=150,
    available=1,
):
    charger = Charger.model_validate(
        {
            "stationName": f"Station {charger_id}",
            "location": {"latitude": latitude, "longitude": longitude},
            "connectors": [
                {
                    "connectorType": "CCS",
                    "powerKw": power,
                    "totalCount": 1,
                    "availableCount": available,
                }
            ],
            "queue": {"currentCount": 2, "observedAt": NOW},
            "grid": {
                "currentLoadKw": 40,
                "capacityKw": 100,
                "activeSessionCount": 0,
                "expectedIncomingDemandKw": 5,
                "predictedPeakLoadKw": 60,
                "updatedAt": NOW,
            },
            "dataSource": "simulated",
            "updatedAt": NOW,
        }
    )
    return charger_id, charger


def make_evidence(
    charger_id,
    *,
    distance=10,
    wait=10,
    risk=20,
    power=100,
    suitable_power=None,
):
    return CandidateEvidence(
        charger_id=charger_id,
        station_name=f"Station {charger_id}",
        distance_km=distance,
        predicted_wait_minutes=wait,
        grid_status=GridStatus.NORMAL.value,
        grid_risk_score=risk,
        available_charging_power_kw=power,
        suitable_charging_power_kw=suitable_power or power,
    )


def make_priority(score):
    return EVPriorityResult(
        ev_id="ev-1",
        priority_score=score,
        priority_level=(
            PriorityLevel.CRITICAL
            if score >= 80
            else PriorityLevel.HIGH
            if score >= 50
            else PriorityLevel.MEDIUM
            if score >= 25
            else PriorityLevel.LOW
        ),
        factors={},
        explanation="In-memory test priority.",
        calculated_at=NOW,
    )


def make_queue_prediction(charger_id, wait):
    return QueuePrediction(
        charger_id=charger_id,
        current_queue_count=2,
        current_queue_observed_at=NOW,
        predicted_queue_count=3,
        predicted_wait_minutes=wait,
        prediction_timestamp=NOW,
        forecast_at=NOW,
        forecast_horizon_minutes=15,
        prediction_method="observed_session_baseline",
        historical_session_count=1,
        historical_data_sources=["simulated"],
        explanation="In-memory test queue prediction.",
    )


def make_grid(charger_id, risk):
    return GridIntelligenceResult(
        charger_id=charger_id,
        current_load_kw=40,
        capacity_kw=100,
        current_utilization_percent=40,
        current_headroom_kw=60,
        expected_incoming_demand_kw=5,
        predicted_peak_load_kw=risk,
        projected_peak_utilization_percent=risk,
        projected_headroom_kw=100 - risk,
        grid_risk_score=risk,
        grid_status=GridStatus.NORMAL if risk < 70 else GridStatus.WATCH,
        calculated_at=NOW,
        explanation="In-memory test grid assessment.",
    )


class RecommendationScoringTests(unittest.TestCase):
    def get_score(self, evidence):
        return score_candidates(50, evidence)[0]

    def test_lower_predicted_wait_improves_score(self):
        ranked = self.get_score(
            [make_evidence("long", wait=20), make_evidence("short", wait=5)]
        )
        self.assertEqual(ranked[0][0].charger_id, "short")

    def test_lower_grid_risk_improves_score(self):
        ranked = self.get_score(
            [make_evidence("high-risk", risk=80), make_evidence("low-risk", risk=20)]
        )
        self.assertEqual(ranked[0][0].charger_id, "low-risk")

    def test_higher_suitable_power_improves_score(self):
        ranked = self.get_score(
            [
                make_evidence("lower-power", power=100, suitable_power=50),
                make_evidence("higher-power", power=150, suitable_power=100),
            ]
        )
        self.assertEqual(ranked[0][0].charger_id, "higher-power")

    def test_lower_distance_improves_score(self):
        ranked = self.get_score(
            [make_evidence("far", distance=20), make_evidence("near", distance=5)]
        )
        self.assertEqual(ranked[0][0].charger_id, "near")

    def test_priority_increases_wait_and_grid_weights(self):
        low = recommendation_weights(10)
        high = recommendation_weights(90)
        self.assertGreater(high.wait, low.wait)
        self.assertGreater(high.grid, low.grid)
        self.assertLess(high.distance, low.distance)
        self.assertLess(high.charging_power, low.charging_power)

    def test_priority_can_change_winner_when_distance_conflicts_with_wait_and_grid(self):
        candidates = [
            make_evidence("near-stressed", distance=0, wait=60, risk=50),
            make_evidence("far-calm", distance=50, wait=0, risk=0),
        ]
        low_priority, _ = score_candidates(0, candidates)
        critical_priority, _ = score_candidates(100, candidates)
        self.assertEqual(low_priority[0][0].charger_id, "near-stressed")
        self.assertEqual(critical_priority[0][0].charger_id, "far-calm")

    def test_weights_total_100_across_priority_range(self):
        for score in range(0, 101):
            weights = recommendation_weights(score)
            self.assertAlmostEqual(
                weights.distance + weights.wait + weights.grid + weights.charging_power,
                100,
            )

    def test_final_scores_are_bounded(self):
        for priority in (0, 25, 50, 80, 100):
            ranked, _ = score_candidates(
                priority,
                [make_evidence("a", distance=0, wait=0, risk=0, power=500),
                 make_evidence("b", distance=100, wait=90, risk=100, power=1)],
            )
            self.assertTrue(all(0 <= result[2] <= 100 for result in ranked))

    def test_ties_are_deterministic_and_alternatives_can_be_sorted(self):
        ranked = self.get_score(
            [make_evidence("b"), make_evidence("a"), make_evidence("c")]
        )
        self.assertEqual([candidate.charger_id for candidate, _, _ in ranked], ["a", "b", "c"])
        self.assertEqual(ranked, self.get_score([make_evidence("c"), make_evidence("b"), make_evidence("a")]))


class RecommendationOrchestrationTests(unittest.TestCase):
    def setup_services(self, charger_records, wait_by_id=None, grid_failure_ids=()):
        wait_by_id = wait_by_id or {}
        def queue_side_effect(charger_id, prediction_timestamp):
            return make_queue_prediction(charger_id, wait_by_id.get(charger_id, 10))
        def grid_side_effect(charger_id, charger, calculated_at):
            if charger_id in grid_failure_ids:
                raise InvalidGridDataError("invalid projected grid")
            return make_grid(charger_id, 20)
        return (
            patch("app.services.recommendation_service.get_available_chargers", return_value=charger_records),
            patch("app.services.recommendation_service.predict_queue_for_charger", side_effect=queue_side_effect),
            patch("app.services.recommendation_service.calculate_grid_intelligence", side_effect=grid_side_effect),
            patch("app.services.recommendation_service.calculate_ev_priority", return_value=make_priority(50)),
        )

    def test_recommendation_is_highest_score_and_alternatives_sorted(self):
        chargers = [make_charger("a"), make_charger("b", latitude=13.2), make_charger("c", latitude=13.3)]
        patches = self.setup_services(chargers, {"a": 20, "b": 5, "c": 10})
        with patches[0], patches[1], patches[2], patches[3]:
            response = recommend_charger_for_ev("ev-1", make_ev(), NOW)
        self.assertEqual(response.recommendation.charger_id, "b")
        alternative_scores = [item.score for item in response.alternatives]
        self.assertEqual(alternative_scores, sorted(alternative_scores, reverse=True))
        self.assertEqual(response.alternatives[0].charger_id, "c")

    def test_charger_without_available_connector_is_excluded(self):
        chargers = [make_charger("unavailable", available=0), make_charger("available")]
        patches = self.setup_services(chargers)
        with patches[0], patches[1], patches[2], patches[3]:
            response = recommend_charger_for_ev("ev-1", make_ev(), NOW)
        self.assertEqual(response.recommendation.charger_id, "available")
        self.assertEqual(response.excluded_candidate_count, 1)
        self.assertIn("No available connector", response.excluded_candidates[0].reason)

    def test_missing_queue_prediction_is_excluded_without_fake_wait(self):
        patches = list(self.setup_services([make_charger("a")]))
        patches[1] = patch("app.services.recommendation_service.predict_queue_for_charger", side_effect=InsufficientQueuePredictionDataError("not enough observed sessions"))
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaises(NoRecommendationCandidatesError):
                recommend_charger_for_ev("ev-1", make_ev(), NOW)

    def test_missing_grid_intelligence_is_excluded_without_fake_grid(self):
        patches = self.setup_services([make_charger("a")], grid_failure_ids={"a"})
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaises(NoRecommendationCandidatesError):
                recommend_charger_for_ev("ev-1", make_ev(), NOW)

    def test_no_serviceable_candidates_is_explicit(self):
        patches = self.setup_services([])
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaises(NoRecommendationCandidatesError):
                recommend_charger_for_ev("ev-1", make_ev(), NOW)

    def test_unexpected_data_errors_are_not_swallowed(self):
        patches = list(self.setup_services([make_charger("a")]))
        patches[0] = patch(
            "app.services.recommendation_service.get_available_chargers",
            side_effect=MalformedFirestoreDocumentError("malformed charger"),
        )
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaises(MalformedFirestoreDocumentError):
                recommend_charger_for_ev("ev-1", make_ev(), NOW)


class RecommendationApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_openapi_publishes_typed_recommendation_response(self):
        operation = app.openapi()["paths"]["/api/ev/{ev_id}/recommendation"]["get"]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(
            response_schema["$ref"],
            "#/components/schemas/EVChargerRecommendation",
        )

    def test_missing_ev_returns_404(self):
        with patch("app.api.ev.get_ev_by_id", return_value=None):
            response = self.client.get("/api/ev/missing/recommendation")
        self.assertEqual(response.status_code, 404)

    def test_invalid_ev_id_returns_422(self):
        response = self.client.get("/api/ev/%20/recommendation")
        self.assertEqual(response.status_code, 422)

    def test_firebase_configuration_failure_returns_503(self):
        with patch(
            "app.api.ev.get_ev_by_id",
            side_effect=FirebaseConfigurationError("Firebase is not configured."),
        ):
            response = self.client.get("/api/ev/ev-1/recommendation")
        self.assertEqual(response.status_code, 503)

    def test_malformed_ev_document_uses_existing_500_behavior(self):
        with patch(
            "app.api.ev.get_ev_by_id",
            side_effect=MalformedFirestoreDocumentError("malformed EV"),
        ):
            response = self.client.get("/api/ev/ev-1/recommendation")
        self.assertEqual(response.status_code, 500)

    def test_unavailable_candidates_return_422(self):
        with patch("app.api.ev.get_ev_by_id", return_value=("ev-1", make_ev())), patch(
            "app.api.ev.recommend_charger_for_ev",
            side_effect=NoRecommendationCandidatesError("No candidate evidence."),
        ):
            response = self.client.get("/api/ev/ev-1/recommendation")
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
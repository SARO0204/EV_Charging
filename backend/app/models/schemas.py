from enum import Enum
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from pydantic.alias_generators import to_camel


class FirestoreModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class EVInputSource(str, Enum):
    USER_ENTERED = "user_entered"
    SIMULATED = "simulated"


class DataSource(str, Enum):
    SIMULATED = "simulated"
    OPERATOR_ENTERED = "operator_entered"
    MEASURED = "measured"


class ReservationStatus(str, Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    EXPIRED = "expired"


class ChargingSessionStatus(str, Enum):
    WAITING = "waiting"
    CHARGING = "charging"
    COMPLETED = "completed"
    LEFT_QUEUE = "left_queue"
    CANCELLED = "cancelled"


class UrgencyLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"


class GeoPoint(FirestoreModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class VehicleDetails(FirestoreModel):
    battery_capacity_kwh: float = Field(gt=0)
    max_charge_rate_kw: float | None = Field(default=None, gt=0)
    make: str | None = None
    model: str | None = None


class BatteryUrgency(FirestoreModel):
    score: float = Field(ge=0, le=100)
    level: UrgencyLevel
    explanation: list[str]
    calculated_at: AwareDatetime


class RecommendedSlot(FirestoreModel):
    start_at: AwareDatetime
    end_at: AwareDatetime

    @model_validator(mode="after")
    def validate_slot_order(self):
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be later than start_at")
        return self


class CurrentRecommendation(FirestoreModel):
    charger_id: str = Field(min_length=1)
    recommended_slot: RecommendedSlot
    predicted_wait_minutes: float = Field(ge=0)
    priority_score: float = Field(ge=0, le=100)
    explanation: list[str]
    reallocation_reason: str | None = None
    changed_from_charger_id: str | None = None


class EV(FirestoreModel):
    battery_percent: float = Field(ge=0, le=100)
    required_charge_percent: float = Field(ge=0, le=100)
    current_location: GeoPoint
    destination: GeoPoint
    vehicle: VehicleDetails
    input_source: EVInputSource
    created_at: AwareDatetime
    updated_at: AwareDatetime
    remaining_range_km: float | None = Field(default=None, gt=0)
    urgency: BatteryUrgency | None = None
    current_recommendation: CurrentRecommendation | None = None


class Connector(FirestoreModel):
    connector_type: str = Field(min_length=1)
    power_kw: float = Field(gt=0)
    total_count: int = Field(ge=0)
    available_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_available_count(self):
        if self.available_count > self.total_count:
            raise ValueError("available_count cannot exceed total_count")
        return self


class QueueSnapshot(FirestoreModel):
    current_count: int = Field(ge=0)
    observed_at: AwareDatetime
    predicted_count: int | None = Field(default=None, ge=0)
    predicted_wait_minutes: float | None = Field(default=None, ge=0)
    predicted_at: AwareDatetime | None = None


class GridSnapshot(FirestoreModel):
    current_load_kw: float = Field(ge=0)
    capacity_kw: float = Field(gt=0)
    active_session_count: int = Field(ge=0)
    expected_incoming_demand_kw: float = Field(ge=0)
    predicted_peak_load_kw: float = Field(ge=0)
    updated_at: AwareDatetime


class Charger(FirestoreModel):
    station_name: str = Field(min_length=1)
    location: GeoPoint
    connectors: list[Connector] = Field(min_length=1)
    queue: QueueSnapshot
    grid: GridSnapshot
    data_source: DataSource
    updated_at: AwareDatetime


class QueuePrediction(FirestoreModel):
    charger_id: str = Field(min_length=1)
    current_queue_count: int = Field(ge=0)
    current_queue_observed_at: AwareDatetime
    predicted_queue_count: int = Field(ge=0)
    predicted_wait_minutes: float = Field(ge=0)
    prediction_timestamp: AwareDatetime
    forecast_at: AwareDatetime
    forecast_horizon_minutes: int = Field(gt=0)
    prediction_method: Literal["observed_session_baseline"]
    historical_session_count: int = Field(ge=1)
    historical_data_sources: list[DataSource]
    explanation: str = Field(min_length=1)


class PriorityLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PriorityFactor(FirestoreModel):
    value: float
    score: float = Field(ge=0, le=100)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=100)


class EVPriorityResult(FirestoreModel):
    ev_id: str = Field(min_length=1)
    priority_score: float = Field(ge=0, le=100)
    priority_level: PriorityLevel
    factors: dict[str, PriorityFactor]
    explanation: str = Field(min_length=1)
    calculated_at: AwareDatetime


class GridStatus(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    HIGH = "HIGH"
    OVERLOADED = "OVERLOADED"


class GridIntelligenceResult(FirestoreModel):
    charger_id: str = Field(min_length=1)
    current_load_kw: float = Field(ge=0)
    capacity_kw: float = Field(gt=0)
    current_utilization_percent: float = Field(ge=0)
    current_headroom_kw: float
    expected_incoming_demand_kw: float = Field(ge=0)
    predicted_peak_load_kw: float = Field(ge=0)
    projected_peak_utilization_percent: float = Field(ge=0)
    projected_headroom_kw: float
    grid_risk_score: float = Field(ge=0, le=100)
    grid_status: GridStatus
    calculated_at: AwareDatetime
    explanation: str = Field(min_length=1)


class RecommendationPrioritySummary(FirestoreModel):
    score: float = Field(ge=0, le=100)
    level: PriorityLevel
    explanation: str = Field(min_length=1)


class RecommendationScoreBreakdown(FirestoreModel):
    distance_score: float = Field(ge=0, le=100)
    wait_score: float = Field(ge=0, le=100)
    grid_score: float = Field(ge=0, le=100)
    charging_power_score: float = Field(ge=0, le=100)


class RecommendationWeights(FirestoreModel):
    distance: float = Field(ge=0, le=100)
    wait: float = Field(ge=0, le=100)
    grid: float = Field(ge=0, le=100)
    charging_power: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_weight_total(self):
        total = self.distance + self.wait + self.grid + self.charging_power
        if abs(total - 100) > 0.01:
            raise ValueError("recommendation weights must total 100")
        return self


class EmergencyActivation(FirestoreModel):
    active: bool = False
    reason: str = Field(min_length=1)
    battery_percent: float = Field(ge=0, le=100)
    priority_score: float = Field(ge=0, le=100)
    priority_level: PriorityLevel


class EmergencyRecommendationDetail(FirestoreModel):
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)
    predicted_wait_minutes: float = Field(ge=0)
    distance_km: float = Field(ge=0)
    grid_status: GridStatus
    grid_risk_score: float = Field(ge=0, le=100)
    available_charging_power_kw: float = Field(gt=0)
    explanation: str = Field(min_length=1)


class EmergencyAlternative(FirestoreModel):
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)
    predicted_wait_minutes: float = Field(ge=0)
    distance_km: float = Field(ge=0)
    grid_status: GridStatus
    reason: str = Field(min_length=1)


class EmergencyReachability(FirestoreModel):
    verified: bool = False
    reason: str = Field(min_length=1)


class EmergencyScoreBreakdown(FirestoreModel):
    wait_score: float = Field(ge=0, le=100)
    charging_power_score: float = Field(ge=0, le=100)
    grid_score: float = Field(ge=0, le=100)
    distance_score: float = Field(ge=0, le=100)


class EmergencyWeights(FirestoreModel):
    wait: float = Field(ge=0, le=100)
    charging_power: float = Field(ge=0, le=100)
    grid: float = Field(ge=0, le=100)
    distance: float = Field(ge=0, le=100)

    @model_validator(mode="after")
    def validate_weight_total(self):
        total = self.wait + self.charging_power + self.grid + self.distance
        if abs(total - 100) > 0.01:
            raise ValueError("emergency weights must total 100")
        return self


class EmergencyRecommendationResult(FirestoreModel):
    ev_id: str = Field(min_length=1)
    emergency: EmergencyActivation
    recommendation: EmergencyRecommendationDetail | None = None
    reachability: EmergencyReachability
    score_breakdown: EmergencyScoreBreakdown
    weights: EmergencyWeights
    alternatives: list[EmergencyAlternative] = Field(default_factory=list)


class RecommendedCharger(FirestoreModel):
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)
    distance_km: float = Field(ge=0)
    predicted_wait_minutes: float = Field(ge=0)
    grid_status: GridStatus
    grid_risk_score: float = Field(ge=0, le=100)
    available_charging_power_kw: float = Field(gt=0)
    suitable_charging_power_kw: float = Field(gt=0)
    explanation: str = Field(min_length=1)


class RecommendationAlternative(FirestoreModel):
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    score: float = Field(ge=0, le=100)
    predicted_wait_minutes: float = Field(ge=0)
    grid_status: GridStatus
    reason: str = Field(min_length=1)


class ExcludedRecommendationCandidate(FirestoreModel):
    charger_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class EVChargerRecommendation(FirestoreModel):
    ev_id: str = Field(min_length=1)
    priority: RecommendationPrioritySummary
    recommendation: RecommendedCharger
    score_breakdown: RecommendationScoreBreakdown
    weights: RecommendationWeights
    weighting_explanation: str = Field(min_length=1)
    alternatives: list[RecommendationAlternative]
    excluded_candidates: list[ExcludedRecommendationCandidate]
    excluded_candidate_count: int = Field(ge=0)


class ReservationCreateRequest(FirestoreModel):
    ev_id: str = Field(min_length=1)
    charger_id: str = Field(min_length=1)
    slot_start: AwareDatetime
    slot_end: AwareDatetime

    @model_validator(mode="after")
    def validate_slot_order(self):
        if self.slot_end <= self.slot_start:
            raise ValueError("slot_end must be later than slot_start")
        return self


class SlotPrioritySummary(FirestoreModel):
    score: float = Field(ge=0, le=100)
    level: PriorityLevel


class SlotOption(FirestoreModel):
    start: AwareDatetime
    end: AwareDatetime
    waiting_minutes: float = Field(ge=0)
    charging_duration_minutes: int = Field(gt=0)
    priority_suitability_score: float = Field(ge=0, le=100)
    grid_suitability_score: float = Field(ge=0, le=100)
    occupied_connectors: int = Field(ge=0)
    serviceable_connector_capacity: int = Field(gt=0)
    score: float = Field(ge=0, le=100)


class SlotChargingDetails(FirestoreModel):
    energy_required_kwh: float = Field(gt=0)
    charging_power_kw: float = Field(gt=0)


class EVSlotRecommendation(FirestoreModel):
    ev_id: str = Field(min_length=1)
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    priority: SlotPrioritySummary
    slot: SlotOption
    charging: SlotChargingDetails
    grid_status: GridStatus
    grid_risk_score: float = Field(ge=0, le=100)
    explanation: str = Field(min_length=1)
    alternatives: list[SlotOption]


class AllocationHistoryItem(FirestoreModel):
    charger_id: str = Field(min_length=1)
    slot_start: AwareDatetime
    slot_end: AwareDatetime
    change_reason: str = Field(min_length=1)
    changed_at: AwareDatetime

    @model_validator(mode="after")
    def validate_slot_order(self):
        if self.slot_end <= self.slot_start:
            raise ValueError("slot_end must be later than slot_start")
        return self


class Reservation(FirestoreModel):
    ev_id: str = Field(min_length=1)
    charger_id: str = Field(min_length=1)
    slot_start: AwareDatetime
    slot_end: AwareDatetime
    status: ReservationStatus
    allocation_history: list[AllocationHistoryItem] = Field(default_factory=list)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_slot_order(self):
        if self.slot_end <= self.slot_start:
            raise ValueError("slot_end must be later than slot_start")
        return self


class ReservationRecord(Reservation):
    id: str = Field(min_length=1)


class ReallocationCurrentContext(FirestoreModel):
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    slot_start: AwareDatetime
    slot_end: AwareDatetime
    score: float = Field(ge=0, le=100)
    predicted_wait_minutes: float = Field(ge=0)
    grid_status: GridStatus
    grid_risk_score: float = Field(ge=0, le=100)


class ReallocationDecision(FirestoreModel):
    recommended: bool = False
    alternative_charger_id: str | None = None
    alternative_station_name: str | None = None
    alternative_slot_start: AwareDatetime | None = None
    alternative_slot_end: AwareDatetime | None = None
    alternative_score: float | None = Field(default=None, ge=0, le=100)
    score_improvement: float | None = None
    reason: str = Field(min_length=1)


class ReservationReallocationAssessment(FirestoreModel):
    reservation_id: str = Field(min_length=1)
    ev_id: str = Field(min_length=1)
    current: ReallocationCurrentContext
    reallocation: ReallocationDecision


class ChargingSession(FirestoreModel):
    ev_id: str = Field(min_length=1)
    charger_id: str = Field(min_length=1)
    status: ChargingSessionStatus
    arrived_at: AwareDatetime
    data_source: DataSource
    created_at: AwareDatetime
    updated_at: AwareDatetime
    reservation_id: str | None = None
    charging_started_at: AwareDatetime | None = None
    charging_ended_at: AwareDatetime | None = None
    queue_exited_at: AwareDatetime | None = None
    energy_delivered_kwh: float | None = Field(default=None, ge=0)


class SimulationInput(FirestoreModel):
    incoming_ev_count: int = Field(ge=0)
    window_minutes: int = Field(gt=0)


class SimulationRequest(FirestoreModel):
    incoming_ev_count: int = Field(ge=1, le=200)
    window_minutes: int = Field(gt=0, le=720)


SimulationRunRequest = SimulationRequest


class SimulationMetrics(FirestoreModel):
    average_wait_minutes: float = Field(ge=0)
    maximum_wait_minutes: float = Field(ge=0)
    peak_grid_utilization_percent: float = Field(ge=0)
    overloaded_station_count: int = Field(ge=0)
    unassigned_ev_count: int = Field(ge=0)
    assigned_ev_count: int = Field(ge=0)


class StationSimulationSnapshot(FirestoreModel):
    queue: int = Field(ge=0)
    wait_minutes: float = Field(ge=0)
    peak_load_kw: float = Field(ge=0)
    peak_utilization_percent: float = Field(ge=0)


class StationSimulationResult(FirestoreModel):
    charger_id: str = Field(min_length=1)
    station_name: str = Field(min_length=1)
    baseline: StationSimulationSnapshot
    grid_flow: StationSimulationSnapshot


class SimulationImpact(FirestoreModel):
    wait_improvement_percent: float = 0.0
    peak_grid_utilization_change_percent: float = 0.0
    overload_reduction: int = 0
    unassigned_ev_reduction: int = 0


class SimulationResults(FirestoreModel):
    baseline: SimulationMetrics
    grid_flow: SimulationMetrics
    stations: list[StationSimulationResult]


class SimulationRunResult(FirestoreModel):
    simulation_id: str = Field(min_length=1)
    input: SimulationInput
    baseline: SimulationMetrics
    grid_flow: SimulationMetrics
    impact: SimulationImpact
    stations: list[StationSimulationResult]


class SimulationRun(FirestoreModel):
    input: SimulationInput
    results: SimulationResults
    data_source: Literal["simulated"]
    created_at: AwareDatetime
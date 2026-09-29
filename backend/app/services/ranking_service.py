from math import asin, cos, radians, sin, sqrt

from ..models import Charger, EV


_EARTH_RADIUS_KM = 6371.0088
_DISTANCE_SCALE_KM = 50
_QUEUE_SCALE = 20
_CHARGING_POWER_SCALE_KW = 350
_WEIGHTS = {
    "distance": 0.35,
    "queue": 0.25,
    "grid_load": 0.25,
    "charging_power": 0.15,
}


def _distance_km(first, second):
    latitude_delta = radians(second.latitude - first.latitude)
    longitude_delta = radians(second.longitude - first.longitude)
    first_latitude = radians(first.latitude)
    second_latitude = radians(second.latitude)
    haversine = (
        sin(latitude_delta / 2) ** 2
        + cos(first_latitude)
        * cos(second_latitude)
        * sin(longitude_delta / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * asin(sqrt(haversine))


def rank_available_chargers(ev: EV, chargers: list[tuple[str, Charger]]):
    ranked = []
    for charger_id, charger in chargers:
        available_connectors = [
            connector
            for connector in charger.connectors
            if connector.available_count > 0
        ]
        if not available_connectors:
            continue

        distance = _distance_km(ev.current_location, charger.location)
        queue_count = charger.queue.current_count
        grid_load_percent = (
            charger.grid.current_load_kw / charger.grid.capacity_kw * 100
        )
        charging_power_kw = max(
            connector.power_kw for connector in available_connectors
        )

        distance_score = max(0, 1 - distance / _DISTANCE_SCALE_KM)
        queue_score = max(0, 1 - queue_count / _QUEUE_SCALE)
        grid_score = max(0, 1 - min(grid_load_percent, 100) / 100)
        power_score = min(charging_power_kw / _CHARGING_POWER_SCALE_KW, 1)
        score = round(
            100
            * (
                _WEIGHTS["distance"] * distance_score
                + _WEIGHTS["queue"] * queue_score
                + _WEIGHTS["grid_load"] * grid_score
                + _WEIGHTS["charging_power"] * power_score
            ),
            2,
        )

        ranked.append(
            {
                "chargerId": charger_id,
                "distanceKm": round(distance, 2),
                "currentQueue": queue_count,
                "gridLoadPercent": round(grid_load_percent, 2),
                "chargingPowerKw": charging_power_kw,
                "available": True,
                "baselineScore": score,
                "explanation": (
                    f"35% distance ({distance:.1f} km), 25% queue ({queue_count}), "
                    f"25% grid load ({grid_load_percent:.1f}%), and 15% available "
                    f"charging power ({charging_power_kw:g} kW); availability is required."
                ),
            }
        )

    return sorted(ranked, key=lambda item: (-item["baselineScore"], item["chargerId"]))
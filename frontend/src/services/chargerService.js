import api from "./api";

export function fetchCharger(chargerId) {
  return api
    .get(`/api/chargers/${encodeURIComponent(chargerId)}`)
    .then((response) => response.data);
}

export function fetchChargerGrid(chargerId) {
  return api
    .get(`/api/chargers/${encodeURIComponent(chargerId)}/grid`)
    .then((response) => response.data);
}

export function fetchQueuePrediction(chargerId) {
  return api
    .get(`/api/queue/${encodeURIComponent(chargerId)}/prediction`)
    .then((response) => response.data);
}

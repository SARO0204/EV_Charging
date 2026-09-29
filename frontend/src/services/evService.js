import api from "./api";

export function fetchEv(evId) {
  return api
    .get(`/api/ev/${encodeURIComponent(evId)}`)
    .then((response) => response.data);
}

export function fetchEvPriority(evId) {
  return api
    .get(`/api/ev/${encodeURIComponent(evId)}/priority`)
    .then((response) => response.data);
}

export function fetchEvRecommendation(evId) {
  return api
    .get(`/api/ev/${encodeURIComponent(evId)}/recommendation`)
    .then((response) => response.data);
}

export function fetchEvSlotRecommendation(evId) {
  return api
    .get(`/api/ev/${encodeURIComponent(evId)}/slot-recommendation`)
    .then((response) => response.data);
}

export function fetchEvEmergency(evId) {
  return api
    .get(`/api/ev/${encodeURIComponent(evId)}/emergency`)
    .then((response) => response.data);
}

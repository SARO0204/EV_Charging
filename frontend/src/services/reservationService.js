import api from "./api";

export function createReservation(payload) {
  return api
    .post("/api/reservations", payload)
    .then((response) => response.data);
}

export function fetchReservation(reservationId) {
  return api
    .get(`/api/reservations/${encodeURIComponent(reservationId)}`)
    .then((response) => response.data);
}

export function cancelReservation(reservationId) {
  return api
    .patch(`/api/reservations/${encodeURIComponent(reservationId)}/cancel`)
    .then((response) => response.data);
}

export function checkReallocation(reservationId) {
  return api
    .get(
      `/api/reservations/${encodeURIComponent(reservationId)}/reallocation-check`,
    )
    .then((response) => response.data);
}

export function applyReallocation(reservationId) {
  return api
    .post(`/api/reservations/${encodeURIComponent(reservationId)}/reallocate`)
    .then((response) => response.data);
}

import api from "./api";

export function runSimulation(payload) {
  return api
    .post("/api/simulation/run", payload)
    .then((response) => response.data);
}

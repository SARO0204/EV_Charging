export async function fetchRoadRoute(origin, destination) {
  if (!origin || !destination) {
    throw new Error("Route endpoints are unavailable.");
  }

  const coordinates = [
    `${origin.longitude},${origin.latitude}`,
    `${destination.longitude},${destination.latitude}`,
  ].join(";");
  const endpoint = `https://router.project-osrm.org/route/v1/driving/${coordinates}?overview=full&geometries=geojson&steps=false`;
  const response = await fetch(endpoint, {
    headers: { Accept: "application/json" },
  });

  if (!response.ok) {
    throw new Error("Routing service returned an error.");
  }

  const payload = await response.json();
  const route = payload.routes?.[0];
  if (
    payload.code !== "Ok" ||
    route?.geometry?.type !== "LineString" ||
    !Array.isArray(route.geometry.coordinates) ||
    route.geometry.coordinates.length < 2
  ) {
    throw new Error("No road route was returned.");
  }

  return {
    geometry: route.geometry,
    distanceMeters: route.distance,
    durationSeconds: route.duration,
  };
}

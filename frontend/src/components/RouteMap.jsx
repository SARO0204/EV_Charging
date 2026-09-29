import { useEffect } from "react";
import {
  CircleMarker,
  MapContainer,
  Polyline,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";

function RouteBounds({ coordinates }) {
  const map = useMap();

  useEffect(() => {
    const bounds = coordinates.map(([longitude, latitude]) => [
      latitude,
      longitude,
    ]);
    map.fitBounds(bounds, { padding: [36, 36], maxZoom: 15 });
  }, [coordinates, map]);

  return null;
}

export default function RouteMap({ origin, destination, route }) {
  const coordinates = route.geometry.coordinates;
  const positions = coordinates.map(([longitude, latitude]) => [
    latitude,
    longitude,
  ]);

  return (
    <MapContainer
      center={[origin.latitude, origin.longitude]}
      zoom={12}
      scrollWheelZoom
      className="h-full min-h-[360px] rounded-xl"
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <RouteBounds coordinates={coordinates} />
      <Polyline
        positions={positions}
        pathOptions={{ color: "#087f5b", weight: 6, opacity: 0.9 }}
      />
      <CircleMarker
        center={[origin.latitude, origin.longitude]}
        radius={9}
        pathOptions={{
          color: "#075e45",
          fillColor: "#ffffff",
          fillOpacity: 1,
          weight: 4,
        }}
      >
        <Tooltip
          permanent
          direction="top"
          offset={[0, -7]}
          className="route-marker-label"
        >
          EV location
        </Tooltip>
      </CircleMarker>
      <CircleMarker
        center={[destination.latitude, destination.longitude]}
        radius={10}
        pathOptions={{
          color: "#b45309",
          fillColor: "#fbbf24",
          fillOpacity: 1,
          weight: 3,
        }}
      >
        <Tooltip
          permanent
          direction="top"
          offset={[0, -8]}
          className="route-marker-label"
        >
          Charger
        </Tooltip>
      </CircleMarker>
    </MapContainer>
  );
}

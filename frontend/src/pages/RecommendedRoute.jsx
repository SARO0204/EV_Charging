import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import RouteMap from "../components/RouteMap";
import { useFlow } from "../context/FlowContext";
import { fetchRoadRoute } from "../services/routingService";

function formatDistance(meters) {
  return meters >= 1000
    ? `${(meters / 1000).toFixed(1)} km`
    : `${Math.round(meters)} m`;
}

function formatDuration(seconds) {
  const minutes = Math.max(1, Math.ceil(seconds / 60));
  return minutes >= 60
    ? `${Math.floor(minutes / 60)} hr ${minutes % 60} min`
    : `${minutes} min`;
}

export default function RecommendedRoute() {
  const { flow } = useFlow();
  const [route, setRoute] = useState(null);
  const [loading, setLoading] = useState(true);
  const [routeError, setRouteError] = useState(false);
  const origin = flow.ev?.current_location;
  const destination = flow.selectedCharger?.location;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setRouteError(false);
    fetchRoadRoute(origin, destination)
      .then((result) => {
        if (active) setRoute(result);
      })
      .catch(() => {
        if (active) {
          setRoute(null);
          setRouteError(true);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    origin?.latitude,
    origin?.longitude,
    destination?.latitude,
    destination?.longitude,
  ]);

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Step 03 · Estimated route
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">
            Road guidance to your charger.
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            {flow.evId} · {flow.selectedCharger?.station_name}
          </p>
        </div>
        <Link
          to="/intelligence"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:border-slate-400"
        >
          Back to intelligence
        </Link>
      </header>

      <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_300px]">
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
          <div className="relative h-[min(68vh,620px)] min-h-90 overflow-hidden rounded-xl">
            {route ? (
              <RouteMap
                origin={origin}
                destination={destination}
                route={route}
              />
            ) : (
              <div className="grid h-full place-items-center bg-[#e7ede8] px-6 text-center">
                <div>
                  {loading ? (
                    <p role="status" className="font-medium text-slate-700">
                      Calculating route…
                    </p>
                  ) : routeError ? (
                    <>
                      <p role="alert" className="font-semibold text-slate-900">
                        Route could not be calculated.
                      </p>
                      <p className="mt-2 max-w-sm text-sm text-slate-600">
                        The charger recommendation is still available. Map
                        routing needs a connection to the prototype routing
                        service.
                      </p>
                    </>
                  ) : null}
                </div>
              </div>
            )}
          </div>
        </div>

        <aside className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              Recommended charger
            </p>
            <h2 className="mt-2 text-xl font-semibold text-slate-950">
              {flow.selectedCharger?.station_name}
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              {flow.recommendation?.recommendation?.grid_status} grid status ·{" "}
              {flow.recommendation?.recommendation?.predicted_wait_minutes} min
              predicted wait
            </p>
          </div>

          {route ? (
            <dl className="mt-6 grid grid-cols-2 gap-4 border-y border-slate-100 py-5">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Estimated route
                </dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-slate-950">
                  {formatDistance(route.distanceMeters)}
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                  Estimated travel time
                </dt>
                <dd className="mt-1 text-xl font-semibold tabular-nums text-slate-950">
                  {formatDuration(route.durationSeconds)}
                </dd>
              </div>
            </dl>
          ) : null}

          <p className="mt-4 text-xs leading-5 text-slate-500">
            Route geometry from OSRM using OpenStreetMap road data. Travel time
            is an estimate, not live traffic guidance or a guaranteed arrival
            time.
          </p>

          <div className="mt-auto flex flex-col gap-2 pt-7">
            <Link
              to="/reservation"
              className="rounded-lg bg-emerald-800 px-4 py-3 text-center text-sm font-semibold text-white hover:bg-emerald-900"
            >
              Continue to Charging Slot
            </Link>
            <Link
              to="/intelligence"
              className="rounded-lg px-4 py-2 text-center text-sm font-semibold text-slate-600 hover:bg-slate-50"
            >
              Back
            </Link>
          </div>
        </aside>
      </section>
    </div>
  );
}

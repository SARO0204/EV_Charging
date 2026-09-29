import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useFlow } from "../context/FlowContext";
import { fetchDashboardOverview } from "../services/dashboardService";
import { fetchEv, fetchEvPriority } from "../services/evService";

function CoordinatePair({ label, location }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </dt>
      <dd className="mt-1 font-mono text-sm text-slate-800">
        {location
          ? `${location.latitude.toFixed(4)}, ${location.longitude.toFixed(4)}`
          : "Not available"}
      </dd>
    </div>
  );
}

export default function EVConsole() {
  const { flow, updateFlow } = useFlow();
  const navigate = useNavigate();
  const [evId, setEvId] = useState(flow.evId);
  const [evOptions, setEvOptions] = useState([]);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchDashboardOverview()
      .then((overview) => {
        if (active) {
          setEvOptions(overview.evs || []);
        }
      })
      .catch(() => {
        if (active) {
          setEvOptions([]);
        }
      })
      .finally(() => {
        if (active) {
          setLoadingOptions(false);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function analyzeEv(event) {
    event.preventDefault();
    const requestedId = evId.trim();
    if (!requestedId) {
      setError("Enter an EV ID to begin the charging analysis.");
      return;
    }

    setLoading(true);
    setError("");
    try {
      const [ev, priority] = await Promise.all([
        fetchEv(requestedId),
        fetchEvPriority(requestedId),
      ]);
      updateFlow({
        evId: ev.id,
        ev,
        priority,
        recommendation: null,
        selectedCharger: null,
        queue: null,
        grid: null,
        slot: null,
        reservation: null,
      });
      navigate("/intelligence");
    } catch (requestError) {
      setError(requestError.message || "Unable to analyze this EV.");
    } finally {
      setLoading(false);
    }
  }

  const currentEv = flow.ev;

  return (
    <div className="space-y-6">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
        <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm sm:p-8">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Step 01 · Vehicle context
          </p>
          <h1 className="mt-3 max-w-xl text-3xl font-semibold leading-tight text-slate-950 sm:text-4xl">
            Start with the EV.
          </h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-slate-600">
            GridFlow uses the vehicle’s charge need and location to evaluate
            nearby charging options.
          </p>

          <form onSubmit={analyzeEv} className="mt-7 space-y-4">
            <label
              htmlFor="ev-id"
              className="block text-sm font-medium text-slate-800"
            >
              EV ID
            </label>
            <div className="flex flex-col gap-3 sm:flex-row">
              <input
                id="ev-id"
                list="available-evs"
                autoComplete="off"
                value={evId}
                onChange={(event) => setEvId(event.target.value)}
                placeholder="Choose or enter an EV ID"
                className="min-w-0 flex-1 rounded-lg border border-slate-300 bg-white px-3.5 py-3 text-sm outline-none transition focus:border-emerald-700 focus:ring-2 focus:ring-emerald-100"
              />
              <datalist id="available-evs">
                {evOptions.map((item) => (
                  <option key={item.id} value={item.id} />
                ))}
              </datalist>
              <button
                type="submit"
                disabled={loading}
                className="rounded-lg bg-emerald-800 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-900 disabled:cursor-wait disabled:opacity-60"
              >
                {loading ? "Analyzing…" : "Analyze EV"}
              </button>
            </div>
            {error ? (
              <p role="alert" className="text-sm text-rose-700">
                {error}
              </p>
            ) : null}
            <p className="text-xs text-slate-500">
              {loadingOptions
                ? "Loading available EVs…"
                : `${evOptions.length} EVs available from the data provider`}
            </p>
          </form>
        </section>

        <aside className="flex flex-col justify-between rounded-xl bg-slate-950 p-6 text-white sm:p-8">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-300">
              Charging context
            </p>
            <h2 className="mt-3 text-xl font-semibold">
              One vehicle, one live analysis.
            </h2>
            <p className="mt-3 text-sm leading-6 text-slate-300">
              Priority and charging recommendations come from the GridFlow
              backend. No scoring is performed in the browser.
            </p>
          </div>
          {currentEv ? (
            <dl className="mt-7 grid grid-cols-2 gap-x-5 gap-y-5 border-t border-white/15 pt-5">
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Battery
                </dt>
                <dd className="mt-1 text-lg font-semibold">
                  {currentEv.battery_percent}%
                </dd>
              </div>
              <div>
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Required charge
                </dt>
                <dd className="mt-1 text-lg font-semibold">
                  {currentEv.required_charge_percent}%
                </dd>
              </div>
              <div className="col-span-2">
                <dt className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Vehicle
                </dt>
                <dd className="mt-1 text-sm">
                  {[currentEv.vehicle.make, currentEv.vehicle.model]
                    .filter(Boolean)
                    .join(" ") || "EV"}{" "}
                  · {currentEv.vehicle.battery_capacity_kwh} kWh
                </dd>
              </div>
              <CoordinatePair
                label="Current location"
                location={currentEv.current_location}
              />
              <CoordinatePair
                label="Destination"
                location={currentEv.destination}
              />
              {currentEv.urgency ? (
                <div className="col-span-2">
                  <dt className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                    Saved urgency
                  </dt>
                  <dd className="mt-1 text-sm">
                    {currentEv.urgency.level} · {currentEv.urgency.score}/100
                  </dd>
                </div>
              ) : null}
            </dl>
          ) : (
            <div className="mt-8 border-t border-white/15 pt-5 text-sm text-slate-300">
              Analyze an EV to see its battery, vehicle and location context
              here.
            </div>
          )}
        </aside>
      </div>

      {currentEv ? (
        <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4">
          <div>
            <p className="text-sm font-semibold text-emerald-950">
              Current analysis: {flow.evId}
            </p>
            <p className="mt-1 text-sm text-emerald-800">
              Priority {flow.priority?.priority_level} · score{" "}
              {flow.priority?.priority_score}
            </p>
          </div>
          <Link
            to="/intelligence"
            className="rounded-lg border border-emerald-800 px-4 py-2 text-sm font-semibold text-emerald-900 hover:bg-white"
          >
            Continue analysis
          </Link>
        </section>
      ) : null}
    </div>
  );
}

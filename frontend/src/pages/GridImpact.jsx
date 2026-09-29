import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { runSimulation } from "../services/simulationService";

function Metric({ label, value, unit = "", dark = false }) {
  return (
    <div
      className={`border-t py-3 ${dark ? "border-white/15" : "border-slate-100"}`}
    >
      <dt
        className={`text-xs font-medium ${dark ? "text-slate-400" : "text-slate-500"}`}
      >
        {label}
      </dt>
      <dd
        className={`mt-1 text-lg font-semibold tabular-nums ${dark ? "text-white" : "text-slate-950"}`}
      >
        {value}
        {unit}
      </dd>
    </div>
  );
}

export default function GridImpact() {
  const [incomingEvCount, setIncomingEvCount] = useState(5);
  const [windowMinutes, setWindowMinutes] = useState(30);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const firstRun = useRef(false);

  async function calculateImpact(
    count = incomingEvCount,
    window = windowMinutes,
  ) {
    setLoading(true);
    setError("");
    try {
      const simulation = await runSimulation({
        incoming_ev_count: Number(count),
        window_minutes: Number(window),
      });
      setResult(simulation);
    } catch (requestError) {
      setError(requestError.message || "Simulation could not be run.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!firstRun.current) {
      firstRun.current = true;
      calculateImpact(5, 30);
    }
  }, []);

  const baseline = result?.baseline;
  const gridFlow = result?.grid_flow;
  const impact = result?.impact;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-emerald-800">
            Step 05 · Grid impact
          </p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">
            Compare the operating strategies.
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            A what-if simulation using the current charger network and backend
            calculation.
          </p>
        </div>
        <Link
          to="/reservation"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:border-slate-400"
        >
          Back to reservation
        </Link>
      </header>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          calculateImpact();
        }}
        className="flex flex-wrap items-end gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
      >
        <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Incoming EVs
          <input
            type="number"
            min="1"
            max="200"
            value={incomingEvCount}
            onChange={(event) => setIncomingEvCount(event.target.value)}
            className="w-32 rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-medium text-slate-900 outline-none focus:border-emerald-700"
          />
        </label>
        <label className="grid gap-1.5 text-xs font-semibold uppercase tracking-wider text-slate-500">
          Arrival window · minutes
          <input
            type="number"
            min="1"
            max="720"
            value={windowMinutes}
            onChange={(event) => setWindowMinutes(event.target.value)}
            className="w-40 rounded-lg border border-slate-300 px-3 py-2.5 text-sm font-medium text-slate-900 outline-none focus:border-emerald-700"
          />
        </label>
        <button
          type="submit"
          disabled={loading}
          className="rounded-lg bg-emerald-800 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-900 disabled:cursor-wait disabled:opacity-60"
        >
          {loading ? "Running simulation…" : "Run simulation"}
        </button>
        <span className="text-xs text-slate-500">
          Each run uses current backend charger data.
        </span>
      </form>

      {error ? (
        <p
          role="alert"
          className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800"
        >
          {error}
        </p>
      ) : null}
      {loading && !result ? (
        <p role="status" className="text-sm text-slate-600">
          Calculating baseline and GridFlow outcomes…
        </p>
      ) : null}

      {baseline && gridFlow ? (
        <>
          <section className="grid gap-5 lg:grid-cols-2">
            {[
              {
                label: "Baseline",
                metrics: baseline,
                tone: "border-slate-300",
              },
              {
                label: "GridFlow",
                metrics: gridFlow,
                tone: "border-emerald-700",
              },
            ].map(({ label, metrics, tone }) => (
              <article
                key={label}
                className={`rounded-xl border border-slate-200 border-t-4 ${tone} bg-white p-6 shadow-sm`}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="text-xl font-semibold text-slate-950">
                    {label}
                  </h2>
                  <span className="text-xs text-slate-500">
                    {result.input.incoming_ev_count} incoming ·{" "}
                    {result.input.window_minutes} min
                  </span>
                </div>
                <dl className="mt-4 grid gap-x-6 sm:grid-cols-2">
                  <Metric
                    label="Average wait"
                    value={metrics.average_wait_minutes}
                    unit=" min"
                  />
                  <Metric
                    label="Maximum wait"
                    value={metrics.maximum_wait_minutes}
                    unit=" min"
                  />
                  <Metric
                    label="Peak grid utilization"
                    value={metrics.peak_grid_utilization_percent}
                    unit="%"
                  />
                  <Metric
                    label="Overloaded stations"
                    value={metrics.overloaded_station_count}
                  />
                  <Metric
                    label="Unassigned EVs"
                    value={metrics.unassigned_ev_count}
                  />
                  <Metric
                    label="Assigned EVs"
                    value={metrics.assigned_ev_count}
                  />
                </dl>
              </article>
            ))}
          </section>

          <section className="rounded-xl bg-slate-950 p-6 text-white sm:p-7">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-300">
              Calculated impact
            </p>
            <div className="mt-4 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
              <Metric
                dark
                label="Wait improvement"
                value={impact.wait_improvement_percent}
                unit="%"
              />
              <Metric
                dark
                label="Peak utilization change"
                value={impact.peak_grid_utilization_change_percent}
                unit="%"
              />
              <Metric
                dark
                label="Overload reduction"
                value={impact.overload_reduction}
              />
              <Metric
                dark
                label="Unassigned reduction"
                value={impact.unassigned_ev_reduction}
              />
            </div>
            <p className="mt-5 border-t border-white/15 pt-4 text-sm leading-6 text-slate-300">
              The baseline assigns vehicles using its existing policy. GridFlow
              ranks available chargers using priority, wait, grid risk and
              charging power. These are simulated outcomes for the selected
              input, not guarantees about live operations.
            </p>
          </section>
        </>
      ) : null}

      <div className="flex items-center justify-between gap-3">
        <Link
          to="/reservation"
          className="px-2 py-2 text-sm font-semibold text-slate-600 hover:text-slate-950"
        >
          Back
        </Link>
        <Link
          to="/"
          className="rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50"
        >
          Home
        </Link>
      </div>
    </div>
  );
}
